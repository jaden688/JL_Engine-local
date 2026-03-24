from .logging_setup import get_logger
logger = get_logger(__name__)

import copy
import os
import json
import requests
from abc import ABC, abstractmethod
from pathlib import Path
from .config_loader import load_json_safely
# from tools.tool_registry import get_interpreter_runner

def get_interpreter_runner():
    raise NotImplementedError("Tool execution is not included in the standard runtime.")

# --- 1. Backend Registry Configuration ---
# This dictionary defines all available model backends.
# To add a new backend, add a new entry here.
DEFAULT_GEMINI_ENDPOINT = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
DEFAULT_GEMINI_MODEL = "gemini-1.5-pro"
DEFAULT_GEMINI_TIMEOUT = 60
GEMINI_CONFIG_PATH = Path(__file__).resolve().parent / "tts_config.json"

OLLAMA_ALLOWED_BASES = {
    "http://127.0.0.1:11434",
    "http://localhost:11434",
}
OLLAMA_CONNECT_TIMEOUT = 3
OLLAMA_READ_TIMEOUT = 120


def _normalize_ollama_base_url(raw: str) -> str:
    if not raw:
        return "http://127.0.0.1:11434"
    value = raw.strip().rstrip("/")
    if value in ("localhost", "http://localhost"):
        return "http://localhost:11434"
    if value in ("127.0.0.1", "http://127.0.0.1"):
        return "http://127.0.0.1:11434"
    if value == "localhost:11434":
        return "http://localhost:11434"
    if value == "127.0.0.1:11434":
        return "http://127.0.0.1:11434"
    if value.startswith("http://localhost") and ":" not in value.split("//", 1)[1]:
        return "http://localhost:11434"
    if value.startswith("http://127.0.0.1") and ":" not in value.split("//", 1)[1]:
        return "http://127.0.0.1:11434"
    return value


def _enforce_ollama_base_url(raw: str) -> str:
    allow_remote = os.getenv("JL_ALLOW_REMOTE_OLLAMA", "").strip() == "1"
    normalized = _normalize_ollama_base_url(raw)
    if allow_remote:
        return normalized
    if normalized.rstrip("/") not in OLLAMA_ALLOWED_BASES:
        return "http://127.0.0.1:11434"
    return normalized


def _ollama_health_check(base_url: str) -> tuple[bool, str]:
    url = base_url.rstrip("/") + "/api/tags"
    try:
        resp = requests.get(url, timeout=(OLLAMA_CONNECT_TIMEOUT, 3))
        resp.raise_for_status()
        return True, ""
    except requests.exceptions.ConnectionError:
        return False, "Ollama not running on localhost:11434"
    except requests.exceptions.ConnectTimeout:
        return False, "Ollama not running on localhost:11434"
    except Exception as exc:
        return False, f"Ollama health check failed: {exc}"


def _load_gemini_config() -> dict:
    data = load_json_safely(GEMINI_CONFIG_PATH)
    return data if isinstance(data, dict) else {}


BACKEND_REGISTRY = {
    "noop-stub": {
        "id": "noop-stub",
        "label": "Stub (No backend)",
        "provider": "noop",
    },
    "google-gemini": {
        "id": "google-gemini",
        "label": "Google Gemini",
        "provider": "google_gemini",
        "google_api_key": None,  # Will be loaded from tts_config.json
        "google_gemini_endpoint": DEFAULT_GEMINI_ENDPOINT,
        "gemini_endpoint": DEFAULT_GEMINI_ENDPOINT,
        "gemini_model": DEFAULT_GEMINI_MODEL,
        "google_gemini_timeout": DEFAULT_GEMINI_TIMEOUT,
    },
    "ollama-local": {
        "id": "ollama-local",
        "label": "Ollama (Local)",
        "provider": "ollama",
        "baseUrl": "http://127.0.0.1:11434",
        # Default model for the local Ollama backend; ensure it is pulled locally.
        "modelName": "llama3",
        "model_name": "llama3",
        "apiKey": "" # Not used by Ollama, but included for structural consistency
    },
    "ollama-dolphin": {
        "id": "ollama-dolphin",
        "label": "Ollama (Dolphin3)",
        "provider": "ollama",
        "baseUrl": "http://127.0.0.1:11434",
        "modelName": "dolphin3",
        "model_name": "dolphin3",
        "apiKey": ""
    },
    "open_interpreter": {
        "id": "open_interpreter",
        "label": "Open Interpreter",
        "provider": "open_interpreter",
        "apiKey": ""
    },
    "custom_http": {
        "id": "custom_http",
        "label": "Custom HTTP Backend",
        "name": "Custom HTTP",
        "provider": "custom_http",
        "base_url": "",
        "model": "",
        "api_key": "",
        "headers": {"Content-Type": "application/json"},
        "request_template": {}
    }
}


