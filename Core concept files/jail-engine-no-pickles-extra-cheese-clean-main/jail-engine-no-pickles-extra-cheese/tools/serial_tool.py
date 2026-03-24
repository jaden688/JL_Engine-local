"""
Tool entrypoint for a generic serial bridge.
"""
from __future__ import annotations

from typing import Any, Dict, Optional

from tools.serial_bridge import SerialBridge

_serial_instance: Optional[SerialBridge] = None


def _default_port() -> str:
    return "COM4"


def _get_serial(port: Optional[str] = None, baudrate: int = 115200, timeout: float = 1.0) -> SerialBridge:
    global _serial_instance
    resolved_port = port or (_serial_instance.port if _serial_instance else _default_port())
    if (
        _serial_instance is None
        or _serial_instance.port != resolved_port
        or _serial_instance.baudrate != baudrate
        or _serial_instance.timeout != timeout
    ):
        _serial_instance = SerialBridge(port=resolved_port, baudrate=baudrate, timeout=timeout)
    return _serial_instance


def serial(payload: Dict[str, Any] | None) -> Dict[str, Any]:
    """
    Serial tool entrypoint.

    Payload:
        action: "connect" | "disconnect" | "status" | "send"
        port: serial port (e.g., COM4)
        baudrate: integer baudrate
        timeout: read timeout seconds
        line: line of text to send when action="send"
        read_response: bool, default True
        max_lines: int, max response lines to capture
    """
    payload = payload if isinstance(payload, dict) else {}
    action = (payload.get("action") or "send").lower()
    port = payload.get("port")
    try:
        baudrate = int(payload.get("baudrate") or payload.get("baud") or 115200)
    except (TypeError, ValueError):
        baudrate = 115200
    try:
        timeout = float(payload.get("timeout") or 1.0)
    except (TypeError, ValueError):
        timeout = 1.0

    bridge = _get_serial(port=port, baudrate=baudrate, timeout=timeout)

    if action in ("connect", "open"):
        bridge.connect()
        return {"ok": True, "status": bridge.status()}
    if action in ("disconnect", "close"):
        bridge.disconnect()
        return {"ok": True, "status": bridge.status()}
    if action == "status":
        return {"ok": True, "status": bridge.status()}
    if action == "send":
        line = payload.get("line") or payload.get("data") or ""
        if not isinstance(line, str) or not line.strip():
            return {"ok": False, "error": "Missing 'line' for serial send."}
        read_response = bool(payload.get("read_response", True))
        try:
            max_lines = int(payload.get("max_lines", 10))
        except (TypeError, ValueError):
            max_lines = 10
        responses = bridge.send_line(line, read_response=read_response, max_lines=max_lines)
        return {"ok": True, "response": responses, "status": bridge.status()}

    return {"ok": False, "error": f"Unknown serial action: {action}"}


__all__ = ["serial"]
