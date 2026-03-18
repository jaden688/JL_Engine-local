from __future__ import annotations

import os
import shlex
import subprocess
import time
from pathlib import Path
from typing import Any

from jl_platform.core.models import ToolSpec


def get_tool_spec() -> ToolSpec:
    return ToolSpec(
        name="run_cc_command",
        description="Execute a local command and return structured output.",
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


def _normalize_command(command: Any, shell: bool) -> str | list[str]:
    if isinstance(command, list):
        if shell:
            return " ".join(shlex.quote(str(part)) for part in command)
        return [str(part) for part in command]
    return str(command)


def run_cc_command(payload: dict) -> dict:
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

    start = time.perf_counter()
    try:
        completed = subprocess.run(
            normalized,
            cwd=cwd or None,
            capture_output=True,
            text=True,
            timeout=timeout,
            shell=shell,
        )
        duration_ms = round((time.perf_counter() - start) * 1000.0, 2)
        return {
            "ok": completed.returncode == 0,
            "returncode": completed.returncode,
            "stdout": completed.stdout or "",
            "stderr": completed.stderr or "",
            "duration_ms": duration_ms,
            "cwd": os.path.abspath(cwd or os.getcwd()),
            "command": normalized,
        }
    except subprocess.TimeoutExpired as exc:
        duration_ms = round((time.perf_counter() - start) * 1000.0, 2)
        return {
            "ok": False,
            "returncode": None,
            "stdout": exc.stdout or "",
            "stderr": exc.stderr or f"Timed out after {timeout}s",
            "duration_ms": duration_ms,
            "cwd": os.path.abspath(cwd or os.getcwd()),
            "command": normalized,
            "error": "timeout",
        }
    except Exception as exc:
        duration_ms = round((time.perf_counter() - start) * 1000.0, 2)
        return {
            "ok": False,
            "returncode": None,
            "stdout": "",
            "stderr": str(exc),
            "duration_ms": duration_ms,
            "cwd": os.path.abspath(cwd or os.getcwd()),
            "command": normalized,
            "error": "exception",
        }
