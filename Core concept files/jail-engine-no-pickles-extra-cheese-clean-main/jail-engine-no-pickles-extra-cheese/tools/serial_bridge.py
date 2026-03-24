"""
Lightweight serial bridge for hardware integrations.
"""
from __future__ import annotations

from typing import Callable, List, Optional

try:
    import serial  # type: ignore
except ImportError as exc:  # pragma: no cover - optional dependency
    raise ImportError(
        "pyserial is required for serial connectivity. Install with 'pip install pyserial'."
    ) from exc


class SerialBridge:
    def __init__(
        self,
        port: str,
        baudrate: int = 115200,
        timeout: float = 1.0,
        log: Optional[Callable[[str], None]] = None,
    ) -> None:
        self.port = port
        self.baudrate = baudrate
        self.timeout = timeout
        self._serial: Optional[serial.Serial] = None
        self.log = log or (lambda msg: print(msg))

    def connect(self) -> None:
        if self._serial and self._serial.is_open:
            return
        self.log(f"[Serial] Opening {self.port} @ {self.baudrate}...")
        self._serial = serial.Serial(self.port, self.baudrate, timeout=self.timeout)
        self.log("[Serial] Connected.")

    def disconnect(self) -> None:
        if self._serial:
            try:
                self._serial.close()
            except Exception:
                pass
        self._serial = None
        self.log("[Serial] Disconnected.")

    def is_connected(self) -> bool:
        return bool(self._serial and self._serial.is_open)

    def status(self) -> dict:
        return {
            "connected": self.is_connected(),
            "port": self.port,
            "baudrate": self.baudrate,
            "timeout": self.timeout,
        }

    def send_line(self, line: str, read_response: bool = True, max_lines: int = 10) -> List[str]:
        if not self.is_connected():
            self.connect()
        if not self._serial:
            raise RuntimeError("Serial not connected")
        payload = (line.rstrip("\r\n") + "\n").encode("utf-8", errors="replace")
        self._serial.write(payload)
        self._serial.flush()
        self.log(f"[Serial TX] {line}")

        responses: List[str] = []
        if not read_response:
            return responses

        for _ in range(max(0, int(max_lines))):
            raw = self._serial.readline()
            if not raw:
                break
            decoded = raw.decode("utf-8", errors="replace").rstrip()
            responses.append(decoded)
            self.log(f"[Serial RX] {decoded}")
        return responses
