from __future__ import annotations

import os
import json
import subprocess
import time
from pathlib import Path
from datetime import datetime
from typing import Any, Dict
from urllib.parse import urlparse

import requests

from jl_platform.core.browser_bridge import BrowserBridgeManager
from jl_platform.core.models import ToolSpec
from jl_platform.core.tools.audit import run_audit_tool


_BROWSER_BRIDGE_ENV = "JL_BROWSER_BRIDGE_URL"
_BROWSER_CAPABILITY_TIER = "session_attach_accessibility"
_LOCAL_BROWSER_BRIDGE: BrowserBridgeManager | None = None
_FS_LIST_MAX_ENTRIES = 500
_BRIDGE_MODE_ALIASES = {
    "ui_info": "browser_inspect",
    "browser_info": "browser_inspect",
    "browser_snapshot": "browser_inspect",
    "browser_open": "browser_action",
    "browser_nav": "browser_action",
    "browser_navigate": "browser_action",
    "browser_go": "browser_action",
}


def _now_ms() -> float:
    return time.perf_counter() * 1000.0


def _safe_path(path: str) -> Path:
    return Path(path).expanduser().resolve()


def _run_subprocess(cmd: list[str], cwd: str | None = None, timeout: int | None = None) -> dict:
    start = _now_ms()
    proc = subprocess.run(
        cmd,
        cwd=cwd or None,
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    duration_ms = round(_now_ms() - start, 2)
    return {
        "stdout": proc.stdout,
        "stderr": proc.stderr,
        "returncode": proc.returncode,
        "duration_ms": duration_ms,
    }


def _fs_read(path: str) -> dict:
    p = _safe_path(path)
    return {"path": str(p), "content": p.read_text(encoding="utf-8", errors="ignore")}


def _fs_write(path: str, content: str) -> dict:
    p = _safe_path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content, encoding="utf-8")
    return {"path": str(p), "bytes": len(content.encode("utf-8"))}


def _fs_mkdir(path: str) -> dict:
    p = _safe_path(path)
    p.mkdir(parents=True, exist_ok=True)
    return {"path": str(p), "exists": p.exists(), "is_dir": p.is_dir()}


def _fs_list(path: str) -> dict:
    p = _safe_path(path)
    if not p.exists():
        return {"path": str(p), "entries": []}
    entries = []
    for child in p.iterdir():
        entries.append(
            {
                "name": child.name,
                "path": str(child.resolve()),
                "is_dir": child.is_dir(),
            }
        )
    return {"path": str(p), "entries": entries}


def _http_request(
    method: str, url: str, payload: dict | None = None, headers: dict | None = None
) -> dict:
    start = _now_ms()
    resp = requests.request(method, url, json=payload, headers=headers, timeout=60)
    duration_ms = round(_now_ms() - start, 2)
    return {
        "status_code": resp.status_code,
        "headers": dict(resp.headers),
        "text": resp.text,
        "duration_ms": duration_ms,
    }


def _normalize_bridge_request(payload: Dict[str, Any]) -> tuple[str, dict, str]:
    requested_mode = str(payload.get("mode", "") or "").strip().lower()
    data = payload.get("data") if isinstance(payload.get("data"), dict) else {}
    normalized_data = dict(data)
    mode = _BRIDGE_MODE_ALIASES.get(requested_mode, requested_mode)

    if requested_mode in {"fs_mkdir", "mkdir", "folder_create", "directory_create"}:
        mode = "fs_mkdir"
    elif requested_mode == "fs_create":
        path_text = str(normalized_data.get("path") or "").strip()
        content_present = normalized_data.get("content") is not None
        looks_like_file = bool(content_present or (path_text and Path(path_text).suffix))
        mode = "fs_write" if looks_like_file else "fs_mkdir"

    if requested_mode == "ui_access":
        has_browser_target = any(
            str(normalized_data.get(key) or "").strip()
            for key in ("url", "selector", "id", "name", "label", "role")
        ) or isinstance(normalized_data.get("target"), dict)
        mode = "browser_action" if has_browser_target else "ui"

    if mode == "browser_action" and not str(normalized_data.get("action") or "").strip():
        if str(normalized_data.get("url") or "").strip():
            normalized_data["action"] = "open"
        elif any(str(normalized_data.get(key) or "").strip() for key in ("value", "text")) and (
            any(str(normalized_data.get(key) or "").strip() for key in ("selector", "id", "name", "label", "role"))
            or isinstance(normalized_data.get("target"), dict)
        ):
            normalized_data["action"] = "fill"
        elif any(str(normalized_data.get(key) or "").strip() for key in ("selector", "id", "name", "label", "role")) or isinstance(
            normalized_data.get("target"), dict
        ):
            normalized_data["action"] = "click"

    return mode, normalized_data, requested_mode


