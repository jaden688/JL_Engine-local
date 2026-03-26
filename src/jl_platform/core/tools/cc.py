from __future__ import annotations

import os
import re
import shlex
import subprocess
import time
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

from jl_platform.core.models import ToolSpec

PROJECT_ROOT = Path(__file__).resolve().parents[4]
DEFAULT_SEARCH_LIMIT = 25
DEFAULT_READ_BYTES = 1_000_000
IGNORED_DIR_NAMES = {".git", ".venv", "__pycache__", ".mypy_cache", ".pytest_cache", "node_modules"}
DEFAULT_MAX_REGEX_QUERY_CHARS = 128


def _normalize_command(command: Any, shell: bool) -> str | list[str]:
    if isinstance(command, list):
        if shell:
            return " ".join(shlex.quote(str(part)) for part in command)
        return [str(part) for part in command]
    if shell:
        return str(command)
    return shlex.split(str(command), posix=os.name != "nt")


def _normalize_windows_command(command: str) -> str:
    normalized = str(command or "").strip()
    if not normalized:
        return normalized

    select_format_pattern = re.compile(
        r"\|\s*Select\s+-Format\s+[\"']([^\"']+)[\"']",
        flags=re.IGNORECASE,
    )

    def _replace_select_format(match: re.Match[str]) -> str:
        columns = [part.strip() for part in str(match.group(1) or "").split(",") if part.strip()]
        if not columns:
            return "| Select-Object *"
        return f"| Select-Object {', '.join(columns)}"

    normalized = select_format_pattern.sub(_replace_select_format, normalized)
    normalized = re.sub(
        r"(Get-Process\s+-Name\s+['\"])([^'\"]+)\.exe(['\"])",
        r"\1\2\3",
        normalized,
        flags=re.IGNORECASE,
    )
    return normalized


def _prepare_command(command: Any, shell: bool) -> tuple[str | list[str], bool]:
    if os.name != "nt":
        return _normalize_command(command, shell=shell), shell

    if shell:
        command_text = _normalize_windows_command(str(command or ""))
        shell_host = shutil.which("pwsh") or shutil.which("powershell") or "powershell"
        return (
            [
                shell_host,
                "-NoLogo",
                "-NoProfile",
                "-NonInteractive",
                "-ExecutionPolicy",
                "Bypass",
                "-Command",
                command_text,
            ],
            False,
        )

    return _normalize_command(command, shell=False), False


def _env_enabled(name: str, default: bool = False) -> bool:
    raw = str(os.getenv(name, "1" if default else "0")).strip().lower()
    return raw not in {"0", "false", "off", "no", ""}


