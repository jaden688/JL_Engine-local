"""
memory_sync.py - Pluggable cross-device sync stub for JL Engine memory layers.

This is intentionally lightweight; implement provider-specific logic
in push/pull when you have a backend (HTTP/S3/etc.).
"""
from __future__ import annotations

from typing import Any, Dict


class MemorySyncAdapter:
    def __init__(self, config: dict | None = None):
        self.config = config or {}
        self.enabled = bool(self.config.get("enabled"))

    def push(self, layer: str, key: str, data: Dict[str, Any], version: str | None = None) -> Dict[str, Any]:
        """
        Push a memory layer blob to remote storage.
        Return a dict with status/etag/error.
        """
        if not self.enabled:
            return {"status": "disabled"}
        return {"status": "skipped", "reason": "adapter not implemented", "layer": layer, "key": key}

    def pull(self, layer: str, key: str) -> Dict[str, Any]:
        """
        Pull a memory layer blob from remote storage.
        Return {"status", "data", "version"}.
        """
        if not self.enabled:
            return {"status": "disabled", "data": None}
        return {"status": "skipped", "reason": "adapter not implemented", "data": None, "version": None}
