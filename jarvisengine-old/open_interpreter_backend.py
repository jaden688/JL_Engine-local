"""
Open Interpreter backend adapter for the JL Engine.

Uses the Open Interpreter Python API (non-interactive) instead of the CLI REPL.
"""

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
        query: str,
        history: List[Dict[str, Any]],
        model: Optional[str] = None,
    ) -> Dict[str, Any]:
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


def _get_client(model: Optional[str] = None) -> OpenInterpreterClient:
    global _CLIENT
    if _CLIENT is None:
        _CLIENT = OpenInterpreterClient(model=model)
    elif model:
        _CLIENT.set_model(model)
    return _CLIENT


def run(query: str, history: List[Dict[str, Any]], model: Optional[str] = None) -> Dict[str, Any]:
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