def _merge_backend_config(target_id: str, incoming: dict, default_provider: str | None = None) -> None:
    """
    Merge a backend config from the master file into the registry.
    """
    if not target_id or not isinstance(incoming, dict):
        return
    existing = BACKEND_REGISTRY.get(target_id, {"id": target_id})
    merged = {**existing, **incoming}
    if default_provider and not merged.get("provider"):
        merged["provider"] = default_provider
    if incoming.get("name") and not merged.get("label"):
        merged["label"] = incoming["name"]
    BACKEND_REGISTRY[target_id] = merged


def apply_backend_overrides(backends_cfg: dict) -> None:
    """
    Apply dynamic backend entries (e.g., custom HTTP) from the master config.
    """
    if not isinstance(backends_cfg, dict):
        return

    brain_cfg = backends_cfg.get("brain_config")
    if isinstance(brain_cfg, dict):
        provider = brain_cfg.get("provider")
        if not provider and brain_cfg.get("request_template"):
            provider = "custom_http"
        target_id = brain_cfg.get("id") or brain_cfg.get("backend_id") or brain_cfg.get("backend") or "custom_http"
        payload = copy.deepcopy(brain_cfg)
        payload["id"] = target_id
        if provider:
            payload["provider"] = provider
        if provider == "custom_http" and payload.get("name") and not payload.get("label"):
            payload["label"] = payload["name"]
        _merge_backend_config(target_id, payload, default_provider=provider or "custom_http")

# Backwards-compatible active backend (drives UI dropdown)
current_backend_id = "noop-stub"
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
        base_url = _enforce_ollama_base_url(self.config.get("baseUrl", ""))
        self.config["baseUrl"] = base_url
        print(f"[OllamaBackend] Sending request to {base_url}...")

        ok, msg = _ollama_health_check(base_url)
        if not ok:
            return f"[ERROR: {msg}]", {"error": "ollama_unavailable"}

        api_url = f"{base_url}/api/chat"
        payload = {
            "model": self.config["modelName"],
            "messages": messages,
            "stream": True,
        }
        if options:
            payload["options"] = options

        try:
            resp = requests.post(
                api_url,
                headers={"Content-Type": "application/json"},
                data=json.dumps(payload),
                timeout=(OLLAMA_CONNECT_TIMEOUT, OLLAMA_READ_TIMEOUT),
                stream=True,
            )
            resp.raise_for_status()
            chunks = []
            for line in resp.iter_lines():
                if not line:
                    continue
                try:
                    data = json.loads(line.decode("utf-8"))
                except Exception:
                    continue
                if "error" in data:
                    error_msg = data["error"]
                    print(f"[OllamaBackend ERROR] Server error: {error_msg}")
                    return (
                        f"[ERROR: Ollama reported an issue. Is '{self.config['modelName']}' installed? Details: {error_msg}]",
                        {"error": error_msg},
                    )
                content = data.get("message", {}).get("content")
                if content:
                    chunks.append(content)
            reply_content = "".join(chunks).strip()
            if not reply_content:
                print("[OllamaBackend ERROR] Received an empty reply from the model.")
                return (
                    "[ERROR: The local model returned an empty response. It might be stuck or overloaded.]",
                    {"error": "empty_reply"},
                )
            return reply_content, {"model": self.config["modelName"]}
        except requests.exceptions.RequestException as e:
            if isinstance(e, requests.exceptions.ReadTimeout):
                return "[ERROR: Model is slow / timed out.]", {"error": "read_timeout"}
            if isinstance(e, (requests.exceptions.ConnectionError, requests.exceptions.ConnectTimeout)):
                return "[ERROR: Ollama not running on localhost:11434]", {"error": "connect_failed"}
            print(f"[OllamaBackend ERROR] Connection error: {e}")
            return (f"[ERROR: Could not connect to Ollama at {api_url}.]", {"error": str(e)})
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
            oi_run = get_interpreter_runner()
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


