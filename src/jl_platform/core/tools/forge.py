from __future__ import annotations

import importlib.util
import json
import os
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
from typing import Any, Dict

from jl_platform.core.models import ToolSpec
from jl_platform.core.tools.audit import run_audit_tool


@dataclass
class ToolMeta:
    name: str
    description: str
    path: str
    code_sha256: str


class ToolForge:
    """
    Create, run, and delete temporary tools stored on disk.
    Tools persist until explicitly deleted.
    """

    def __init__(self, root: Path) -> None:
        self.root = root
        self.root.mkdir(parents=True, exist_ok=True)
        self.index_path = self.root / "index.json"
        self._index: Dict[str, ToolMeta] = {}
        self._load_index()

    def _load_index(self) -> None:
        if not self.index_path.exists():
            return
        try:
            raw = json.loads(self.index_path.read_text(encoding="utf-8"))
            tools = raw.get("tools", raw) if isinstance(raw, dict) else {}
            if isinstance(tools, dict):
                for name, meta in tools.items():
                    if not isinstance(meta, dict):
                        continue
                    self._index[name] = ToolMeta(
                        name=name,
                        description=meta.get("description", ""),
                        path=meta.get("path", ""),
                        code_sha256=meta.get("code_sha256", ""),
                    )
            if isinstance(raw, dict):
                self._last_created = raw.get("last_created")
        except Exception:
            # If index is corrupt, start fresh.
            self._index = {}

    def _save_index(self) -> None:
        data = {
            name: {
                "description": meta.description,
                "path": meta.path,
                "code_sha256": meta.code_sha256,
            }
            for name, meta in self._index.items()
        }
        payload = {"tools": data, "last_created": getattr(self, "_last_created", None)}
        self.index_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    def _tool_path(self, name: str) -> Path:
        safe = "".join(ch for ch in name if ch.isalnum() or ch in ("_", "-"))
        return self.root / f"{safe}.py"

    def _to_meta_path(self, path: Path) -> str:
        resolved = path.resolve()
        try:
            return resolved.relative_to(self.root.resolve()).as_posix()
        except ValueError:
            return str(resolved)

    def _resolve_meta_path(self, raw_path: str) -> Path:
        candidate = Path(raw_path)
        if not candidate.is_absolute():
            candidate = self.root / candidate
        return candidate.resolve()

    def create_tool(self, name: str, code: str, description: str = "") -> Dict[str, Any]:
        if not name or not name.strip():
            return {"status": "error", "error": "missing_name"}
        if not code or not code.strip():
            return {"status": "error", "error": "missing_code"}

        path = self._tool_path(name)
        code_hash = sha256(code.encode("utf-8")).hexdigest()
        path.write_text(code, encoding="utf-8")

        self._index[name] = ToolMeta(
            name=name.strip(),
            description=description or "",
            path=self._to_meta_path(path),
            code_sha256=code_hash,
        )
        self._last_created = name
        self._save_index()
        return {
            "status": "ok",
            "name": name,
            "path": str(path.resolve()),
            "code_sha256": code_hash,
            "docs": "docs/TOOL_FORGE.md",
        }

    def list_tools(self) -> Dict[str, Any]:
        return {
            "status": "ok",
            "tools": [
                {
                    "name": meta.name,
                    "description": meta.description,
                    "path": meta.path,
                    "code_sha256": meta.code_sha256,
                }
                for meta in self._index.values()
            ],
            "docs": "docs/TOOL_FORGE.md",
        }

    def delete_tool(self, name: str) -> Dict[str, Any]:
        meta = self._index.get(name)
        if not meta:
            return {"status": "error", "error": "not_found"}
        try:
            path = self._resolve_meta_path(meta.path)
            if path.exists():
                path.unlink()
        except Exception as exc:
            return {"status": "error", "error": "delete_failed", "message": str(exc)}
        self._index.pop(name, None)
        self._save_index()
        return {"status": "ok", "deleted": name}

    def promote_tool(self, name: str, promoted_dir: Path) -> Dict[str, Any]:
        meta = self._index.get(name)
        if not meta:
            return {"status": "error", "error": "not_found"}
        src = self._resolve_meta_path(meta.path)
        if not src.exists():
            return {"status": "error", "error": "missing_file", "path": meta.path}
        promoted_dir.mkdir(parents=True, exist_ok=True)
        dst = promoted_dir / src.name
        dst.write_text(src.read_text(encoding="utf-8"), encoding="utf-8")
        return {
            "status": "ok",
            "name": name,
            "promoted_path": str(dst),
            "promote_hint": "Promoted tools are auto-registered from src/jl_platform/core/tools/promoted/.",
        }

    def promote_last(self, promoted_dir: Path) -> Dict[str, Any]:
        name = getattr(self, "_last_created", None)
        if not name:
            return {"status": "error", "error": "no_last_created"}
        return self.promote_tool(name, promoted_dir)

    def run_tool(self, name: str, payload: Dict[str, Any] | None = None) -> Dict[str, Any]:
        meta = self._index.get(name)
        if not meta:
            return {"status": "error", "error": "not_found"}

        path = self._resolve_meta_path(meta.path)
        if not path.exists():
            return {"status": "error", "error": "missing_file", "path": meta.path}

        spec = importlib.util.spec_from_file_location(f"tool_{name}", str(path))
        if spec is None or spec.loader is None:
            return {"status": "error", "error": "load_failed"}
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)  # type: ignore[attr-defined]

        if not hasattr(module, "run"):
            return {"status": "error", "error": "missing_run"}

        result = module.run(payload or {})
        audit = run_audit_tool({"code": path.read_text(encoding="utf-8"), "output": str(result)})
        return {
            "status": "ok",
            "result": result,
            "audit": audit,
            "promote_hint": "If this tool becomes common, consider moving it into core tools.",
        }


