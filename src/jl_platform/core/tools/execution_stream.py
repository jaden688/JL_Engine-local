from __future__ import annotations

import contextlib
import hashlib
import io
import time
import traceback
import tracemalloc
import cProfile
import pstats
from typing import Dict, Any

from jl_platform.core.models import ToolSpec


def _sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _validate_payload(payload: Dict[str, Any]) -> tuple[str, Dict[str, Any] | None]:
    code = str(payload.get("code", "") or "")
    if not code.strip():
        return "", {
            "status": "error",
            "error": "missing_code",
            "message": "Payload requires a non-empty 'code' field.",
        }
    return code, None


def _get_safe_builtins() -> dict[str, Any]:
    _BLOCKED_BUILTINS = {"__import__", "compile", "breakpoint", "open", "input"}
    import builtins as _builtins
    return {
        k: v for k, v in vars(_builtins).items() if k not in _BLOCKED_BUILTINS
    }


def run_py_exec_stream(payload: Dict[str, Any]) -> Dict[str, Any]:
    """
    Execute Python code in-process with telemetry:
    - wall time
    - peak memory (tracemalloc)
    - call graph summary (cProfile)
    - stdout/stderr capture
    """
    code, error_response = _validate_payload(payload)
    if error_response:
        return error_response

    safe_builtins = _get_safe_builtins()

    stdout_buf = io.StringIO()
    stderr_buf = io.StringIO()

    # Detect nested calls — skip profiling to avoid pstats conflict
    _nested = tracemalloc.is_tracing()
    profile = cProfile.Profile() if not _nested else None

    start = time.perf_counter()
    if not _nested:
        tracemalloc.start()
    error = None
    tb = None

    # Use a single execution namespace so imports are visible to functions/classes
    # defined in the executed code (avoids NameError for imported symbols).
    exec_namespace: Dict[str, Any] = {"__builtins__": safe_builtins}
    try:
        with contextlib.redirect_stdout(stdout_buf), contextlib.redirect_stderr(stderr_buf):
            if profile:
                profile.enable()
            exec(code, exec_namespace, exec_namespace)  # noqa: S102 — intentional; guarded by safe_builtins + env toggle
    except Exception as exc:
        error = str(exc)
        tb = traceback.format_exc()
    finally:
        if profile:
            profile.disable()
        if not _nested:
            current, peak = tracemalloc.get_traced_memory()
            tracemalloc.stop()
        else:
            current, peak = 0, 0

    duration_ms = (time.perf_counter() - start) * 1000.0
    stdout_val = stdout_buf.getvalue()
    stderr_val = stderr_buf.getvalue()

    call_graph = ""
    if profile:
        try:
            stats_stream = io.StringIO()
            stats = pstats.Stats(profile, stream=stats_stream)
            stats.strip_dirs().sort_stats("cumtime").print_stats(15)
            call_graph = stats_stream.getvalue()
        except Exception:
            call_graph = ""

    output_text = (stdout_val + ("\n" if stderr_val else "") + stderr_val).strip()
    # Only expose the final error line, not the full traceback (avoids leaking code paths).
    sanitized_tb = tb.strip().rsplit("\n", 1)[-1] if tb else None
    response = {
        "status": "ok" if error is None else "error",
        "stdout": stdout_val,
        "stderr": stderr_val,
        "output": output_text,
        "error": error,
        "traceback": sanitized_tb,
        "metrics": {
            "duration_ms": round(duration_ms, 2),
            "memory_current_kb": round(current / 1024.0, 2),
            "memory_peak_kb": round(peak / 1024.0, 2),
        },
        "hashes": {
            "code_sha256": _sha256_text(code),
            "output_sha256": _sha256_text(output_text),
        },
        "profile": call_graph,
    }
    return response


def get_tool_spec() -> ToolSpec:
    return ToolSpec(
        name="py_exec_stream",
        description="Execute Python code with time/memory/call telemetry and capture stdout/stderr.",
        input_schema={
            "type": "object",
            "properties": {"code": {"type": "string"}},
            "required": ["code"],
        },
        output_schema={"type": "object"},
    )