class GoogleGeminiBackend(ModelBackend):
    """Google Gemini backend using a simple API key."""

    def __init__(self, config: dict):
        super().__init__(config)
        self.endpoint_template = (
            config.get("gemini_endpoint")
            or config.get("google_gemini_endpoint")
            or DEFAULT_GEMINI_ENDPOINT
        )
        self.api_key = config.get("google_api_key")
        self.timeout = config.get("google_gemini_timeout", DEFAULT_GEMINI_TIMEOUT)
        self.model = config.get("gemini_model", DEFAULT_GEMINI_MODEL)
        runtime_cfg = _load_gemini_config()
        stored_endpoint = runtime_cfg.get("gemini_endpoint") or runtime_cfg.get("google_gemini_endpoint")
        if stored_endpoint:
            self.endpoint_template = stored_endpoint

        stored_key = runtime_cfg.get("gemini_api_key") or runtime_cfg.get("google_api_key")
        env_key = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
        if config.get("google_api_key"):
            self.api_key = config["google_api_key"]
        elif stored_key:
            self.api_key = stored_key
        elif env_key:
            self.api_key = env_key
        else:
            self.api_key = None

        self.model = (
            runtime_cfg.get("gemini_model")
            or self.model
            or DEFAULT_GEMINI_MODEL
        )

        stored_timeout = runtime_cfg.get("gemini_timeout")
        if stored_timeout:
            try:
                self.timeout = int(stored_timeout)
            except Exception:
                pass
        self.endpoint = self._format_endpoint(self.endpoint_template, self.model)

    def _assemble_prompt(self, messages: list) -> str:
        lines = []
        for msg in messages:
            role = (msg.get("role") or "user").upper()
            content = msg.get("content") or msg.get("text") or ""
            if content:
                lines.append(f"[{role}] {content}")
        return "\n".join(lines).strip()

    def _format_endpoint(self, template: str, model: str) -> str:
        """
        Resolve the endpoint with the requested model, tolerating placeholders.
        """
        target_model = model or DEFAULT_GEMINI_MODEL
        url = (template or DEFAULT_GEMINI_ENDPOINT).strip()
        if "{model}" in url:
            try:
                return url.format(model=target_model)
            except Exception:
                return DEFAULT_GEMINI_ENDPOINT.format(model=target_model)
        return url or DEFAULT_GEMINI_ENDPOINT.format(model=target_model)

    def generate(self, messages: list, options: dict | None = None, timeout: int | float | None = None) -> tuple[str, dict]:
        """
        Support both generateContent (v1beta) and generateMessage (v1beta2) style endpoints.
        """
        prompt = self._assemble_prompt(messages)
        request_timeout = timeout or self.timeout

        if not self.api_key:
            return "[ERROR: Google Gemini API key is not set. Configure it in the Services tab.]", {"error": "api_key_missing"}

        headers = {
            "Content-Type": "application/json",
            "x-goog-api-key": self.api_key,
        }
        endpoint_url = self._format_endpoint(self.endpoint_template, self.model)
        if "key=" not in endpoint_url:
            sep = "&" if "?" in endpoint_url else "?"
            endpoint_url = f"{endpoint_url}{sep}key={self.api_key}"

        # Choose payload shape based on endpoint
        use_generate_message = "generatemessage" in endpoint_url.lower()
        if use_generate_message:
            payload = {"prompt": {"text": prompt}}
        else:
            payload = {
                "contents": [
                    {
                        "parts": [{"text": prompt}],
                    }
                ]
            }

        if options:
            gen_config = {}
            if "temperature" in options:
                gen_config["temperature"] = options["temperature"]
            if "top_p" in options:
                gen_config["topP"] = options["top_p"]
            if gen_config:
                if use_generate_message:
                    payload["generationConfig"] = gen_config
                else:
                    payload["generationConfig"] = gen_config

        data = {}
        try:
            response = requests.post(endpoint_url, headers=headers, json=payload, timeout=request_timeout)
            response.raise_for_status()
            data = response.json()
            # v1beta generateContent response
            if not use_generate_message:
                text = data["candidates"][0]["content"]["parts"][0]["text"]
            else:
                # v1beta2 generateMessage response sometimes returns "candidates[..].content.parts[..].text" or "output_text"
                text = (
                    data.get("candidates", [{}])[0]
                    .get("content", {})
                    .get("parts", [{}])[0]
                    .get("text")
                ) or data.get("candidates", [{}])[0].get("output_text")
        except requests.exceptions.RequestException as e:
            return f"[ERROR: Could not connect to Google Gemini: {e}]", {"error": str(e)}
        except (KeyError, IndexError):
            return f"[ERROR: Unexpected response format from Google Gemini.]", {"error": "parsing_failed", "raw_response": data}

        metadata = {"model": self.model, "backend": "google_gemini"}
        if options:
            metadata["options"] = options
        return text, metadata