def _get_root() -> Path:
    override = os.getenv("JL_TOOLS_RUNTIME_DIR")
    if override and str(override).strip():
        return Path(str(override)).expanduser().resolve()

    default_root = Path(__file__).resolve().parents[3] / "tools_runtime"
    # When installed, __file__ often lives under site-packages and is not writable.
    if any(part.lower() in {"site-packages", "dist-packages"} for part in default_root.parts):
        return (Path.home() / ".jl_engine" / "tools_runtime").expanduser().resolve()
    return default_root


def get_tools_runtime_dir() -> Path:
    """Return the resolved directory used for persisted tools."""
    return _get_root()


def _get_promoted_dir() -> Path:
    override = os.getenv("JL_PROMOTED_TOOLS_DIR")
    if override and str(override).strip():
        return Path(str(override)).expanduser().resolve()

    package_dir = Path(__file__).resolve().parent / "promoted"
    if any(part.lower() in {"site-packages", "dist-packages"} for part in package_dir.parts):
        return (_get_root() / "promoted").expanduser().resolve()
    return package_dir


def get_promoted_tools_dir() -> Path:
    """Return the resolved directory used for promoted tools."""
    return _get_promoted_dir()


_FORGE = ToolForge(_get_root())


def forge_create(payload: Dict[str, Any]) -> Dict[str, Any]:
    return _FORGE.create_tool(
        name=str(payload.get("name", "") or ""),
        code=str(payload.get("code", "") or ""),
        description=str(payload.get("description", "") or ""),
    )


def forge_list(payload: Dict[str, Any]) -> Dict[str, Any]:
    return _FORGE.list_tools()


def forge_delete(payload: Dict[str, Any]) -> Dict[str, Any]:
    return _FORGE.delete_tool(str(payload.get("name", "") or ""))


def forge_run(payload: Dict[str, Any]) -> Dict[str, Any]:
    return _FORGE.run_tool(
        name=str(payload.get("name", "") or ""),
        payload=payload.get("payload") or {},
    )


def forge_promote(payload: Dict[str, Any]) -> Dict[str, Any]:
    promoted_dir = _get_promoted_dir()
    return _FORGE.promote_tool(str(payload.get("name", "") or ""), promoted_dir)


def forge_promote_last(payload: Dict[str, Any]) -> Dict[str, Any]:
    promoted_dir = _get_promoted_dir()
    return _FORGE.promote_last(promoted_dir)


def get_tool_specs() -> list[ToolSpec]:
    return [
        ToolSpec(
            name="forge_create",
            description="Create a temporary tool (persisted until explicitly deleted).",
            input_schema={
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "description": {"type": "string"},
                    "code": {"type": "string"},
                },
                "required": ["name", "code"],
            },
            output_schema={"type": "object"},
        ),
        ToolSpec(
            name="forge_list",
            description="List temporary tools.",
            input_schema={"type": "object"},
            output_schema={"type": "object"},
        ),
        ToolSpec(
            name="forge_run",
            description="Run a temporary tool by name.",
            input_schema={
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "payload": {"type": "object"},
                },
                "required": ["name"],
            },
            output_schema={"type": "object"},
        ),
        ToolSpec(
            name="forge_delete",
            description="Delete a temporary tool by name.",
            input_schema={
                "type": "object",
                "properties": {"name": {"type": "string"}},
                "required": ["name"],
            },
            output_schema={"type": "object"},
        ),
        ToolSpec(
            name="forge_promote",
            description="Promote a temporary tool into core tools (auto-registered).",
            input_schema={
                "type": "object",
                "properties": {"name": {"type": "string"}},
                "required": ["name"],
            },
            output_schema={"type": "object"},
        ),
        ToolSpec(
            name="forge_promote_last",
            description="Promote the most recently created tool into core tools.",
            input_schema={"type": "object"},
            output_schema={"type": "object"},
        ),
    ]