def _ui_action(payload: dict) -> dict:
    try:
        import pyautogui  # type: ignore
    except Exception as exc:
        return {"error": "pyautogui_missing", "message": str(exc)}

    action = payload.get("action")
    if not str(action or "").strip():
        return {
            "error": "missing_action",
            "message": "UI control requires an action: move, click, type, hotkey, or screenshot.",
        }
    if action == "move":
        pyautogui.moveTo(payload.get("x", 0), payload.get("y", 0))
    elif action == "click":
        pyautogui.click(payload.get("x"), payload.get("y"))
    elif action == "type":
        pyautogui.typewrite(payload.get("text", ""))
    elif action == "hotkey":
        keys = payload.get("keys", [])
        if isinstance(keys, list):
            pyautogui.hotkey(*keys)
    elif action == "screenshot":
        path = payload.get("path")
        if path:
            out_path = _safe_path(str(path))
        else:
            repo_root = Path(__file__).resolve().parents[4]
            shots_dir = repo_root / "logs" / "screenshots"
            stamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")[:-3]
            out_path = shots_dir / f"shot_{stamp}.png"
        out_path.parent.mkdir(parents=True, exist_ok=True)
        img = pyautogui.screenshot()
        img.save(out_path)
        return {"status": "ok", "action": action, "path": str(out_path)}
    else:
        return {"error": "unknown_action"}
    return {"status": "ok", "action": action}


def _clip_text(value: Any, limit: int = 4000) -> str:
    text = str(value or "")
    if len(text) <= limit:
        return text
    return text[: limit - 3] + "..."


def _browser_bridge_unavailable() -> dict:
    return {
        "status": "error",
        "error": "browser_bridge_unavailable",
        "message": (
            "No external browser bridge is configured. "
            f"Set {_BROWSER_BRIDGE_ENV} to enable accessibility-first browser inspection and actions."
        ),
        "capability_tier": _BROWSER_CAPABILITY_TIER,
    }


def _normalize_url(value: str | None) -> str:
    normalized = str(value or "").strip()
    if not normalized:
        return ""
    if "://" not in normalized:
        normalized = f"http://{normalized}"
    return normalized.rstrip("/")


def _is_loopback_browser_bridge_url(value: str | None) -> bool:
    normalized = _normalize_url(value)
    if not normalized:
        return False
    parsed = urlparse(normalized)
    host = str(parsed.hostname or "").strip().lower()
    path = str(parsed.path or "").rstrip("/")
    return host in {"127.0.0.1", "localhost"} and path == "/browser-bridge"


def _get_local_browser_bridge() -> BrowserBridgeManager:
    global _LOCAL_BROWSER_BRIDGE
    if _LOCAL_BROWSER_BRIDGE is None:
        _LOCAL_BROWSER_BRIDGE = BrowserBridgeManager()
    return _LOCAL_BROWSER_BRIDGE


def _browser_bridge_local_request(request_type: str, data: dict) -> dict:
    manager = _get_local_browser_bridge()
    if request_type == "inspect":
        result = manager.inspect(data)
    elif request_type == "action":
        result = manager.action(data)
    else:
        result = {
            "status": "error",
            "error": "unknown_browser_request",
            "message": f"Unsupported browser request: {request_type}",
        }
    if isinstance(result, dict):
        result.setdefault("capability_tier", _BROWSER_CAPABILITY_TIER)
    return result


def _browser_bridge_request(request_type: str, data: dict) -> dict:
    bridge_url = _normalize_url(os.getenv(_BROWSER_BRIDGE_ENV, ""))
    if not bridge_url:
        return _browser_bridge_local_request(request_type, data)

    payload = {
        "type": f"jl-browser-{request_type}",
        "request_type": request_type,
        "capability_tier": _BROWSER_CAPABILITY_TIER,
        "data": data,
    }
    try:
        resp = requests.post(bridge_url, json=payload, timeout=30)
        resp.raise_for_status()
    except requests.RequestException as exc:
        if _is_loopback_browser_bridge_url(bridge_url):
            fallback = _browser_bridge_local_request(request_type, data)
            if isinstance(fallback, dict):
                fallback.setdefault("bridge_http_error", str(exc))
            return fallback
        return {
            "status": "error",
            "error": "browser_bridge_request_failed",
            "message": str(exc),
            "capability_tier": _BROWSER_CAPABILITY_TIER,
        }

    try:
        body = resp.json()
    except ValueError as exc:
        return {
            "status": "error",
            "error": "browser_bridge_invalid_json",
            "message": str(exc),
            "raw": _clip_text(resp.text, 2000),
            "capability_tier": _BROWSER_CAPABILITY_TIER,
        }

    if not isinstance(body, dict):
        return {
            "status": "error",
            "error": "browser_bridge_invalid_payload",
            "message": "Browser bridge response must be a JSON object.",
            "raw": _clip_text(body, 2000),
            "capability_tier": _BROWSER_CAPABILITY_TIER,
        }
    return body