class CustomHTTPBackend(ModelBackend):
    """Configurable HTTP backend for OpenAI-compatible chat endpoints."""

    def __init__(self, config: dict):
        super().__init__(config)
        self.name = config.get("name") or config.get("label") or "Custom HTTP"
        self.base_url = (config.get("base_url") or config.get("url") or "").rstrip("/")
        self.api_key = (
            config.get("api_key")
            or os.getenv("XAI_API_KEY")
            or os.getenv("CUSTOM_HTTP_API_KEY")
            or os.getenv("GROK_API_KEY")
        )
        self.model = config.get("model") or config.get("model_name")
        self.headers = copy.deepcopy(config.get("headers") or {"Content-Type": "application/json"})
        self.request_template = copy.deepcopy(config.get("request_template") or {})
        self.timeout = config.get("timeout") or config.get("request_timeout") or 60

    def _fill_template(self, template, context: dict):
        """Recursively replace template tokens with context values."""
        if isinstance(template, str):
            if template == "{{messages}}":
                return context.get("messages")
            if template == "{{model}}":
                return context.get("model")
            if template == "{{temperature}}":
                return context.get("temperature")
            if template == "{{api_key}}":
                return context.get("api_key")
            text_val = template
            for key, val in context.items():
                if val is None:
                    continue
                text_val = text_val.replace(f"{{{{{key}}}}}", str(val))
            return text_val
        if isinstance(template, list):
            return [self._fill_template(item, context) for item in template]
        if isinstance(template, dict):
            return {k: self._fill_template(v, context) for k, v in template.items()}
        return template

    def _build_payload(self, messages: list, options: dict | None) -> dict:
        options = options or {}
        template_body = {}
        if isinstance(self.request_template, dict):
            template_body = self.request_template.get("body", {}) or {}
        payload = copy.deepcopy(template_body) if isinstance(template_body, (dict, list)) else {}
        context = {
            "messages": messages,
            "model": self.model,
            "temperature": options.get("temperature"),
            "top_p": options.get("top_p"),
            "api_key": self.api_key,
        }
        payload = self._fill_template(payload, context)
        if not isinstance(payload, dict):
            payload = {}
        if "messages" not in payload:
            payload["messages"] = messages
        if self.model and "model" not in payload:
            payload["model"] = self.model
        if "temperature" in options:
            payload["temperature"] = options["temperature"]
        if "top_p" in options and "top_p" not in payload:
            payload["top_p"] = options["top_p"]
        return payload

    def _build_headers(self) -> dict:
        headers = {"Content-Type": "application/json"}
        cfg_headers = self.headers if isinstance(self.headers, dict) else {}
        for key, value in cfg_headers.items():
            if isinstance(value, str):
                updated_val = value
                if self.api_key:
                    updated_val = updated_val.replace("{{api_key}}", self.api_key)
                    if "your_xai_api_key_here" in updated_val:
                        updated_val = updated_val.replace("your_xai_api_key_here", self.api_key)
                headers[key] = updated_val
            else:
                headers[key] = value
        if self.api_key and "Authorization" not in headers:
            headers["Authorization"] = f"Bearer {self.api_key}"
        return headers

    def _build_url(self) -> str:
        path = ""
        if isinstance(self.request_template, dict):
            path = self.request_template.get("path") or ""
        base = self.base_url.rstrip("/") if self.base_url else ""
        if base and path:
            return f"{base}/{path.lstrip('/')}"
        if base:
            return base
        return path

    def _coerce_content_text(self, content) -> str:
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            parts = []
            for item in content:
                if isinstance(item, str):
                    parts.append(item)
                elif isinstance(item, dict):
                    if isinstance(item.get("text"), str):
                        parts.append(item["text"])
                    elif isinstance(item.get("value"), str):
                        parts.append(item["value"])
            return "".join(parts)
        return ""

    def _extract_text_from_choice(self, choice: dict) -> str:
        if not isinstance(choice, dict):
            return ""
        message = choice.get("message")
        if isinstance(message, dict):
            text = self._coerce_content_text(message.get("content"))
            if text:
                return text
        delta = choice.get("delta")
        if isinstance(delta, dict):
            text = self._coerce_content_text(delta.get("content"))
            if text:
                return text
        if isinstance(choice.get("content"), (str, list)):
            return self._coerce_content_text(choice.get("content"))
        return ""

    def _extract_text_from_response(self, data: dict) -> str:
        if not isinstance(data, dict):
            return ""
        choices = data.get("choices")
        if isinstance(choices, list) and choices:
            text = self._extract_text_from_choice(choices[0])
            if text:
                return text
        if isinstance(data.get("message"), dict):
            text = self._coerce_content_text(data["message"].get("content"))
            if text:
                return text
        if isinstance(data.get("response"), str):
            return data["response"]
        if isinstance(data.get("text"), str):
            return data["text"]
        return ""

    def _consume_stream(self, response: requests.Response) -> str:
        pieces = []
        for raw_line in response.iter_lines(decode_unicode=True):
            if not raw_line:
                continue
            line = raw_line.strip()
            if line.startswith("data:"):
                line = line[len("data:"):].strip()
            if not line or line == "[DONE]":
                continue
            try:
                payload = json.loads(line)
            except Exception:
                continue
            text = self._extract_text_from_response(payload)
            if not text:
                choices = payload.get("choices")
                if isinstance(choices, list) and choices:
                    text = self._extract_text_from_choice(choices[0])
            if text:
                pieces.append(text)
        return "".join(pieces)

    def generate(self, messages: list, options: dict | None = None, timeout: int | float | None = None) -> tuple[str, dict]:
        if not self.base_url:
            return "[ERROR: Custom HTTP backend is missing a base_url.]", {"error": "missing_base_url"}

        payload = self._build_payload(messages, options)
        headers = self._build_headers()
        url = self._build_url()
        if not url:
            return "[ERROR: Custom HTTP backend URL could not be built from the config.]", {"error": "invalid_url"}

        method = "POST"
        if isinstance(self.request_template, dict):
            method = self.request_template.get("method", "POST")
        method = method.upper()
        stream_mode = bool(payload.get("stream")) if isinstance(payload, dict) else False
        request_timeout = timeout or self.timeout
        response = None
        try:
            response = requests.request(
                method,
                url,
                headers=headers,
                json=payload,
                timeout=request_timeout,
                stream=stream_mode,
            )
            response.raise_for_status()
            metadata = {
                "backend": "custom_http",
                "model": payload.get("model") or self.model,
                "stream": stream_mode,
            }
            if stream_mode:
                text = self._consume_stream(response)
                if not text:
                    metadata["error"] = "empty_stream"
                    text = "[ERROR: Custom HTTP backend returned no streamed content.]"
                return text, metadata

            data = response.json()
            metadata["raw"] = data
            text = self._extract_text_from_response(data)
            if text:
                return text, metadata
            metadata["error"] = "empty_reply"
            return "[ERROR: Custom HTTP backend returned an empty response.]", metadata
        except requests.exceptions.RequestException as exc:
            return f"[ERROR: Custom HTTP backend request failed: {exc}]", {"error": str(exc)}
        except json.JSONDecodeError:
            preview = response.text[:200] if response is not None else ""
            return "[ERROR: Custom HTTP backend returned non-JSON response.]", {"error": "invalid_json", "preview": preview}