def _is_relative_to(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def _resolve_cwd(cwd: str | None = None) -> Path:
    base = Path(cwd).expanduser() if isinstance(cwd, str) and cwd.strip() else PROJECT_ROOT
    resolved = base.resolve()
    if not resolved.exists() or not resolved.is_dir():
        raise ValueError("invalid_cwd")
    return resolved


def _iter_allowed_roots(base: Path) -> Iterable[Path]:
    candidates = [base, PROJECT_ROOT, PROJECT_ROOT / "artifacts"]
    home = Path.home()
    candidates.extend(home / folder for folder in ("Desktop", "Documents", "Downloads"))
    seen: set[str] = set()
    for candidate in candidates:
        try:
            resolved = candidate.resolve()
        except Exception:
            continue
        key = str(resolved).lower()
        if key in seen:
            continue
        seen.add(key)
        yield resolved


def _path_within_allowed_roots(path: Path, base: Path) -> bool:
    return any(_is_relative_to(path, root) for root in _iter_allowed_roots(base))


def _resolve_path(raw_path: Any, cwd: str | None = None) -> Path:
    text = str(raw_path or "").strip()
    base = _resolve_cwd(cwd)
    if not text:
        return base
    path = Path(text).expanduser()
    resolved = path.resolve() if path.is_absolute() else (base / path).resolve()
    if not _path_within_allowed_roots(resolved, base):
        raise ValueError("path_outside_allowed_roots")
    return resolved


def _clip_text(value: Any, limit: int = 240) -> str:
    text = str(value or "")
    if len(text) <= limit:
        return text
    return text[: limit - 3] + "..."


def _iter_paths(root: Path, recursive: bool) -> Iterable[Path]:
    if not root.exists():
        return []
    if root.is_file():
        return [root]
    if recursive:
        return (path for path in root.rglob("*") if not _path_is_ignored(path))
    return (path for path in root.iterdir() if not _path_is_ignored(path))


def _path_is_ignored(path: Path) -> bool:
    parts = {part.lower() for part in path.parts}
    return any(name in parts for name in IGNORED_DIR_NAMES)


def _read_text(path: Path, max_bytes: int = DEFAULT_READ_BYTES) -> str | None:
    try:
        if path.is_dir():
            return None
        if path.stat().st_size > max_bytes:
            return None
        text = path.read_text(encoding="utf-8", errors="ignore")
    except Exception:
        return None
    if "\x00" in text[:4096]:
        return None
    return text


def _run_subprocess(
    cmd: str | list[str], cwd: str | None = None, timeout: int | None = None, shell: bool | None = None
) -> dict:
    start = time.perf_counter()
    proc = subprocess.run(
        cmd,
        cwd=str(_resolve_cwd(cwd)) if cwd else None,
        capture_output=True,
        text=True,
        timeout=timeout,
        shell=isinstance(cmd, str) if shell is None else shell,
    )
    duration_ms = round((time.perf_counter() - start) * 1000.0, 2)
    return {
        "stdout": proc.stdout or "",
        "stderr": proc.stderr or "",
        "returncode": proc.returncode,
        "duration_ms": duration_ms,
    }


def _fs_list(path: str, cwd: str | None = None) -> dict:
    target = _resolve_path(path or ".", cwd=cwd)
    if not target.exists():
        return {"path": str(target), "entries": [], "exists": False}
    if target.is_file():
        return {
            "path": str(target),
            "exists": True,
            "is_dir": False,
            "entries": [],
            "size": target.stat().st_size,
        }
    entries = []
    for child in sorted(target.iterdir(), key=lambda p: (not p.is_dir(), p.name.lower())):
        if _path_is_ignored(child):
            continue
        child_stat = None
        try:
            child_stat = child.stat()
        except Exception:
            child_stat = None
        entries.append(
            {
                "name": child.name,
                "path": str(child.resolve()),
                "is_dir": child.is_dir(),
                "size": child_stat.st_size if child_stat else None,
            }
        )
    return {"path": str(target), "exists": True, "is_dir": True, "entries": entries}


def _fs_read(path: str, cwd: str | None = None) -> dict:
    target = _resolve_path(path, cwd=cwd)
    try:
        content = target.read_text(encoding="utf-8", errors="ignore")
    except Exception as exc:
        return {"status": "error", "error": "read_failed", "path": str(target), "message": str(exc)}
    return {
        "path": str(target),
        "exists": target.exists(),
        "is_dir": target.is_dir(),
        "bytes": len(content.encode("utf-8")),
        "content": content,
    }


def _fs_write(path: str, content: str, cwd: str | None = None) -> dict:
    target = _resolve_path(path, cwd=cwd)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")
    return {
        "path": str(target),
        "exists": target.exists(),
        "bytes": len(content.encode("utf-8")),
        "created": True,
    }


def _fs_mkdir(path: str, cwd: str | None = None) -> dict:
    target = _resolve_path(path, cwd=cwd)
    target.mkdir(parents=True, exist_ok=True)
    return {
        "path": str(target),
        "exists": target.exists(),
        "is_dir": target.is_dir(),
        "created": True,
    }


def _search_files(
    *,
    root: str,
    query: str,
    cwd: str | None = None,
    recursive: bool = True,
    limit: int = DEFAULT_SEARCH_LIMIT,
    case_sensitive: bool = False,
    regex: bool = False,
    max_bytes: int = DEFAULT_READ_BYTES,
) -> dict:
    search_root = _resolve_path(root or ".", cwd=cwd)
    if search_root.is_file():
        search_root = search_root.parent

    if not query.strip():
        return {
            "status": "error",
            "error": "missing_query",
            "root": str(search_root),
            "matches": [],
        }

    flags = 0 if case_sensitive else re.IGNORECASE
    if regex and not _env_enabled("JL_CC_ENABLE_REGEX_SEARCH", default=False):
        return {
            "status": "error",
            "error": "regex_search_disabled",
            "root": str(search_root),
            "matches": [],
        }
    if regex and len(query) > DEFAULT_MAX_REGEX_QUERY_CHARS:
        return {
            "status": "error",
            "error": "regex_query_too_long",
            "root": str(search_root),
            "matches": [],
        }
    try:
        pattern = re.compile(query, flags) if regex else None
    except re.error:
        return {
            "status": "error",
            "error": "invalid_regex",
            "root": str(search_root),
            "matches": [],
        }
    needle = query if case_sensitive else query.lower()

    matches: list[dict[str, Any]] = []
    for path in _iter_paths(search_root, recursive=recursive):
        if len(matches) >= max(1, int(limit or DEFAULT_SEARCH_LIMIT)):
            break
        if path.is_dir():
            continue

        rel_path = str(path.relative_to(search_root)) if path != search_root else path.name
        rel_cmp = rel_path if case_sensitive else rel_path.lower()
        if pattern:
            if pattern.search(rel_path):
                matches.append(
                    {
                        "path": str(path.resolve()),
                        "match_type": "path",
                        "line_number": None,
                        "snippet": rel_path,
                    }
                )
                continue
        elif needle in rel_cmp:
            matches.append(
                {
                    "path": str(path.resolve()),
                    "match_type": "path",
                    "line_number": None,
                    "snippet": rel_path,
                }
            )
            continue

        text = _read_text(path, max_bytes=max_bytes)
        if text is None:
            continue

        for line_number, line in enumerate(text.splitlines(), start=1):
            line_cmp = line if case_sensitive else line.lower()
            matched = bool(pattern.search(line)) if pattern else needle in line_cmp
            if not matched:
                continue
            matches.append(
                {
                    "path": str(path.resolve()),
                    "match_type": "content",
                    "line_number": line_number,
                    "snippet": _clip_text(line.strip(), 260),
                }
            )
            break

    return {
        "status": "ok",
        "action": "search_files",
        "root": str(search_root),
        "query": query,
        "count": len(matches),
        "matches": matches,
        "truncated": len(matches) >= max(1, int(limit or DEFAULT_SEARCH_LIMIT)),
    }


@dataclass(slots=True)
class CommandCommissioner:
    project_root: Path = PROJECT_ROOT

    def _resolve_action(self, payload: dict[str, Any]) -> str:
        raw = str(
            payload.get("action")
            or payload.get("mode")
            or payload.get("operation")
            or ""
        ).strip().lower()
        aliases = {
            "": "",
            "command": "run",
            "execute": "run",
            "run": "run",
            "shell": "run",
            "subprocess": "run",
            "fs_list": "fs_list",
            "list_dir": "fs_list",
            "ls": "fs_list",
            "fs_read": "fs_read",
            "read": "fs_read",
            "read_file": "fs_read",
            "fs_write": "fs_write",
            "write": "fs_write",
            "write_file": "fs_write",
            "fs_mkdir": "fs_mkdir",
            "mkdir": "fs_mkdir",
            "create_dir": "fs_mkdir",
            "search": "search_files",
            "search_files": "search_files",
            "find": "search_files",
        }
        resolved = aliases.get(raw, raw)
        if resolved:
            return resolved
        if str(payload.get("query") or "").strip():
            return "search_files"
        if str(payload.get("path") or "").strip() and payload.get("content") is not None:
            return "fs_write"
        if payload.get("command") is not None:
            return "run"
        return ""

    def commission(self, payload: dict[str, Any] | None) -> dict:
        safe_payload = payload if isinstance(payload, dict) else {}
        action = self._resolve_action(safe_payload)
        cwd = str(safe_payload.get("cwd") or "").strip() or None

        if action == "run":
            command = safe_payload.get("command")
            if command is None or command == "":
                return {
                    "status": "error",
                    "error": "missing_command",
                    "message": "Missing command",
                }
            timeout_raw = safe_payload.get("timeout")
            timeout = None
            if timeout_raw is not None:
                try:
                    timeout = float(timeout_raw)
                except (TypeError, ValueError):
                    timeout = None
            shell = bool(safe_payload.get("shell", True))
            if shell:
                command_text = str(command or "")
                if not _env_enabled("JL_CC_ENABLE_SHELL_SYNTAX", default=False):
                    blocked_tokens = ("|", ";", "&&", "||", ">", "<", "$(", "`")
                    if any(token in command_text for token in blocked_tokens):
                        return {
                            "status": "error",
                            "action": "run",
                            "error": "shell_syntax_blocked",
                            "message": "Shell metacharacters require JL_CC_ENABLE_SHELL_SYNTAX=1.",
                        }
            normalized, shell_mode = _prepare_command(command, shell=shell)
            start = time.perf_counter()
            try:
                result = _run_subprocess(normalized, cwd=cwd, timeout=timeout, shell=shell_mode)
            except ValueError as exc:
                return {
                    "status": "error",
                    "action": "run",
                    "error": str(exc),
                    "stdout": "",
                    "stderr": "",
                    "command": normalized,
                }
            except subprocess.TimeoutExpired as exc:
                duration_ms = round((time.perf_counter() - start) * 1000.0, 2)
                return {
                    "status": "error",
                    "action": "run",
                    "error": "timeout",
                    "stdout": exc.stdout or "",
                    "stderr": exc.stderr or f"Timed out after {timeout}s",
                    "duration_ms": duration_ms,
                    "command": normalized,
                    "cwd": os.path.abspath(cwd or os.getcwd()),
                }
            except Exception as exc:
                return {
                    "status": "error",
                    "action": "run",
                    "error": "exception",
                    "stdout": "",
                    "stderr": str(exc),
                    "command": normalized,
                    "cwd": os.path.abspath(cwd or os.getcwd()),
                }
            result.update(
                {
                    "status": "ok" if result["returncode"] == 0 else "error",
                    "action": "run",
                    "command": normalized,
                    "cwd": os.path.abspath(cwd or os.getcwd()),
                }
            )
            return result

        if action == "search_files":
            try:
                return _search_files(
                    root=str(safe_payload.get("root") or safe_payload.get("path") or "."),
                    query=str(safe_payload.get("query") or safe_payload.get("pattern") or ""),
                    cwd=cwd,
                    recursive=bool(safe_payload.get("recursive", True)),
                    limit=int(safe_payload.get("limit") or DEFAULT_SEARCH_LIMIT),
                    case_sensitive=bool(safe_payload.get("case_sensitive", False)),
                    regex=bool(safe_payload.get("regex", False)),
                    max_bytes=int(safe_payload.get("max_bytes") or DEFAULT_READ_BYTES),
                )
            except ValueError as exc:
                return {"status": "error", "action": "search_files", "error": str(exc), "matches": []}

        if action == "fs_list":
            try:
                return {"status": "ok", "action": "fs_list", **_fs_list(str(safe_payload.get("path") or "."), cwd=cwd)}
            except ValueError as exc:
                return {"status": "error", "action": "fs_list", "error": str(exc), "entries": []}

        if action == "fs_read":
            path = str(safe_payload.get("path") or "").strip()
            if not path:
                return {"status": "error", "error": "missing_path", "message": "Missing path"}
            try:
                return {"status": "ok", "action": "fs_read", **_fs_read(path, cwd=cwd)}
            except ValueError as exc:
                return {"status": "error", "action": "fs_read", "error": str(exc), "message": "Invalid path"}

        if action == "fs_write":
            path = str(safe_payload.get("path") or "").strip()
            if not path:
                return {"status": "error", "error": "missing_path", "message": "Missing path"}
            content = str(safe_payload.get("content") or "")
            try:
                return {"status": "ok", "action": "fs_write", **_fs_write(path, content, cwd=cwd)}
            except ValueError as exc:
                return {"status": "error", "action": "fs_write", "error": str(exc), "message": "Invalid path"}

        if action == "fs_mkdir":
            path = str(safe_payload.get("path") or safe_payload.get("name") or "").strip()
            if not path:
                return {"status": "error", "error": "missing_path", "message": "Missing path"}
            try:
                return {"status": "ok", "action": "fs_mkdir", **_fs_mkdir(path, cwd=cwd)}
            except ValueError as exc:
                return {"status": "error", "action": "fs_mkdir", "error": str(exc), "message": "Invalid path"}

        return {
            "status": "error",
            "error": "unknown_action",
            "message": "Missing or unsupported CC action.",
        }


_COMMISSIONER = CommandCommissioner()


def get_tool_spec() -> ToolSpec:
    return ToolSpec(
        name="run_cc_command",
        description="Command commissioner for local shell and file operations.",
        input_schema={
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": [
                        "run",
                        "search_files",
                        "fs_list",
                        "fs_read",
                        "fs_write",
                        "fs_mkdir",
                    ],
                },
                "command": {
                    "description": "Shell command string or argv list.",
                    "oneOf": [{"type": "string"}, {"type": "array", "items": {"type": "string"}}],
                },
                "cwd": {"type": "string"},
                "timeout": {"type": "number"},
                "shell": {"type": "boolean"},
                "root": {"type": "string"},
                "path": {"type": "string"},
                "query": {"type": "string"},
                "content": {"type": "string"},
                "recursive": {"type": "boolean"},
                "limit": {"type": "integer"},
                "case_sensitive": {"type": "boolean"},
                "regex": {"type": "boolean"},
                "max_bytes": {"type": "integer"},
            },
        },
        output_schema={"type": "object"},
    )


def run_cc_command(payload: dict) -> dict:
    return _COMMISSIONER.commission(payload)
