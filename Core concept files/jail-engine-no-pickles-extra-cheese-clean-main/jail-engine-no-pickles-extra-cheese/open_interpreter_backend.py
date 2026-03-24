"""
Open Interpreter backend adapter for the JL Engine.

Uses the Open Interpreter Python API (non-interactive) instead of the CLI REPL.
"""

import json
from typing import Any, Dict, List, Optional

try:
    # Preferred import path for 0.4.x
    from open_interpreter import OpenInterpreter
except ImportError:
    try:
        # Package installs the module name `interpreter`
        from interpreter import OpenInterpreter
    except ImportError as exc:  # pragma: no cover - surfaced at runtime if missing
        raise ImportError(
            "open-interpreter package is required for the Open Interpreter backend."
        ) from exc


def _coerce_message(item: Dict[str, Any]) -> Optional[Dict[str, str]]:
    """Normalize a single message to include only role/content."""
    if not isinstance(item, dict):
        return None

    role = item.get("role")
    content = item.get("content")
    if not isinstance(role, str):
        return None

    return {
        "role": role,
        "content": "" if content is None else str(content),
    }


def _normalize_history(history: List[Dict[str, Any]]) -> List[Dict[str, str]]:
    """Filter and normalize history items to role/content dicts."""
    safe: List[Dict[str, str]] = []
    for item in history or []:
        msg = _coerce_message(item)
        if msg:
            safe.append(msg)
    return safe


def _parse_tool_request(obj: Any) -> Optional[Dict[str, Any]]:
    """Detect a structured tool request sent through the bridge."""
    if isinstance(obj, dict) and obj.get("mode") == "tool":
        return obj
    if isinstance(obj, str):
        try:
            data = json.loads(obj)
        except (TypeError, ValueError):
            return None
        if isinstance(data, dict) and data.get("mode") == "tool":
            return data
    return None


def _format_tool_reply(tool: str, result: Any) -> str:
    status = "ok" if isinstance(result, dict) and result.get("ok") else "error"
    detail = ""
    if isinstance(result, dict):
        detail = (
            result.get("response")
            or result.get("status")
            or result.get("error")
            or ""
        )
    else:
        detail = str(result)
    detail_str = f": {detail}" if detail else ""
    return f"[{tool}] {status}{detail_str}"


def _handle_tool_request(request: Dict[str, Any]) -> Dict[str, Any]:
    """Route tool requests without invoking the LLM layer."""
    tool = request.get("tool")
    payload = request.get("payload") if isinstance(request, dict) else None
    payload = payload if isinstance(payload, dict) else {}

    # Tier-1 tool dispatch (fs/search/exec/git/etc)
    try:
        from tools.coding.registry import dispatch_tool
    except Exception:
        dispatch_tool = None

    if tool == "serial":
        try:
            from tools import serial_tool
        except Exception as exc:
            return {
                "assistant": "[serial] error: serial tool unavailable",
                "tokens": 0,
                "raw": {"tool": tool, "error": str(exc)},
            }

        result = serial_tool.serial(payload)
        return {
            "assistant": _format_tool_reply("serial", result),
            "tokens": 0,
            "raw": {"tool": "serial", "result": result},
        }

    if dispatch_tool is not None and isinstance(tool, str):
        result = dispatch_tool(tool, payload)
        return {
            "assistant": _format_tool_reply(tool, result),
            "tokens": 0,
            "raw": {"tool": tool, "result": result},
        }

    return {
        "assistant": f"[tool error] Unknown tool: {tool}",
        "tokens": 0,
        "raw": {"tool": tool, "error": "unknown_tool"},
    }


def to_oi_messages(messages: List[Dict[str, Any]]) -> List[Dict[str, str]]:
    """
    Convert JL Engine messages to the format Open Interpreter expects:
    role/content plus a required type="message". Open Interpreter already injects its
    own system message internally, so we downgrade all incoming 'system' roles to
    'assistant' to avoid multiple system messages.
    """
    oi_messages: List[Dict[str, str]] = []
    for i, msg in enumerate(messages):
        role = msg.get("role", "user")
        content = msg.get("content", "")

        # Prevent multiple system messages; the interpreter will prepend its own.
        if role == "system":
            role = "assistant"

        oi_messages.append(
            {
                "role": role,
                "content": content,
                "type": "message",
            }
        )

    return oi_messages


def _extract_assistant(raw: Any) -> str:
    """Best-effort extraction of assistant text from various OI response shapes."""
    if isinstance(raw, dict):
        if isinstance(raw.get("message"), dict):
            msg = raw["message"]
            if msg.get("role") == "assistant":
                return str(msg.get("content", ""))
        if isinstance(raw.get("messages"), list):
            for msg in reversed(raw["messages"]):
                if isinstance(msg, dict) and msg.get("role") == "assistant":
                    return str(msg.get("content", ""))
        if "response" in raw:
            return str(raw.get("response", ""))

    if isinstance(raw, list):
        for msg in reversed(raw):
            if isinstance(msg, dict) and msg.get("role") == "assistant":
                return str(msg.get("content", ""))

    if raw is None:
        return ""
    return str(raw)


def _extract_tokens(raw: Any) -> int:
    """Pull token usage if available."""
    if isinstance(raw, dict) and isinstance(raw.get("usage"), dict):
        usage = raw["usage"]
        for key in ("total_tokens", "tokens", "completion_tokens"):
            if isinstance(usage.get(key), (int, float)):
                try:
                    return int(usage[key])
                except (TypeError, ValueError):
                    continue
    return 0


