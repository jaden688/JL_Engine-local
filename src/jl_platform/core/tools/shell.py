from __future__ import annotations

import os
import re
import shutil

from jl_platform.core.models import ToolSpec
from jl_platform.core.tools.cc import run_cc_command


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


def get_tool_spec() -> ToolSpec:
    return ToolSpec(
        name="run_shell",
        description="Execute a shell command on the host machine. Use with caution.",
        input_schema={
            "type": "object",
            "properties": {
                "command": {"type": "string", "description": "The command line to execute."},
                "cwd": {"type": "string", "description": "Optional working directory."},
            },
            "required": ["command"],
        },
        output_schema={
            "type": "object",
            "properties": {
                "stdout": {"type": "string"},
                "stderr": {"type": "string"},
                "returncode": {"type": "integer"},
            },
        },
    )


def run_shell(payload: dict) -> dict:
    # Keep compatibility with run_shell while routing execution through CC runtime.
    command = payload.get("command")
    shell = True
    if os.name == "nt":
        command = _normalize_windows_command(str(command or ""))
        shell_host = shutil.which("pwsh") or shutil.which("powershell") or "powershell"
        command = [
            shell_host,
            "-NoLogo",
            "-NoProfile",
            "-NonInteractive",
            "-ExecutionPolicy",
            "Bypass",
            "-Command",
            str(command or ""),
        ]
        shell = False
    cc_payload = {
        "action": "run",
        "command": command,
        "cwd": payload.get("cwd"),
        "timeout": payload.get("timeout", 60),
        "shell": shell,
    }
    result = run_cc_command(cc_payload)
    return {
        "stdout": result.get("stdout", ""),
        "stderr": result.get("stderr", ""),
        "returncode": result.get("returncode", -1),
        "ok": result.get("ok"),
        "duration_ms": result.get("duration_ms"),
    }
