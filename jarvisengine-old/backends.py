from logging_setup import get_logger
logger = get_logger(__name__)

import os
import json
import requests
from abc import ABC, abstractmethod

# --- 1. Backend Registry Configuration ---
# This dictionary defines all available model backends.
# To add a new backend, add a new entry here.
BACKEND_REGISTRY = {
    "ollama-local": {
        "id": "ollama-local",
        "label": "Ollama (Local)",
        "provider": "ollama",
        "baseUrl": "http://127.0.0.1:11434",
        "modelName": "llama3",
        "apiKey": "" # Not used by Ollama, but included for structural consistency
    },
    "open_interpreter": {
        "id": "open_interpreter",
        "label": "Open Interpreter",
        "provider": "open_interpreter",
        "apiKey": ""
    }
}

# Backwards-compatible active backend (drives UI dropdown)
current_backend_id = "ollama-local" # Default brain backend defaults to local Llama
# Explicit dual-backend selection (brain = chat model, tool = interpreter)
brain_backend_id = current_backend_id
tool_backend_id = "open_interpreter"

# --- 2. Backend Abstraction ---

class ModelBackend(ABC):
    """
    Abstract base class for all model backends.
    Defines the interface that the JL Engine will use to interact with any model.
    """
    def __init__(self, config: dict):
        self.config = config

    @abstractmethod
    def generate(self, messages: list, options: dict = None, timeout: int | float | None = None) -> tuple[str, dict]:
        """
        Generates a response from the model.

        Args:
            messages (list): A list of message dictionaries (e.g., [{"role": "user", "content": "..."}]).
            options (dict, optional): A dictionary of model-specific options like temperature.
            timeout (int | float | None, optional): Request timeout in seconds if supported.

        Returns:
            tuple[str, dict]: The raw text reply and optional metadata.
        """
        pass

# --- 3. Concrete Backend Implementations ---

class OllamaBackend(ModelBackend):
    """Backend for connecting to an Ollama or compatible local server."""
    def generate(self, messages: list, options: dict = None, timeout: int | float = 30) -> tuple[str, dict]:
        print(f"[OllamaBackend] Sending request to {self.config['baseUrl']}...")
        
        api_url = f"{self.config['baseUrl']}/api/chat"
        payload = {
            "model": self.config["modelName"],
            "messages": messages,
            "stream": False,
        }
        if options:
            payload["options"] = options

        try:
            resp = requests.post(
                api_url,
                headers={"Content-Type": "application/json"},
                data=json.dumps(payload),
                timeout=timeout, # Reduced timeout to 30 seconds
            )
            resp.raise_for_status()
            data = resp.json()

            if "error" in data:
                error_msg = data["error"]
                print(f"[OllamaBackend ERROR] Server error: {error_msg}")
                return (
                    f"[ERROR: Ollama reported an issue. Is '{self.config['modelName']}' installed? Details: {error_msg}]",
                    {"error": error_msg},
                )

            # Explicitly check for an empty or missing reply
            reply_content = data.get("message", {}).get("content", "")
            if not reply_content.strip():
                print("[OllamaBackend ERROR] Received an empty reply from the model.")
                return (
                    "[ERROR: The local model returned an empty response. It might be stuck or overloaded.]",
                    {"error": "empty_reply"},
                )
            return reply_content, {"model": self.config["modelName"]}
        except requests.exceptions.RequestException as e:
            print(f"[OllamaBackend ERROR] Connection error: {e}")
            return (
                f"[ERROR: Could not connect to Ollama at {api_url}. Is it running?]",
                {"error": str(e)},
            )
        except (KeyError, IndexError, json.JSONDecodeError) as e:
            print(f"[OllamaBackend ERROR] Could not parse response: {e}")
            return (
                "[ERROR: Received an unexpected response format from the local model.]",
                {"error": str(e)},
            )

class OpenInterpreterBackend(ModelBackend):
    """Backend that delegates to the Open Interpreter runtime API."""
    def generate(self, messages: list, options: dict = None, timeout: int | float | None = None) -> tuple[str, dict]:
        try:
            from open_interpreter_backend import run as oi_run
        except Exception as exc:
            err_msg = f"[ERROR: Open Interpreter backend unavailable: {exc}]"
            print(f"[OpenInterpreterBackend ERROR] {exc}")
            return err_msg, {"error": str(exc)}

        if not messages:
            return "[ERROR: No messages provided to backend.]", {"error": "no_messages"}

        # The last message is assumed to be the new user query; prior messages form history.
        query_msg = messages[-1]
        query = query_msg.get("content", "") if isinstance(query_msg, dict) else str(query_msg)
        history = messages[:-1]

        try:
            result = oi_run(query=query, history=history)
        except Exception as exc:
            err_msg = f"[ERROR: Open Interpreter call failed: {exc}]"
            print(f"[OpenInterpreterBackend ERROR] {exc}")
            return err_msg, {"error": str(exc)}

        assistant_text = ""
        tokens_used = 0
        meta_raw = result

        if isinstance(result, dict):
            assistant_text = result.get("assistant", "") or ""
            tokens_used = result.get("tokens", 0) or 0

        return assistant_text, {"tokens": tokens_used, "raw": meta_raw}

# --- 4. Backend Selector ---

def get_backend(backend_id: str | None = None) -> ModelBackend:
    """
    Factory function that returns an instance of the selected backend.
    Falls back to the globally selected backend if none is provided.
    """
    target_id = backend_id or current_backend_id
    config = BACKEND_REGISTRY.get(target_id)
    if not config:
        raise ValueError(f"Backend '{target_id}' not found in registry.")

    provider = config.get("provider")
    if provider == "ollama":
        return OllamaBackend(config)
    if provider == "open_interpreter":
        return OpenInterpreterBackend(config)
    
    raise NotImplementedError(f"No implementation found for provider: {provider}")


# --- 5. Dual-backend helpers (brain vs tool) ---

def configure_backends(brain_id: str | None = None, tool_id: str | None = None) -> None:
    """
    Set the brain (chat) and tool (interpreter) backend ids. Falls back safely if invalid.
    """
    global brain_backend_id, tool_backend_id, current_backend_id

    if brain_id and brain_id in BACKEND_REGISTRY:
        brain_backend_id = brain_id
        current_backend_id = brain_id  # Preserve legacy behavior

    if tool_id and tool_id in BACKEND_REGISTRY:
        tool_backend_id = tool_id


def set_brain_backend_id(backend_id: str) -> None:
    """Update the active brain backend and keep legacy current_backend_id in sync."""
    global brain_backend_id, current_backend_id
    if backend_id in BACKEND_REGISTRY:
        brain_backend_id = backend_id
        current_backend_id = backend_id


def set_tool_backend_id(backend_id: str) -> None:
    """Update the tool backend id (used for explicit tool calls)."""
    global tool_backend_id
    if backend_id in BACKEND_REGISTRY:
        tool_backend_id = backend_id


def get_brain_backend() -> ModelBackend:
    """Return the primary conversational backend instance."""
    return get_backend(brain_backend_id)


def get_tool_backend() -> ModelBackend:
    """Return the interpreter/tool backend instance."""
    return get_backend(tool_backend_id)