class NoopBackend(ModelBackend):
    """Stub backend for offline/UI-only usage."""

    def generate(self, messages: list, options: dict = None, timeout: int | float | None = None) -> tuple[str, dict]:
        user_msg = ""
        if messages and isinstance(messages, list):
            for m in reversed(messages):
                if isinstance(m, dict) and m.get("role") == "user":
                    user_msg = m.get("content", "")
                    break
        reply = user_msg or "[NOOP BACKEND] This is a stub response. No real model was called."
        return reply, {"provider": "noop", "status": "ok", "model": "noop-stub"}

# --- 4. Backend Selector ---

def get_backend(backend_id: str | None = None, overrides: dict | None = None) -> ModelBackend:
    """
    Factory function that returns an instance of the selected backend.
    Falls back to the globally selected backend if none is provided.
    Optional overrides let callers supply a temporary model/base_url/etc. without
    mutating the global registry (useful for stress/model-switching runs).
    """
    target_id = backend_id or current_backend_id
    base_config = BACKEND_REGISTRY.get(target_id)
    if not base_config:
        logger.warning("Backend '%s' not found; falling back to noop-stub.", target_id)
        base_config = BACKEND_REGISTRY.get("noop-stub", {"id": "noop-stub", "provider": "noop"})

    config = copy.deepcopy(base_config)
    if overrides and isinstance(overrides, dict):
        config.update(overrides)

    provider = config.get("provider")
    if provider == "ollama":
        return OllamaBackend(config)
    if provider == "open_interpreter":
        return OpenInterpreterBackend(config)
    if provider == "google_gemini":
        return GoogleGeminiBackend(config)
    if provider == "custom_http":
        return CustomHTTPBackend(config)
    if provider == "noop":
        return NoopBackend(config)
    
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
