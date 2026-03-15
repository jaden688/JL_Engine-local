from __future__ import annotations

import hashlib
import os
import subprocess
from typing import Dict, Any

from jl_platform.core.models import ToolSpec


def _sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _run_git(args: list[str]) -> dict:
    try:
        proc = subprocess.run(
            ["git", *args],
            capture_output=True,
            text=True,
            check=False,
        )
        return {
            "ok": proc.returncode == 0,
            "stdout": proc.stdout.strip(),
            "stderr": proc.stderr.strip(),
            "code": proc.returncode,
        }
    except Exception as exc:
        return {"ok": False, "stdout": "", "stderr": str(exc), "code": -1}


def _truthy(value: Any) -> bool:
    return str(value or "").strip().lower() in {"1", "true", "yes", "y", "on"}


def _include_git_state(payload: Dict[str, Any]) -> bool:
    if "include_git" in payload:
        return _truthy(payload.get("include_git"))
    return _truthy(os.environ.get("JL_AUDIT_INCLUDE_GIT"))


def _skipped_git_result() -> dict:
    return {
        "ok": True,
        "stdout": "",
        "stderr": "",
        "code": 0,
        "skipped": True,
    }


def run_audit_tool(payload: Dict[str, Any]) -> Dict[str, Any]:
    """
    Cross-check wrapper that returns hashes + git state for verification.
    """
    code = str(payload.get("code", "") or "")
    output = str(payload.get("output", "") or "")
    expected_output_sha = payload.get("expected_output_sha256")

    if not code.strip():
        return {
            "status": "error",
            "error": "missing_code",
            "message": "Payload requires a non-empty 'code' field.",
        }

    code_hash = _sha256_text(code)
    output_hash = _sha256_text(output) if output is not None else ""
    verify_match = None
    if expected_output_sha:
        verify_match = str(expected_output_sha).strip() == output_hash

    if _include_git_state(payload):
        git_status = _run_git(["status", "--porcelain"])
        git_diff = _run_git(["diff"])
        git_log = _run_git(["log", "-n", "5", "--oneline"])
    else:
        git_status = _skipped_git_result()
        git_diff = _skipped_git_result()
        git_log = _skipped_git_result()

    return {
        "status": "ok",
        "hashes": {
            "code_sha256": code_hash,
            "output_sha256": output_hash,
            "expected_output_sha256": expected_output_sha,
            "match": verify_match,
        },
        "git": {
            "status": git_status,
            "diff": git_diff,
            "log": git_log,
        },
    }


def get_tool_spec() -> ToolSpec:
    return ToolSpec(
        name="audit_crosscheck",
        description="Compute hashes and git status/diff/log for cross-check verification.",
        input_schema={
            "type": "object",
            "properties": {
                "code": {"type": "string"},
                "output": {"type": "string"},
                "expected_output_sha256": {"type": "string"},
                "include_git": {"type": "boolean"},
            },
            "required": ["code"],
        },
        output_schema={"type": "object"},
    )
