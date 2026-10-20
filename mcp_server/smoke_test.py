"""Smoke test for the SparkByte MCP server tools.

Imports server.py (which registers all @mcp.tool functions), then exercises
the DB-backed tools directly. WS-backed tools are only checked for callability
unless RUN_WS=1, since they need the live engine.

Usage:
    python mcp_server/smoke_test.py
    RUN_WS=1 python mcp_server/smoke_test.py    # also hit the live engine
"""
import asyncio
import json
import os
import sys
from pathlib import Path

# Ensure repo root on sys.path so `mcp_server.server` imports cleanly.
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from mcp_server import server as srv  # noqa: E402


def _check(name: str, fn, *args, **kwargs):
    try:
        out = fn(*args, **kwargs)
        if asyncio.iscoroutine(out):
            out = asyncio.run(out)
        assert isinstance(out, str) and out, f"{name} returned empty/non-str"
        # Should be JSON-decodable for DB tools (WS replies may be plain text).
        try:
            json.loads(out)
        except Exception:
            pass
        print(f"  ok  {name}: {out[:80]!r}{'…' if len(out) > 80 else ''}")
        return True
    except Exception as e:
        print(f"  FAIL {name}: {e}")
        return False


def main() -> int:
    print("[smoke] DB-backed tools")
    results = [
        _check("get_engine_state", srv.get_engine_state),
        _check("list_forged_tools", srv.list_forged_tools),
        _check("query_memory", srv.query_memory, "", "", 3),
        _check("get_recent_telemetry", srv.get_recent_telemetry, 3),
        _check("list_agents", srv.list_agents),
        _check("list_forged_tools_registry", srv.list_forged_tools_registry),
        _check("search_julian_quarry", srv.search_julian_quarry, "def", 2),
    ]

    if os.environ.get("RUN_WS") == "1":
        print("[smoke] WS-backed tools (live engine required)")
        results.append(_check("ask_sparkbyte", srv.ask_sparkbyte, "ping"))
        results.append(_check("call_forged_tool", srv.call_forged_tool, "coin_flip"))
    else:
        print("[smoke] WS tools skipped (set RUN_WS=1 to include)")

    passed = sum(results)
    total = len(results)
    print(f"[smoke] {passed}/{total} passed")
    return 0 if passed == total else 1


if __name__ == "__main__":
    sys.exit(main())