class OpenInterpreterClient:
    """Stateful wrapper that keeps a single Open Interpreter instance alive."""

    def __init__(self, model: Optional[str] = None):
        self.interpreter = OpenInterpreter(
            auto_run=True,
            in_terminal_interface=False,
            conversation_history=False,
            disable_telemetry=True,
            plain_text_display=True,
        )
        # Reinforce non-interactive defaults in case the constructor signature changes.
        self.interpreter.auto_run = True
        self.interpreter.in_terminal_interface = False
        self.interpreter.conversation_history = False
        self.interpreter.plain_text_display = True
        try:
            # Attach tool metadata for function-calling aware models.
            existing_tools = getattr(self.interpreter, "tools", []) or []
            self.interpreter.tools = existing_tools + OI_TOOLS
        except Exception:
            pass

        if model:
            self.set_model(model)

    def set_model(self, model: str) -> None:
        """Set the underlying model if the adapter exposes one."""
        try:
            self.interpreter.llm.model = model
        except Exception:
            # Best-effort; not all builds expose llm.model
            pass

    def generate(
        self,
        query: Any,
        history: List[Dict[str, Any]],
        model: Optional[str] = None,
    ) -> Dict[str, Any]:
        tool_request = _parse_tool_request(query)
        if tool_request:
            return _handle_tool_request(tool_request)

        if model:
            self.set_model(model)

        messages = _normalize_history(history)
        messages.append({"role": "user", "content": query or ""})
        oi_messages = to_oi_messages(messages)

        raw_response: Any = self.interpreter.chat(
            message=oi_messages,
            display=False,  # Crucial: avoid the terminal_interface/CLI REPL.
            stream=False,
        )

        assistant_text = _extract_assistant(raw_response)
        tokens_used = _extract_tokens(raw_response)

        return {
            "assistant": assistant_text,
            "tokens": tokens_used,
            "raw": raw_response,
        }


_CLIENT: Optional[OpenInterpreterClient] = None
OI_TOOLS = [
    {
        "name": "serial",
        "description": "Serial bridge tool: connect, status, send line, disconnect.",
        "parameters": {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["connect", "disconnect", "status", "send"],
                    "description": "Serial action to perform.",
                },
                "port": {
                    "type": "string",
                    "description": "Serial port (e.g., COM4).",
                },
                "baudrate": {
                    "type": "integer",
                    "description": "Baudrate for the connection.",
                },
                "timeout": {
                    "type": "number",
                    "description": "Read timeout in seconds.",
                },
                "line": {
                    "type": "string",
                    "description": "Line of text to send when action='send'.",
                },
                "read_response": {
                    "type": "boolean",
                    "description": "Whether to read response lines after send.",
                    "default": True,
                },
                "max_lines": {
                    "type": "integer",
                    "description": "Maximum response lines to capture.",
                },
            },
            "required": ["action"],
        },
    },

    # Tier-1 coding tools (representative set; actual dispatch supports more)
    {
        "name": "fs.read",
        "description": "Read a text file from the sandboxed workspace.",
        "parameters": {
            "type": "object",
            "properties": {"path": {"type": "string"}},
            "required": ["path"],
        },
    },
    {
        "name": "fs.write",
        "description": "Write a text file in the sandboxed workspace.",
        "parameters": {
            "type": "object",
            "properties": {"path": {"type": "string"}, "content": {"type": "string"}},
            "required": ["path", "content"],
        },
    },
    {
        "name": "fs.apply_patch",
        "description": "Apply a unified diff patch to a single file.",
        "parameters": {
            "type": "object",
            "properties": {"path": {"type": "string"}, "patch": {"type": "string"}},
            "required": ["path", "patch"],
        },
    },
    {
        "name": "search.rg",
        "description": "Search for a fixed string in the workspace (ripgrep if available).",
        "parameters": {
            "type": "object",
            "properties": {"query": {"type": "string"}, "path": {"type": "string"}, "glob": {"type": "string"}},
            "required": ["query"],
        },
    },
    {
        "name": "exec.run",
        "description": "Run an allowlisted command (python/pytest/npm/etc) in the workspace.",
        "parameters": {
            "type": "object",
            "properties": {"cmd": {"type": "array", "items": {"type": "string"}}, "cwd": {"type": "string"}, "timeout_sec": {"type": "integer"}},
            "required": ["cmd"],
        },
    },
    {
        "name": "git.diff",
        "description": "Show git diff for the repo (read-only unless enabled).",
        "parameters": {
            "type": "object",
            "properties": {"paths": {"type": "array", "items": {"type": "string"}}},
        },
    },
    {
        "name": "git.status",
        "description": "Git status --porcelain (read-only).",
        "parameters": {"type": "object", "properties": {}, "required": []},
    },
]


def _get_client(model: Optional[str] = None) -> OpenInterpreterClient:
    global _CLIENT
    if _CLIENT is None:
        _CLIENT = OpenInterpreterClient(model=model)
    elif model:
        _CLIENT.set_model(model)
    return _CLIENT


def run(query: Any, history: List[Dict[str, Any]], model: Optional[str] = None) -> Dict[str, Any]:
    """
    Execute a single Open Interpreter turn in non-interactive mode.

    Args:
        query: Latest user message content.
        history: Prior messages (role/content dicts).
        model: Optional model override for this call.

    Returns:
        dict with:
            - assistant: extracted assistant reply text
            - tokens: int token count if available
            - raw: full raw response object from Open Interpreter
    """
    client = _get_client(model=model)
    return client.generate(query=query, history=history, model=model)
