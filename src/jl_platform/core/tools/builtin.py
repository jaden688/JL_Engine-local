from __future__ import annotations

import os

from jl_platform.core.tools.execution_stream import (
    get_tool_spec as get_exec_spec,
    run_py_exec_stream,
)
from jl_platform.core.tools.audit import get_tool_spec as get_audit_spec, run_audit_tool
from jl_platform.core.tools.forge import (
    get_tool_specs as get_forge_specs,
    forge_create,
    forge_list,
    forge_run,
    forge_delete,
    forge_promote,
    forge_promote_last,
)
from jl_platform.core.tools.cc import get_tool_spec as get_cc_spec, run_cc_command
from jl_platform.core.tools.bridge import get_tool_spec as get_bridge_spec, run_bridge
from jl_platform.core.tools.shell import get_tool_spec as get_shell_spec, run_shell
from jl_platform.core.models import ToolSpec


def default_allow_unsafe_tools() -> bool:
    raw = str(os.getenv("JL_LOCAL_UNSAFE_TOOLS", "0")).strip().lower()
    return raw not in {"0", "false", "off", "no", ""}


def register_core_tools(registry, allow_unsafe: bool | None = None) -> None:
    if allow_unsafe is None:
        allow_unsafe = default_allow_unsafe_tools()
    registry.register(get_exec_spec(), run_py_exec_stream)
    registry.register(get_audit_spec(), run_audit_tool)
    for spec in get_forge_specs():
        if spec.name == "forge_create":
            registry.register(spec, forge_create)
        elif spec.name == "forge_list":
            registry.register(spec, forge_list)
        elif spec.name == "forge_run":
            registry.register(spec, forge_run)
        elif spec.name == "forge_delete":
            registry.register(spec, forge_delete)
        elif spec.name == "forge_promote":
            registry.register(spec, forge_promote)
        elif spec.name == "forge_promote_last":
            registry.register(spec, forge_promote_last)
    if allow_unsafe:
        registry.register(get_cc_spec(), run_cc_command)
        registry.register(get_bridge_spec(), run_bridge)
        registry.register(get_shell_spec(), run_shell)
    else:
        _register_safe_fallback_tools(registry)
    _register_promoted_tools(registry)


def _register_safe_fallback_tools(registry) -> None:
    """Register safe read-only alternatives when unsafe tools are disabled."""

    def _safe_shell_stub(payload: dict) -> dict:
        return {
            "status": "error",
            "error": "shell_disabled",
            "message": "Shell tools are disabled. Re-run with --unsafe-tools to enable.",
        }

    def _safe_bridge_stub(payload: dict) -> dict:
        return {
            "status": "error",
            "error": "bridge_disabled",
            "message": "Bridge tools are disabled. Re-run with --unsafe-tools to enable.",
        }

    spec_shell = get_shell_spec()
    spec_shell.description += " (DISABLED - use --unsafe-tools to enable)"
    registry.register(spec_shell, _safe_shell_stub)

    spec_bridge = get_bridge_spec()
    spec_bridge.description += " (DISABLED - use --unsafe-tools to enable)"
    registry.register(spec_bridge, _safe_bridge_stub)


def _register_promoted_tools(registry) -> None:
    from importlib.util import spec_from_file_location, module_from_spec
    from pathlib import Path
    from jl_platform.core.tools.forge import get_promoted_tools_dir

    promoted_dirs: list[Path] = []

    env_dir = (os.getenv("JL_PROMOTED_TOOLS_DIR") or "").strip()
    if env_dir:
        promoted_dirs.append(Path(env_dir).expanduser().resolve())

    try:
        promoted_dirs.append(get_promoted_tools_dir())
    except Exception:
        pass

    promoted_dirs.append(Path(__file__).resolve().parent / "promoted")

    seen: set[str] = set()
    for promoted_dir in promoted_dirs:
        try:
            promoted_dir = promoted_dir.expanduser().resolve()
        except Exception:
            pass
        if str(promoted_dir) in seen:
            continue
        seen.add(str(promoted_dir))
        if not promoted_dir.exists():
            continue

        def _make_handler(module_path: Path):
            def _handler(payload: dict) -> dict:
                mod_spec = spec_from_file_location(f"promoted_{module_path.stem}", str(module_path))
                if mod_spec is None or mod_spec.loader is None:
                    return {"status": "error", "error": "load_failed"}
                module = module_from_spec(mod_spec)
                mod_spec.loader.exec_module(module)  # type: ignore[attr-defined]
                if not hasattr(module, "run"):
                    return {"status": "error", "error": "missing_run"}
                return module.run(payload or {})

            return _handler

        for path in promoted_dir.glob("*.py"):
            name = path.stem
            spec = ToolSpec(
                name=name,
                description=f"Promoted tool: {name}",
                input_schema={"type": "object"},
                output_schema={"type": "object"},
            )
            registry.register(spec, _make_handler(path))
