"""
Command bridge for dispatching high-level engine commands to external systems.
The bridge is intentionally defensive: failures are logged and never raised.
"""

from __future__ import annotations

import logging
import os
from typing import Any, Dict, Optional

try:
    import requests
except ImportError:  # pragma: no cover - optional dependency
    requests = None


class JLBridge:
    """Lightweight, pluggable command bridge."""

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        self.config = config or {}
        self.enabled = bool(self.config.get("enabled", False))
        self.mode = str(self.config.get("mode", "stub")).lower()
        self.url = self.config.get("jl_url") or self.config.get("url")
        self.log_file = self.config.get("log_file")
        self.timeout = self.config.get("timeout", 10)

        self.logger = logging.getLogger("JLBridge")
        self.logger.setLevel(logging.INFO)
        self._configure_logger()

    def _configure_logger(self) -> None:
        """Configure a file logger if possible without raising exceptions."""
        if not self.logger.handlers:
            self.logger.addHandler(logging.NullHandler())

        if not self.log_file:
            return

        try:
            log_dir = os.path.dirname(self.log_file)
            if log_dir:
                os.makedirs(log_dir, exist_ok=True)

            already_added = any(
                isinstance(h, logging.FileHandler) and getattr(h, "baseFilename", None) == os.path.abspath(self.log_file)
                for h in self.logger.handlers
            )
            if not already_added:
                handler = logging.FileHandler(self.log_file, encoding="utf-8")
                handler.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s"))
                self.logger.addHandler(handler)
        except Exception as exc:  # pragma: no cover - fail open
            self.logger.warning("JLBridge could not set file logger: %s", exc)

    def send_command(self, command_text: str, meta: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """
        Sends a high-level command to the outside world.

        Returns a status dict and never raises.
        """
        meta = meta or {}

        if not self.enabled:
            self.logger.info("Command bridge disabled; ignoring command: %s", command_text)
            return {"status": "disabled"}

        mode = self.mode or "stub"

        try:
            if mode == "stub":
                self.logger.info("Stub bridge echo -> %s | meta=%s", command_text, meta)
                return {"status": "stub", "echo": command_text, "meta": meta}

            if mode in ("http", "interpreter"):
                if not self.url:
                    self.logger.warning("Command bridge missing URL; dropping command: %s", command_text)
                    return {"status": "error", "error": "missing_url"}

                if requests is None:
                    self.logger.warning("requests not installed; cannot send command.")
                    return {"status": "error", "error": "requests_not_available"}

                payload = {"command": command_text, "meta": meta}
                response = requests.post(self.url, json=payload, timeout=self.timeout)

                try:
                    data = response.json()
                except Exception:
                    data = {"status": "error", "error": "invalid_json", "raw": response.text}

                self.logger.info(
                    "Command dispatched (mode=%s, url=%s, http_status=%s)", mode, self.url, response.status_code
                )
                return {"status": "ok", "response": data, "http_status": response.status_code}

            self.logger.warning("Unknown command bridge mode '%s'; treating as error.", mode)
            return {"status": "error", "error": f"unknown_mode:{mode}"}
        except Exception as exc:  # pragma: no cover - defensive
            self.logger.error("Command dispatch failed: %s", exc)
            return {"status": "error", "error": str(exc)}