def _normalize_browser_controls(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    controls: list[dict[str, Any]] = []
    for item in value[:100]:
        if not isinstance(item, dict):
            continue
        controls.append(
            {
                "role": str(item.get("role", "") or "").strip(),
                "name": _clip_text(item.get("name", ""), 200),
                "id": str(item.get("id", "") or "").strip(),
                "value": _clip_text(item.get("value", ""), 200),
                "state": _clip_text(item.get("state", ""), 200),
            }
        )
    return controls


def _browser_inspect(data: dict) -> dict:
    raw = _browser_bridge_request("inspect", data)
    if str(raw.get("status", "")).lower() == "error" or raw.get("error"):
        raw.setdefault("capability_tier", _BROWSER_CAPABILITY_TIER)
        return raw
    ax_tree = raw.get("ax_tree")
    if ax_tree is None:
        ax_tree = raw.get("accessibility_tree")
    return {
        "status": "ok",
        "capability_tier": str(raw.get("capability_tier") or _BROWSER_CAPABILITY_TIER),
        "url": str(raw.get("url") or raw.get("current_url") or data.get("url") or "").strip(),
        "title": _clip_text(raw.get("title", ""), 300),
        "focused": raw.get("focused") if isinstance(raw.get("focused"), dict) else None,
        "controls": _normalize_browser_controls(raw.get("controls")),
        "visible_text": _clip_text(raw.get("visible_text") or raw.get("text") or "", 4000),
        "dom_excerpt": _clip_text(raw.get("dom_excerpt") or raw.get("html_excerpt") or "", 4000),
        "ax_tree": ax_tree,
        "message": _clip_text(raw.get("message", ""), 400),
        "bridge_http_error": _clip_text(raw.get("bridge_http_error") or "", 600),
    }


def _browser_action(data: dict) -> dict:
    raw = _browser_bridge_request("action", data)
    if str(raw.get("status", "")).lower() == "error" or raw.get("error"):
        raw.setdefault("capability_tier", _BROWSER_CAPABILITY_TIER)
        return raw
    return {
        "status": "ok",
        "capability_tier": str(raw.get("capability_tier") or _BROWSER_CAPABILITY_TIER),
        "action": str(raw.get("action") or data.get("action") or "").strip(),
        "request_id": str(raw.get("request_id") or data.get("request_id") or "").strip(),
        "url": str(raw.get("url") or data.get("url") or "").strip(),
        "title": _clip_text(raw.get("title", ""), 300),
        "message": _clip_text(raw.get("message", ""), 400),
        "error": str(raw.get("error") or "").strip(),
        "bridge_http_error": _clip_text(raw.get("bridge_http_error") or "", 600),
    }


def run_bridge(payload: Dict[str, Any]) -> Dict[str, Any]:
    """
    Local-only bridge for file system, subprocess, http, and UI automation.
    """
    mode, data, requested_mode = _normalize_bridge_request(payload)

    if mode == "subprocess":
        cmd = data.get("cmd")
        if not isinstance(cmd, list) or not cmd:
            return {"status": "error", "error": "missing_cmd"}
        result = _run_subprocess(cmd, cwd=data.get("cwd"), timeout=data.get("timeout"))
    elif mode == "fs_read":
        result = _fs_read(data.get("path", ""))
    elif mode == "fs_write":
        result = _fs_write(data.get("path", ""), data.get("content", ""))
    elif mode == "fs_mkdir":
        result = _fs_mkdir(data.get("path", "") or data.get("name", ""))
    elif mode == "fs_list":
        result = _fs_list(data.get("path", "."))
    elif mode == "http":
        result = _http_request(
            method=str(data.get("method", "GET")).upper(),
            url=str(data.get("url", "")),
            payload=data.get("payload"),
            headers=data.get("headers"),
        )
    elif mode == "browser_inspect":
        result = _browser_inspect(data)
    elif mode == "browser_action":
        result = _browser_action(data)
    elif mode == "ui":
        result = _ui_action(data)
    else:
        return {"status": "error", "error": "unknown_mode"}

    audit = run_audit_tool(
        {"code": json.dumps(payload, indent=2), "output": json.dumps(result, indent=2)}
    )
    bridge_status = (
        str(result.get("status")).lower()
        if isinstance(result, dict) and result.get("status") is not None
        else ("error" if isinstance(result, dict) and result.get("error") else "ok")
    )
    response = {
        "status": bridge_status,
        "result": result,
        "audit": audit,
        "effective_mode": mode,
        "requested_mode": requested_mode,
    }
    if bridge_status == "error" and isinstance(result, dict):
        if result.get("error") is not None:
            response["error"] = result.get("error")
        if result.get("message") is not None:
            response["message"] = result.get("message")
    return response


def get_tool_spec() -> ToolSpec:
    return ToolSpec(
        name="bridge_local",
        description="Local-only bridge for fs/subprocess/http/ui/browser automation with audit.",
        input_schema={
            "type": "object",
            "properties": {
                "mode": {
                    "type": "string",
                    "enum": [
                        "subprocess",
                        "fs_read",
                        "fs_write",
                        "fs_mkdir",
                        "fs_list",
                        "http",
                        "browser_inspect",
                        "browser_action",
                        "ui",
                    ],
                },
                "data": {"type": "object"},
            },
            "required": ["mode"],
        },
        output_schema={"type": "object"},
    )
