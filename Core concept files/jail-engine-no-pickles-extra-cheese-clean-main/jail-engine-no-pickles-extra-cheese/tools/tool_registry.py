"""
Central registry for auxiliary tools/managers used by the JL Engine.

Purpose: keep wiring to serial bridge, Open Interpreter backend, MPF runtime manager,
and MPF generator in one place so callers can import from a single module.
"""

from __future__ import annotations

from typing import Any, Dict, Optional

from business_mpf_generator import generate_business_mpf
serial_tool = None  # lazy

# Tier-1 coding tool dispatch (optional at runtime)
try:  # pragma: no cover
    from tools.coding.registry import dispatch_tool as dispatch_tool
except Exception:  # pragma: no cover
    dispatch_tool = None  # type: ignore


def get_interpreter_runner():
    """Return the Open Interpreter backend runner callable."""
    from open_interpreter_backend import run as run_interpreter_backend

    return run_interpreter_backend


def get_mpf_runtime_manager(profiles: Optional[Dict[str, Any]] = None):
    """
    Factory to keep MPF runtime creation consistent.
    Lazy import avoids cycles with backends importing this registry.
    """
    from modules.mpf_runtime_manager import MPFRuntimeManager

    return MPFRuntimeManager(profiles)


def get_serial_bridge(port: str | None = None, baudrate: int = 115200, timeout: float = 1.0):
    """Create a serial bridge instance with safe defaults."""
    from tools.serial_bridge import SerialBridge

    return SerialBridge(port=port or "COM4", baudrate=baudrate, timeout=timeout)


def serial(payload: Dict[str, Any]):
    """Wrapper around the serial tool entrypoint."""
    global serial_tool
    if serial_tool is None:
        from tools import serial_tool as _serial_tool

        serial_tool = _serial_tool
    return serial_tool.serial(payload)


__all__ = [
    "get_interpreter_runner",
    "get_mpf_runtime_manager",
    "generate_business_mpf",
    "get_serial_bridge",
    "serial",
    "dispatch_tool",
]
