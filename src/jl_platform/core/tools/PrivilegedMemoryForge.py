from __future__ import annotations

import os
import time
from typing import Any, Dict, Callable

from jl_platform.core.tools.forge import forge_create, forge_promote


def _env_float(name: str, default: float, minimum: float = 0.0) -> float:
    raw = str(os.getenv(name) or "").strip()
    try:
        value = float(raw) if raw else default
    except ValueError:
        value = default
    return max(minimum, value)


def _env_int(name: str, default: int, minimum: int = 1) -> int:
    raw = str(os.getenv(name) or "").strip()
    try:
        value = int(raw) if raw else default
    except ValueError:
        value = default
    return max(minimum, value)


class PrivilegedMemoryForge:
    """
    An in-memory, ephemeral tool forge for trusted, high-performance agents.

    This forge creates and runs tools directly in memory using exec(), offering
    maximum speed and runtime flexibility. It is designed for "special agents"
    that are trusted to generate safe and functional code.

    Tools created with this forge are ephemeral and vanish when the session ends.
    """

    def __init__(self) -> None:
        """Initializes the in-memory tool cache."""
        self._tools: Dict[str, Callable[[Dict[str, Any]], Any]] = {}
        self._tool_descriptions: Dict[str, str] = {}
        self._tool_code: Dict[str, str] = {}
        self._tool_stats: Dict[str, Dict[str, Any]] = {}
        self._recently_deleted: Dict[str, Dict[str, Any]] = {}
        # Fat-agent default lifecycle: RAM tools are single-use unless promoted.
        self._delete_after_use: bool = True
        # Unused RAM tools should not linger forever on low-memory machines.
        self._unused_ttl_seconds: float = _env_float("JL_RAM_TOOL_UNUSED_TTL_SECONDS", 300.0, minimum=0.0)
        self._max_active_tools: int = _env_int("JL_RAM_TOOL_MAX_ACTIVE", 8, minimum=1)
        self._max_recently_deleted: int = _env_int("JL_RAM_TOOL_MAX_RECENTLY_DELETED", 24, minimum=1)

    def _stats_snapshot(self, name: str) -> Dict[str, Any]:
        stats = dict(self._tool_stats.get(name) or {})
        created_at = float(stats.get("created_at") or time.time())
        use_count = int(stats.get("use_count", 0) or 0)
        promoted = bool(stats.get("promoted", False))
        expires_at = None
        if not promoted and use_count <= 0 and self._unused_ttl_seconds > 0:
            expires_at = created_at + self._unused_ttl_seconds
        stats["idle_ttl_seconds"] = self._unused_ttl_seconds
        stats["expires_at"] = expires_at
        return stats

    def _drop_tool(self, name: str) -> None:
        self._tools.pop(name, None)
        self._tool_descriptions.pop(name, None)
        self._tool_code.pop(name, None)
        self._tool_stats.pop(name, None)

    def _trim_recently_deleted(self) -> None:
        if len(self._recently_deleted) <= self._max_recently_deleted:
            return
        ordered = sorted(
            self._recently_deleted.items(),
            key=lambda item: float((item[1] or {}).get("deleted_at") or 0.0),
            reverse=True,
        )
        self._recently_deleted = dict(ordered[: self._max_recently_deleted])

    def _record_recently_deleted(
        self,
        name: str,
        *,
        reason: str,
        stats_snapshot: Dict[str, Any] | None = None,
        error: str | None = None,
    ) -> None:
        self._recently_deleted[name] = {
            "code": self._tool_code.get(name, ""),
            "description": self._tool_descriptions.get(name, ""),
            "stats": dict(stats_snapshot or self._stats_snapshot(name)),
            "deleted_at": time.time(),
            "reason": reason,
        }
        if error:
            self._recently_deleted[name]["error"] = str(error)
        self._trim_recently_deleted()

    def _collect_expired_tools(self) -> list[str]:
        if self._unused_ttl_seconds <= 0:
            return []
        now = time.time()
        expired: list[str] = []
        for name in list(self._tools.keys()):
            stats = dict(self._tool_stats.get(name) or {})
            if bool(stats.get("promoted", False)):
                continue
            if int(stats.get("use_count", 0) or 0) > 0:
                continue
            created_at = float(stats.get("created_at") or now)
            if (now - created_at) < self._unused_ttl_seconds:
                continue
            self._record_recently_deleted(
                name,
                reason="expired_unused",
                stats_snapshot=self._stats_snapshot(name),
            )
            self._drop_tool(name)
            expired.append(name)
        return expired

    def _enforce_active_limit(self, *, keep: str | None = None) -> list[str]:
        if len(self._tools) <= self._max_active_tools:
            return []
        keep_name = str(keep or "").strip()
        ordered = sorted(
            self._tools.keys(),
            key=lambda name: (
                float((self._tool_stats.get(name) or {}).get("last_used_at") or (self._tool_stats.get(name) or {}).get("created_at") or 0.0),
                float((self._tool_stats.get(name) or {}).get("created_at") or 0.0),
                name,
            ),
        )
        evicted: list[str] = []
        for name in ordered:
            if len(self._tools) <= self._max_active_tools:
                break
            if name == keep_name:
                continue
            stats = dict(self._tool_stats.get(name) or {})
            if bool(stats.get("promoted", False)):
                continue
            self._record_recently_deleted(
                name,
                reason="capacity_eviction",
                stats_snapshot=self._stats_snapshot(name),
            )
            self._drop_tool(name)
            evicted.append(name)
        return evicted

    def create_tool(self, name: str, code: str, description: str = "") -> Dict[str, Any]:
        """
        Creates or overwrites a tool directly in memory.

        Args:
            name: The unique name of the tool.
            code: A string of Python code defining a `run(payload)` function.
            description: An optional description of the tool's purpose.

        Returns:
            A dictionary indicating the status of the operation.
        """
        if not name or not name.strip():
            return {"status": "error", "error": "missing_name"}
        if not code or not code.strip():
            return {"status": "error", "error": "missing_code"}
        expired = self._collect_expired_tools()

        try:
            # Prepare a dedicated context for exec to run in.
            # Block dangerous builtins to limit attack surface.
            import builtins as _builtins

            _BLOCKED_BUILTINS = {"__import__", "compile", "breakpoint", "open", "input"}
            safe_builtins = {
                k: v for k, v in vars(_builtins).items() if k not in _BLOCKED_BUILTINS
            }
            exec_context: Dict[str, Any] = {"__builtins__": safe_builtins}
            exec(code, exec_context)  # noqa: S102 — intentional; guarded by safe_builtins + session scope

            # The code MUST define a 'run' function.
            if "run" not in exec_context or not isinstance(exec_context["run"], Callable):
                return {"status": "error", "error": "missing_run_function"}

            tool_function = exec_context["run"]
            self._tools[name] = tool_function
            self._tool_descriptions[name] = description
            self._tool_code[name] = code
            self._tool_stats[name] = {
                "created_at": time.time(),
                "last_used_at": None,
                "use_count": 0,
                "error_count": 0,
                "promoted": False,
            }
            evicted = self._enforce_active_limit(keep=name)

            return {
                "status": "ok",
                "name": name,
                "action": "created_or_updated",
                "stats": self._stats_snapshot(name),
                "lifecycle": {
                    "expired_unused": expired,
                    "evicted_for_capacity": evicted,
                },
            }
        except Exception as exc:
            return {"status": "error", "error": "exec_failed", "message": str(exc)}

    def list_tools(self) -> Dict[str, Any]:
        """Lists all tools currently stored in memory."""
        expired = self._collect_expired_tools()
        tool_list = [
            {
                "name": name,
                "description": self._tool_descriptions.get(name, ""),
                "stats": self._stats_snapshot(name),
            }
            for name in self._tools
        ]
        return {
            "status": "ok",
            "tools": tool_list,
            "recently_deleted": sorted(self._recently_deleted.keys()),
            "expired_unused": expired,
        }

    def run_tool(self, name: str, payload: Dict[str, Any] | None = None) -> Dict[str, Any]:
        """
        Runs a tool from memory.

        Args:
            name: The name of the tool to run.
            payload: The JSON-like dictionary to pass to the tool's run() function.

        Returns:
            A dictionary containing the result or an error.
        """
        expired = self._collect_expired_tools()
        if name not in self._tools:
            return {"status": "error", "error": "not_found"}

        try:
            tool_function = self._tools[name]
            result = tool_function(payload or {})
            stats = self._tool_stats.setdefault(
                name,
                {"created_at": time.time(), "last_used_at": None, "use_count": 0, "error_count": 0, "promoted": False},
            )
            stats["last_used_at"] = time.time()
            stats["use_count"] = int(stats.get("use_count", 0)) + 1
            stats_snapshot = self._stats_snapshot(name)

            lifecycle: Dict[str, Any] = {}
            if self._delete_after_use and not bool(stats.get("promoted", False)):
                self._record_recently_deleted(
                    name,
                    reason="deleted_after_use",
                    stats_snapshot=stats_snapshot,
                )
                self._drop_tool(name)
                lifecycle["deleted_after_use"] = True
                lifecycle["deleted_name"] = name
            if expired:
                lifecycle["expired_unused"] = expired

            return {"status": "ok", "result": result, "lifecycle": lifecycle, "stats": stats_snapshot}
        except Exception as exc:
            stats = self._tool_stats.setdefault(
                name,
                {"created_at": time.time(), "last_used_at": None, "use_count": 0, "error_count": 0, "promoted": False},
            )
            stats["error_count"] = int(stats.get("error_count", 0)) + 1
            stats["last_used_at"] = time.time()
            stats_snapshot = self._stats_snapshot(name)
            lifecycle: Dict[str, Any] = {}
            if self._delete_after_use and not bool(stats.get("promoted", False)):
                self._record_recently_deleted(
                    name,
                    reason="deleted_after_error",
                    stats_snapshot=stats_snapshot,
                    error=str(exc),
                )
                self._drop_tool(name)
                lifecycle["deleted_after_use"] = True
                lifecycle["deleted_name"] = name
            if expired:
                lifecycle["expired_unused"] = expired
            return {
                "status": "error",
                "error": "execution_failed",
                "message": str(exc),
                "lifecycle": lifecycle,
                "stats": stats_snapshot,
            }

    def delete_tool(self, name: str) -> Dict[str, Any]:
        """Deletes a tool from memory."""
        self._collect_expired_tools()
        if name not in self._tools:
            return {"status": "error", "error": "not_found"}
        self._drop_tool(name)

        return {"status": "ok", "deleted": name}

    def promote_tool(self, name: str, description: str | None = None) -> Dict[str, Any]:
        """Persist an in-memory tool into the disk forge and promote it for auto-registration."""
        self._collect_expired_tools()
        source = "active_memory"
        if name in self._tools:
            code = self._tool_code.get(name)
            base_description = self._tool_descriptions.get(name, "")
        else:
            recent = self._recently_deleted.get(name)
            if not recent:
                return {"status": "error", "error": "not_found"}
            source = "recently_deleted"
            code = str(recent.get("code") or "")
            base_description = str(recent.get("description") or "")
        if not code:
            return {"status": "error", "error": "missing_source_code"}
        create_res = forge_create({"name": name, "code": code, "description": description or base_description})
        if create_res.get("status") != "ok":
            return create_res
        promote_res = forge_promote({"name": name})
        if promote_res.get("status") == "ok":
            if name in self._tool_stats:
                stats = self._tool_stats.get(name) or {}
                stats["promoted"] = True
                self._tool_stats[name] = stats
            if name in self._recently_deleted:
                recent = self._recently_deleted.get(name) or {}
                recent["promoted"] = True
                self._recently_deleted[name] = recent
            promote_res["source"] = source
        return promote_res

    def clone(self) -> "PrivilegedMemoryForge":
        """Create a full in-memory clone of this forge and its tools."""
        cloned = PrivilegedMemoryForge()
        cloned._tools = dict(self._tools)
        cloned._tool_descriptions = dict(self._tool_descriptions)
        cloned._tool_code = dict(self._tool_code)
        cloned._tool_stats = {name: dict(meta) for name, meta in self._tool_stats.items()}
        cloned._recently_deleted = {name: dict(meta) for name, meta in self._recently_deleted.items()}
        cloned._delete_after_use = self._delete_after_use
        cloned._unused_ttl_seconds = self._unused_ttl_seconds
        cloned._max_active_tools = self._max_active_tools
        cloned._max_recently_deleted = self._max_recently_deleted
        return cloned
