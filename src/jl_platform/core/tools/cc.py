from __future__ import annotations

import importlib
import shlex
from pathlib import Path
from typing import Any

from jl_platform.core.models import ToolSpec


def get_tool_spec() -> ToolSpec:
    return ToolSpec(
        name="run_cc_command",
        description="Execute a local command through modules/cc.py (legacy CC.py shim) and return structured output.",
        input_schema={
            "type": "object",
            "properties": {
                "command": {
                    "description": "Shell command string or argv list.",
                    "oneOf": [{"type": "string"}, {"type": "array", "items": {"type": "string"}}],
                },
                "cwd": {"type": "string"},
                "timeout": {"type": "number"},
                "shell": {"type": "boolean"},
            },
            "required": ["command"],
        },
        output_schema={
            "type": "object",
            "properties": {
                "ok": {"type": "boolean"},
                "returncode": {"type": ["integer", "null"]},
                "stdout": {"type": "string"},
                "stderr": {"type": "string"},
                "duration_ms": {"type": "number"},
                "cwd": {"type": "string"},
                "command": {},
            },
        },
    )


def _load_cc_module():
    for module_name in ("modules.cc", "CC"):
        try:
            return importlib.import_module(module_name)
        except Exception:
            continue
    return None


def _normalize_command(command: Any, shell: bool) -> str | list[str]:
    if isinstance(command, list):
        if shell:
            return " ".join(shlex.quote(str(part)) for part in command)
        return [str(part) for part in command]
    return str(command)


def run_cc_command(payload: dict) -> dict:
    cc_module = _load_cc_module()
    if cc_module is None or not hasattr(cc_module, "run_command"):
        return {
            "ok": False,
            "returncode": None,
            "stdout": "",
            "stderr": "CC module is not importable. Expected modules.cc or legacy CC with run_command().",
            "error": "cc_unavailable",
        }

    command = payload.get("command")
    if command is None or command == "":
        return {
            "ok": False,
            "returncode": None,
            "stdout": "",
            "stderr": "Missing command",
            "error": "missing_command",
        }

    cwd = payload.get("cwd")
    timeout_raw = payload.get("timeout")
    shell = bool(payload.get("shell", True))
    timeout = None
    if timeout_raw is not None:
        try:
            timeout = float(timeout_raw)
        except (TypeError, ValueError):
            timeout = None
    if isinstance(cwd, str) and cwd.strip():
        cwd = str(Path(cwd).expanduser())
    else:
        cwd = None

    normalized = _normalize_command(command, shell=shell)
    try:
        result = cc_module.run_command(normalized, cwd=cwd, timeout=timeout, shell=shell)
    except Exception as exc:
        return {
            "ok": False,
            "returncode": None,
            "stdout": "",
            "stderr": str(exc),
            "error": "cc_runtime_error",
        }
    if isinstance(result, dict):
        return result
    return {
        "ok": False,
        "returncode": None,
        "stdout": "",
        "stderr": "CC returned non-dict response",
        "error": "cc_invalid_response",
    }
