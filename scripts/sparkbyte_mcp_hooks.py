#!/usr/bin/env python3
"""Discover and optionally install SparkByte MCP hooks for local AI clients.

Default mode is read-only. Use --apply to write supported JSON MCP configs.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parent.parent
SERVER = ROOT / "mcp_server" / "server.py"


@dataclass
class Target:
    key: str
    label: str
    path: Path
    kind: str = "json_mcp_servers"
    create_parent_only: bool = True


def _home() -> Path:
    return Path.home()


def _appdata() -> Path:
    return Path(os.environ.get("APPDATA", _home() / "AppData" / "Roaming"))


def _localappdata() -> Path:
    return Path(os.environ.get("LOCALAPPDATA", _home() / "AppData" / "Local"))


def _expected(relative: bool = False) -> dict[str, Any]:
    arg = "mcp_server/server.py" if relative else str(SERVER)
    return {"command": "python", "args": [arg]}


def _targets() -> list[Target]:
    appdata = _appdata()
    home = _home()
    return [
        Target("repo_cursor", "Cursor project MCP", ROOT / ".cursor" / "mcp.json"),
        Target("repo_claude_code", "Claude Code project MCP", ROOT / ".mcp.json"),
        Target("claude_desktop", "Claude Desktop", appdata / "Claude" / "claude_desktop_config.json"),
        Target("cursor_user", "Cursor user MCP", appdata / "Cursor" / "User" / "mcp.json"),
        Target("vscode_user", "VS Code user MCP", appdata / "Code" / "User" / "mcp.json"),
        Target("vscode_insiders_user", "VS Code Insiders user MCP", appdata / "Code - Insiders" / "User" / "mcp.json"),
        Target("windsurf_user", "Windsurf user MCP", appdata / "Windsurf" / "User" / "mcp.json"),
        Target("zed_user", "Zed user MCP", appdata / "Zed" / "settings.json", kind="manual"),
        Target("codex_config", "Codex config", home / ".codex" / "config.toml", kind="manual"),
        Target("claude_cli_settings", "Claude Code local settings", ROOT / ".claude" / "settings.local.json", kind="manual"),
        Target("chatgpt_sse_note", "ChatGPT custom MCP", ROOT / "mcp_server" / "README.md", kind="sse_note"),
    ]


def _load_json(path: Path) -> tuple[dict[str, Any], str | None]:
    if not path.exists():
        return {}, None
    try:
        raw = path.read_text(encoding="utf-8-sig")
        if not raw.strip():
            return {}, None
        data = json.loads(raw)
        if isinstance(data, dict):
            return data, None
        return {}, "JSON root is not an object"
    except Exception as exc:
        return {}, str(exc)


def _server_entry(data: dict[str, Any]) -> Any:
    servers = data.get("mcpServers")
    if isinstance(servers, dict):
        return servers.get("sparkbyte")
    return None


def _entry_status(entry: Any, *, relative: bool = False) -> tuple[str, str]:
    expected = _expected(relative=relative)
    if entry is None:
        return "missing", "sparkbyte entry is not configured"
    if not isinstance(entry, dict):
        return "invalid", "sparkbyte entry is not an object"
    if entry == expected:
        return "current", "points at this checkout"
    args = entry.get("args")
    if isinstance(args, list) and args:
        first = str(args[0])
        if first.replace("\\", "/").endswith("mcp_server/server.py"):
            target = Path(first) if not relative else (ROOT / first)
            if target.exists():
                return "different", f"points at another existing server: {first}"
            return "stale", f"points at missing server: {first}"
    return "different", "sparkbyte entry exists but does not match this checkout"


def _audit_json_target(target: Target) -> dict[str, Any]:
    data, error = _load_json(target.path)
    if error:
        return {
            "key": target.key,
            "label": target.label,
            "path": str(target.path),
            "kind": target.kind,
            "exists": target.path.exists(),
            "status": "unreadable",
            "message": error,
            "can_apply": False,
        }
    relative = target.key == "repo_claude_code"
    status, message = _entry_status(_server_entry(data), relative=relative)
    return {
        "key": target.key,
        "label": target.label,
        "path": str(target.path),
        "kind": target.kind,
        "exists": target.path.exists(),
        "status": status,
        "message": message,
        "can_apply": True,
        "will_create": not target.path.exists(),
    }


def audit() -> dict[str, Any]:
    items: list[dict[str, Any]] = []
    for target in _targets():
        if target.kind == "json_mcp_servers":
            items.append(_audit_json_target(target))
        elif target.kind == "sse_note":
            items.append({
                "key": target.key,
                "label": target.label,
                "path": str(target.path),
                "kind": target.kind,
                "exists": target.path.exists(),
                "status": "manual",
                "message": "Run `python mcp_server/server.py --http` and connect to http://127.0.0.1:8083/sse",
                "can_apply": False,
            })
        else:
            exists = target.path.exists()
            items.append({
                "key": target.key,
                "label": target.label,
                "path": str(target.path),
                "kind": target.kind,
                "exists": exists,
                "status": "manual" if exists else "not_found",
                "message": "Manual review recommended; config shape varies by version.",
                "can_apply": False,
            })
    return {
        "ok": True,
        "root": str(ROOT),
        "server": str(SERVER),
        "server_exists": SERVER.exists(),
        "targets": items,
    }


def _write_json_mcp(target: Target) -> dict[str, Any]:
    data, error = _load_json(target.path)
    if error:
        return {"key": target.key, "status": "skipped", "message": f"unreadable JSON: {error}"}
    backup = None
    if target.path.exists():
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        backup = target.path.with_suffix(target.path.suffix + f".bak-{stamp}")
        shutil.copy2(target.path, backup)
    target.path.parent.mkdir(parents=True, exist_ok=True)
    servers = data.get("mcpServers")
    if not isinstance(servers, dict):
        servers = {}
        data["mcpServers"] = servers
    servers["sparkbyte"] = _expected(relative=(target.key == "repo_claude_code"))
    target.path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    return {
        "key": target.key,
        "status": "updated",
        "path": str(target.path),
        "backup": str(backup) if backup else None,
    }


def apply(target_keys: set[str] | None = None) -> dict[str, Any]:
    results = []
    for target in _targets():
        if target.kind != "json_mcp_servers":
            continue
        if target_keys and target.key not in target_keys:
            continue
        results.append(_write_json_mcp(target))
    return {"ok": True, "results": results, "audit": audit()}


def main() -> int:
    parser = argparse.ArgumentParser(description="Audit or install SparkByte MCP client hooks.")
    parser.add_argument("--apply", action="store_true", help="Write supported MCP JSON configs.")
    parser.add_argument("--target", action="append", help="Limit --apply to a target key. Repeatable.")
    parser.add_argument("--pretty", action="store_true", help="Pretty-print human-readable output.")
    args = parser.parse_args()

    if args.apply:
        payload = apply(set(args.target or []) or None)
    else:
        payload = audit()

    if args.pretty:
        print(f"SparkByte MCP server: {payload.get('server') or payload.get('audit', {}).get('server')}")
        targets = payload.get("targets") or payload.get("audit", {}).get("targets", [])
        for item in targets:
            print(f"- {item['key']}: {item['status']} :: {item['message']}")
    else:
        print(json.dumps(payload, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
