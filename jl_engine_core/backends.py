"""Licensed under the Apache License, Version 2.0. See LICENSE.md and NOTICE."""

import copy
import os
import json
import re
import time
import socket
import subprocess
import urllib.error
import urllib.parse
import urllib.request
from abc import ABC, abstractmethod
from pathlib import Path
from .config_loader import load_json_safely
from .logging_setup import get_logger

try:
    import requests  # type: ignore
    from requests import RequestException  # type: ignore
except Exception:  # pragma: no cover - requests optional fallback
    class _FallbackRequestException(Exception):
        pass

    class _FallbackHTTPError(_FallbackRequestException):
        def __init__(self, message: str, response=None):
            super().__init__(message)
            self.response = response

    class _FallbackTimeout(_FallbackRequestException):
        pass

    class _FallbackReadTimeout(_FallbackTimeout):
        pass

    class _FallbackConnectionError(_FallbackRequestException):
        pass

    class _FallbackResponse:
        def __init__(self, status_code: int, body: bytes, url: str):
            self.status_code = int(status_code)
            self._body = body or b""
            self.url = url
            self.text = self._body.decode("utf-8", errors="replace")
            self.content = self._body

        def json(self):
            if not self.text:
                return {}
            return json.loads(self.text)

        def raise_for_status(self) -> None:
            if self.status_code >= 400:
                raise _FallbackHTTPError(
                    f"HTTP {self.status_code} for {self.url}",
                    response=self,
                )

    class _FallbackRequests:
        class exceptions:
            HTTPError = _FallbackHTTPError
            Timeout = _FallbackTimeout
            ReadTimeout = _FallbackReadTimeout
            ConnectionError = _FallbackConnectionError

        @staticmethod
        def _normalize_timeout(timeout) -> float | None:
            if isinstance(timeout, (tuple, list)):
                vals = [float(v) for v in timeout if isinstance(v, (int, float)) and v > 0]
                return max(vals) if vals else None
            if isinstance(timeout, (int, float)) and timeout > 0:
                return float(timeout)
            return None

        @classmethod
        def post(cls, url, headers=None, data=None, json=None, timeout=None):
            payload = data
            request_headers = dict(headers or {})
            if json is not None:
                payload = __import__("json").dumps(json).encode("utf-8")
                request_headers.setdefault("Content-Type", "application/json")
            elif isinstance(payload, str):
                payload = payload.encode("utf-8")
            elif payload is None:
                payload = None
            t = cls._normalize_timeout(timeout)
            req = urllib.request.Request(url, data=payload, headers=request_headers, method="POST")
            try:
                with urllib.request.urlopen(req, timeout=t) as resp:
                    body = resp.read()
                    return _FallbackResponse(resp.status, body, url)
            except urllib.error.HTTPError as exc:
                body = exc.read() if hasattr(exc, "read") else b""
                response = _FallbackResponse(getattr(exc, "code", 500), body, url)
                raise _FallbackHTTPError(str(exc), response=response)
            except socket.timeout as exc:
                raise _FallbackReadTimeout(str(exc))
            except urllib.error.URLError as exc:
                raise _FallbackConnectionError(str(exc))

        @classmethod
        def get(cls, url, headers=None, timeout=None):
            request_headers = dict(headers or {})
            t = cls._normalize_timeout(timeout)
            req = urllib.request.Request(url, headers=request_headers, method="GET")
            try:
                with urllib.request.urlopen(req, timeout=t) as resp:
                    body = resp.read()
                    return _FallbackResponse(resp.status, body, url)
            except urllib.error.HTTPError as exc:
                body = exc.read() if hasattr(exc, "read") else b""
                response = _FallbackResponse(getattr(exc, "code", 500), body, url)
                raise _FallbackHTTPError(str(exc), response=response)
            except socket.timeout as exc:
                raise _FallbackReadTimeout(str(exc))
            except urllib.error.URLError as exc:
                raise _FallbackConnectionError(str(exc))

    requests = _FallbackRequests()
    RequestException = _FallbackRequestException

logger = get_logger(__name__)

# --- 1. Backend Registry Configuration ---
DEFAULT_GEMINI_ENDPOINT = (
    "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
)
DEFAULT_GEMINI_MODEL = "gemini-3-flash-preview"
DEFAULT_GEMINI_TIMEOUT = 60
DEFAULT_OPENAI_BASE_URL = "https://api.openai.com/v1"
DEFAULT_OPENAI_MODEL = "gpt-5.2"
DEFAULT_OPENAI_TIMEOUT = 90
DEFAULT_OPENROUTER_ENDPOINT = "https://openrouter.ai/api/v1/chat/completions"
DEFAULT_OPENROUTER_MODEL = "openrouter/auto"
DEFAULT_OPENROUTER_TIMEOUT = 90
GEMINI_CONFIG_PATH = Path(__file__).resolve().parent / "gemini_config.json"


def _env_float(name: str, default: float, minimum: float | None = None) -> float:
    raw = os.getenv(name)
    if raw is None:
        value = default
    else:
        try:
            value = float(raw)
        except (TypeError, ValueError):
            value = default
    if minimum is not None:
        value = max(minimum, value)
    return value


def _env_int(name: str, default: int, minimum: int = 0, maximum: int = 10) -> int:
    raw = os.getenv(name)
    if raw is None:
        value = default
    else:
        try:
            value = int(raw)
        except (TypeError, ValueError):
            value = default
    value = max(minimum, value)
    value = min(maximum, value)
    return value


OLLAMA_CONNECT_TIMEOUT = _env_float("JL_OLLAMA_CONNECT_TIMEOUT", 3.0, minimum=0.1)
OLLAMA_READ_TIMEOUT = _env_float("JL_OLLAMA_READ_TIMEOUT", 300.0, minimum=1.0)
OLLAMA_TIMEOUT_CAP = _env_float("JL_OLLAMA_TIMEOUT_CAP", 600.0, minimum=10.0)
OLLAMA_MAX_RETRIES = _env_int("JL_OLLAMA_MAX_RETRIES", 1, minimum=0, maximum=6)
_OLLAMA_AUTOSTART_ATTEMPTS: set[str] = set()


def _first_non_empty(*values: object, fallback: str) -> str:
    for value in values:
        text = str(value or "").strip()
        if text:
            return text
    return fallback


def _load_gemini_config() -> dict:
    data = load_json_safely(GEMINI_CONFIG_PATH)
    return data if isinstance(data, dict) else {}


GEMINI_LOCAL_CONFIG = _load_gemini_config()
if not GEMINI_LOCAL_CONFIG:
    # Backward-compatible fallback if legacy config file exists.
    legacy_path = Path(__file__).resolve().parent / "tts_config.json"
    if legacy_path.exists():
        GEMINI_LOCAL_CONFIG = load_json_safely(legacy_path)

DEFAULT_OLLAMA_BASE_URL = _first_non_empty(
    os.getenv("JL_OLLAMA_BASE_URL"),
    os.getenv("OLLAMA_URL"),
    GEMINI_LOCAL_CONFIG.get("ollama_base_url"),
    fallback="http://127.0.0.1:11434",
)
DEFAULT_OLLAMA_MODEL = _first_non_empty(
    os.getenv("JL_OLLAMA_MODEL"),
    os.getenv("BENCH_OLLAMA_MODEL"),
    GEMINI_LOCAL_CONFIG.get("ollama_model"),
    fallback="dolphin3:latest",
)
DEFAULT_OPENAI_BASE_URL = _first_non_empty(
    os.getenv("JL_OPENAI_BASE_URL"),
    os.getenv("OPENAI_BASE_URL"),
    GEMINI_LOCAL_CONFIG.get("openai_base_url"),
    GEMINI_LOCAL_CONFIG.get("openai_endpoint"),
    fallback=DEFAULT_OPENAI_BASE_URL,
)
DEFAULT_OPENAI_MODEL = _first_non_empty(
    os.getenv("JL_OPENAI_MODEL"),
    os.getenv("OPENAI_MODEL"),
    GEMINI_LOCAL_CONFIG.get("openai_model"),
    fallback=DEFAULT_OPENAI_MODEL,
)
DEFAULT_OPENAI_TIMEOUT = _env_float("JL_OPENAI_TIMEOUT", DEFAULT_OPENAI_TIMEOUT, minimum=1.0)


def _normalize_ollama_base_url(raw_url: str | None) -> str:
    base = str(raw_url or "").strip()
    if not base:
        base = DEFAULT_OLLAMA_BASE_URL
    if not base.startswith(("http://", "https://")):
        base = f"http://{base}"
    return base.rstrip("/")


def list_ollama_model_names(base_url: str | None = None) -> list[str]:
    target = _normalize_ollama_base_url(base_url)
    try:
        resp = requests.get(
            f"{target}/api/tags",
            timeout=(OLLAMA_CONNECT_TIMEOUT, min(10.0, OLLAMA_READ_TIMEOUT)),
        )
        resp.raise_for_status()
        payload = resp.json() if getattr(resp, "content", None) else {}
        models = payload.get("models") or []
        names = [m.get("name") for m in models if isinstance(m, dict) and m.get("name")]
        return sorted(set(str(name).strip() for name in names if str(name).strip()))
    except RequestException:
        return []


def ollama_model_allowed(model_name: str | None) -> bool:
    """Heuristic filter for startup model auto-selection in UI paths."""
    name = str(model_name or "").strip().lower()
    if not name:
        return False
    if any(token in name for token in ("70b", "72b", "90b", "110b", "405b", "671b")):
        return False
    size_match = re.search(r"(\d+(?:\.\d+)?)b", name)
    if size_match:
        try:
            if float(size_match.group(1)) > 34.0:
                return False
        except (TypeError, ValueError):
            pass
    return True


def _is_loopback_ollama_url(base_url: str) -> bool:
    try:
        host = str(urllib.parse.urlparse(base_url).hostname or "").strip().lower()
    except Exception:
        return False
    return host in {"127.0.0.1", "localhost", "::1"}


def _start_ollama_server_process() -> bool:
    command = ["ollama", "serve"]
    creationflags = 0
    if os.name == "nt":
        creationflags = int(getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)) | int(
            getattr(subprocess, "DETACHED_PROCESS", 0)
        )
    try:
        subprocess.Popen(
            command,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=creationflags,
        )
        logger.info("[Backends] Requested Ollama autostart with command: %s", " ".join(command))
        return True
    except Exception as exc:
        logger.warning("[Backends] Failed to autostart Ollama (%s): %s", " ".join(command), exc)
        return False


def ensure_ollama_server(
    base_url: str | None = None,
    *,
    autostart: bool = True,
    wait_timeout: float = 15.0,
    poll_interval: float = 0.5,
) -> bool:
    target = _normalize_ollama_base_url(base_url)
    deadline = time.time() + max(0.0, float(wait_timeout))
    poll_delay = max(0.1, float(poll_interval))

    should_autostart = bool(autostart) and _is_loopback_ollama_url(target)
    if should_autostart and target not in _OLLAMA_AUTOSTART_ATTEMPTS:
        _OLLAMA_AUTOSTART_ATTEMPTS.add(target)
        _start_ollama_server_process()

    while True:
        try:
            resp = requests.get(
                f"{target}/api/tags",
                timeout=(OLLAMA_CONNECT_TIMEOUT, min(10.0, OLLAMA_READ_TIMEOUT)),
            )
            status = int(getattr(resp, "status_code", 0) or 0)
            if 200 <= status < 500:
                return True
        except RequestException:
            pass

        if time.time() >= deadline:
            return False
        time.sleep(poll_delay)


def resolve_ollama_model_name(
    preferred: str | None = None,
    *,
    base_url: str | None = None,
    allow_unavailable: bool = True,
    fallback_to_first_installed: bool = True,
) -> str:
    chosen = str(preferred or "").strip()
    models = list_ollama_model_names(base_url=base_url)
    if models:
        if chosen and chosen in models:
            return chosen
        if fallback_to_first_installed:
            return models[0]
        return ""
    if allow_unavailable:
        return chosen
    return ""


def _normalize_openai_base_url(raw_url: str | None) -> str:
    base = str(raw_url or "").strip()
    if not base:
        base = DEFAULT_OPENAI_BASE_URL
    if not base.startswith(("http://", "https://")):
        base = f"https://{base}"
    return base.rstrip("/")

BACKEND_REGISTRY = {
    "google-gemini": {
        "id": "google-gemini",
        "label": "Google Gemini",
        "provider": "google_gemini",
        "google_api_key": GEMINI_LOCAL_CONFIG.get("gemini_api_key")
        or GEMINI_LOCAL_CONFIG.get("google_api_key"),
        "google_gemini_endpoint": GEMINI_LOCAL_CONFIG.get("gemini_endpoint")
        or GEMINI_LOCAL_CONFIG.get("google_gemini_endpoint")
        or DEFAULT_GEMINI_ENDPOINT,
        "gemini_endpoint": GEMINI_LOCAL_CONFIG.get("gemini_endpoint")
        or GEMINI_LOCAL_CONFIG.get("google_gemini_endpoint")
        or DEFAULT_GEMINI_ENDPOINT,
        "gemini_model": GEMINI_LOCAL_CONFIG.get("gemini_model") or DEFAULT_GEMINI_MODEL,
        "google_gemini_timeout": GEMINI_LOCAL_CONFIG.get(
            "google_gemini_timeout", DEFAULT_GEMINI_TIMEOUT
        ),
    },
    "ollama-local": {
        "id": "ollama-local",
        "label": "Ollama (Local)",
        "provider": "ollama",
        "baseUrl": DEFAULT_OLLAMA_BASE_URL,
        "modelName": DEFAULT_OLLAMA_MODEL,
        "model_name": DEFAULT_OLLAMA_MODEL,
        "apiKey": "",
    },
    "jan-ai": {
        "id": "jan-ai",
        "label": "Jan AI",
        "provider": "openai",
        "openai_api_key": "not-needed",
        "openai_base_url": "http://127.0.0.1:1337/v1",
        "openai_model": "mistral-ins-7b-q4",
        "openai_timeout": 120,
    },
    "openai": {
        "id": "openai",
        "label": "OpenAI",
        "provider": "openai",
        "openai_api_key": GEMINI_LOCAL_CONFIG.get("openai_api_key") or os.getenv("OPENAI_API_KEY"),
        "openai_base_url": DEFAULT_OPENAI_BASE_URL,
        "openai_model": DEFAULT_OPENAI_MODEL,
        "openai_timeout": GEMINI_LOCAL_CONFIG.get("openai_timeout") or DEFAULT_OPENAI_TIMEOUT,
    },
    "openrouter": {
        "id": "openrouter",
        "label": "OpenRouter",
        "provider": "openrouter",
        "openrouter_api_key": GEMINI_LOCAL_CONFIG.get("openrouter_api_key")
        or os.getenv("OPENROUTER_API_KEY"),
        "openrouter_endpoint": GEMINI_LOCAL_CONFIG.get("openrouter_endpoint")
        or os.getenv("OPENROUTER_ENDPOINT")
        or DEFAULT_OPENROUTER_ENDPOINT,
        "openrouter_model": GEMINI_LOCAL_CONFIG.get("openrouter_model")
        or os.getenv("JL_OPENROUTER_MODEL")
        or DEFAULT_OPENROUTER_MODEL,
        "openrouter_timeout": GEMINI_LOCAL_CONFIG.get("openrouter_timeout")
        or DEFAULT_OPENROUTER_TIMEOUT,
        "openrouter_site_url": GEMINI_LOCAL_CONFIG.get("openrouter_site_url")
        or os.getenv("OPENROUTER_SITE_URL")
        or "",
        "openrouter_app_name": GEMINI_LOCAL_CONFIG.get("openrouter_app_name")
        or os.getenv("OPENROUTER_APP_NAME")
        or "JL Engine Core",
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
        "request_template": {},
    },
}

PRIMARY_BACKEND_ID = "ollama-local"
SECONDARY_BACKEND_ID = "openrouter"
TERTIARY_BACKEND_ID = "google-gemini"

# SET DEFAULT BACKEND TO OLLAMA
current_backend_id = PRIMARY_BACKEND_ID
brain_backend_id = current_backend_id
tool_backend_id = current_backend_id


def _merge_backend_config(
    target_id: str, incoming: dict, default_provider: str | None = None
) -> None:
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
    if not isinstance(backends_cfg, dict):
        return
    brain_cfg = backends_cfg.get("brain_config")
    if isinstance(brain_cfg, dict):
        provider = brain_cfg.get("provider")
        target_id = (
            brain_cfg.get("id")
            or brain_cfg.get("backend_id")
            or brain_cfg.get("backend")
            or "custom_http"
        )
        payload = copy.deepcopy(brain_cfg)
        payload["id"] = target_id
        _merge_backend_config(target_id, payload, default_provider=provider or "custom_http")
    tool_cfg = backends_cfg.get("tool_config")
    if isinstance(tool_cfg, dict):
        provider = tool_cfg.get("provider")
        target_id = (
            tool_cfg.get("id")
            or tool_cfg.get("backend_id")
            or tool_cfg.get("backend")
            or "custom_http"
        )
        payload = copy.deepcopy(tool_cfg)
        payload["id"] = target_id
        _merge_backend_config(target_id, payload, default_provider=provider or "custom_http")


class ModelBackend(ABC):
    """Abstract backend interface for model providers."""

    def __init__(self, config: dict):
        self.config = config

    @abstractmethod
    def generate(
        self, messages: list, options: dict = None, timeout: int | float | None = None
    ) -> tuple[str, dict]:
        pass


class OllamaBackend(ModelBackend):
    """Backend for local Ollama deployments."""

    def generate(
        self,
        messages: list,
        options: dict = None,
        timeout: int | float | tuple[float, float] | None = None,
    ) -> tuple[str, dict]:
        base_url = self._base_url()
        api_url = f"{base_url}/api/chat"
        model_name = self._model_name()
        timeout_cfg = self._request_timeout(timeout)
        retries = self._retry_count()
        model_fallback_used = False
        payload = {"model": model_name, "messages": messages, "stream": False}
        if options:
            payload["options"] = options
        for attempt in range(1, retries + 2):
            payload["model"] = model_name
            try:
                resp = requests.post(
                    api_url,
                    headers={"Content-Type": "application/json"},
                    data=json.dumps(payload),
                    timeout=timeout_cfg,
                )
                resp.raise_for_status()
                data = resp.json()
                reply_content = data.get("message", {}).get("content", "")
                meta = {"model": model_name, "attempt": attempt, "retries": attempt - 1}
                if model_fallback_used:
                    meta["model_autofallback"] = True
                return reply_content, meta
            except (RequestException, json.JSONDecodeError, KeyError, TypeError) as exc:
                if isinstance(exc, requests.exceptions.HTTPError):
                    fallback = self._fallback_model_for_missing(base_url, model_name, exc)
                    if fallback and fallback != model_name:
                        logger.warning(
                            "[Backends] Ollama model '%s' unavailable; switching to '%s'.",
                            model_name,
                            fallback,
                        )
                        model_name = fallback
                        model_fallback_used = True
                        continue
                if attempt <= retries and self._retryable_error(exc):
                    timeout_cfg = self._next_timeout(timeout_cfg, exc)
                    time.sleep(min(2.0, 0.35 * attempt))
                    continue
                logger.exception("[Backends] Ollama connection failed: %s", exc)
                return (
                    f"[ERROR: Ollama connection failed: {exc}]",
                    {"error": str(exc), "model": model_name, "attempts": attempt},
                )
        return (
            "[ERROR: Ollama connection failed: exhausted retries]",
            {"error": "exhausted_retries", "model": model_name},
        )

    def _base_url(self) -> str:
        return _normalize_ollama_base_url(
            self.config.get("baseUrl") or self.config.get("base_url") or DEFAULT_OLLAMA_BASE_URL
        )

    def _model_name(self) -> str:
        configured = self.config.get("modelName") or self.config.get("model_name") or DEFAULT_OLLAMA_MODEL
        model = resolve_ollama_model_name(configured, base_url=self._base_url())
        model = str(model).strip()
        return model or str(configured or "").strip() or DEFAULT_OLLAMA_MODEL

    def _retry_count(self) -> int:
        raw = self.config.get("retry_attempts", OLLAMA_MAX_RETRIES)
        try:
            retries = int(raw)
        except (TypeError, ValueError):
            retries = OLLAMA_MAX_RETRIES
        return max(0, min(6, retries))

    def _request_timeout(
        self, timeout: int | float | tuple[float, float] | None
    ) -> tuple[float, float]:
        if isinstance(timeout, (tuple, list)) and len(timeout) >= 2:
            connect_timeout, read_timeout = timeout[0], timeout[1]
        elif isinstance(timeout, (int, float)) and not isinstance(timeout, bool) and timeout > 0:
            connect_timeout, read_timeout = OLLAMA_CONNECT_TIMEOUT, float(timeout)
        else:
            connect_timeout = self.config.get("connect_timeout", OLLAMA_CONNECT_TIMEOUT)
            read_timeout = self.config.get("read_timeout", OLLAMA_READ_TIMEOUT)
        try:
            connect_timeout = float(connect_timeout)
        except (TypeError, ValueError):
            connect_timeout = OLLAMA_CONNECT_TIMEOUT
        try:
            read_timeout = float(read_timeout)
        except (TypeError, ValueError):
            read_timeout = OLLAMA_READ_TIMEOUT
        connect_timeout = max(0.1, connect_timeout)
        read_timeout = max(1.0, read_timeout)
        return connect_timeout, read_timeout

    def _next_timeout(
        self, current: tuple[float, float], exc: Exception
    ) -> tuple[float, float]:
        connect_timeout, read_timeout = current
        if isinstance(exc, requests.exceptions.ReadTimeout):
            read_timeout = min(OLLAMA_TIMEOUT_CAP, max(read_timeout + 15.0, read_timeout * 1.4))
        return connect_timeout, read_timeout

    def _retryable_error(self, exc: Exception) -> bool:
        return isinstance(
            exc,
            (
                requests.exceptions.Timeout,
                requests.exceptions.ConnectionError,
                json.JSONDecodeError,
            ),
        )

    def _fallback_model_for_missing(
        self, base_url: str, current_model: str, exc: requests.exceptions.HTTPError
    ) -> str | None:
        if not self._is_model_missing_response(exc):
            return None
        models = self._list_models(base_url)
        if not models:
            return None
        if current_model in models:
            return current_model
        return models[0]

    def _is_model_missing_response(self, exc: requests.exceptions.HTTPError) -> bool:
        response = getattr(exc, "response", None)
        if response is None:
            return False
        if response.status_code != 404:
            return False
        body = (response.text or "").lower()
        return "model" in body and ("not found" in body or "does not exist" in body)

    def _list_models(self, base_url: str) -> list[str]:
        return list_ollama_model_names(base_url)


class OpenAIBackend(ModelBackend):
    """Backend for OpenAI text generation via the Responses API."""

    def __init__(self, config: dict):
        super().__init__(config)
        self.api_key = config.get("openai_api_key") or os.getenv("OPENAI_API_KEY")
        self.base_url = _normalize_openai_base_url(
            config.get("openai_base_url")
            or config.get("openai_endpoint")
            or config.get("baseUrl")
            or config.get("base_url")
            or DEFAULT_OPENAI_BASE_URL
        )
        self.model = config.get("openai_model") or os.getenv("OPENAI_MODEL") or DEFAULT_OPENAI_MODEL
        self.timeout = config.get("openai_timeout") or DEFAULT_OPENAI_TIMEOUT
        self.reasoning_effort = str(config.get("openai_reasoning_effort") or "").strip()

    def _endpoint(self) -> str:
        if self.base_url.endswith("/responses"):
            return self.base_url
        return f"{self.base_url}/responses"

    def _normalized_input(self, messages: list) -> list[dict]:
        normalized: list[dict] = []
        for message in messages or []:
            if not isinstance(message, dict):
                continue
            role = str(message.get("role") or "user").strip() or "user"
            content = message.get("content")
            if isinstance(content, list):
                chunks: list[str] = []
                for item in content:
                    if isinstance(item, dict):
                        text = item.get("text")
                        if text is not None:
                            chunks.append(str(text))
                    elif item is not None:
                        chunks.append(str(item))
                text = "\n".join(part for part in chunks if part).strip()
            else:
                text = str(content or "").strip()
            normalized.append(
                {
                    "type": "message",
                    "role": role,
                    "content": [{"type": "input_text", "text": text}],
                }
            )
        return normalized

    def _extract_output_text(self, payload: dict) -> str:
        direct = payload.get("output_text")
        if isinstance(direct, str) and direct.strip():
            return direct
        parts: list[str] = []
        for item in payload.get("output") or []:
            if not isinstance(item, dict):
                continue
            if item.get("type") != "message":
                continue
            for content in item.get("content") or []:
                if not isinstance(content, dict):
                    continue
                text = content.get("text")
                if text is not None:
                    parts.append(str(text))
                    continue
                if content.get("type") == "output_text":
                    text = content.get("text")
                    if text is not None:
                        parts.append(str(text))
        return "\n".join(part for part in parts if part).strip()

    def generate(
        self, messages: list, options: dict | None = None, timeout: int | float | None = None
    ) -> tuple[str, dict]:
        if not self.api_key:
            return "[ERROR: OpenAI API key missing]", {"error": "api_key_missing"}

        payload: dict = {
            "model": self.model,
            "input": self._normalized_input(messages),
            "store": False,
        }
        if options and isinstance(options, dict):
            if options.get("temperature") is not None:
                payload["temperature"] = options["temperature"]
            if options.get("top_p") is not None:
                payload["top_p"] = options["top_p"]
            if options.get("max_tokens") is not None:
                payload["max_output_tokens"] = options["max_tokens"]
        if self.reasoning_effort:
            payload["reasoning"] = {"effort": self.reasoning_effort}

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        try:
            response = requests.post(
                self._endpoint(),
                headers=headers,
                json=payload,
                timeout=timeout or self.timeout,
            )
            response.raise_for_status()
            data = response.json()
            text = self._extract_output_text(data)
            return text, {
                "model": data.get("model") or self.model,
                "backend": "openai",
                "response_id": data.get("id"),
            }
        except (RequestException, KeyError, IndexError, TypeError, json.JSONDecodeError) as exc:
            logger.exception("[Backends] OpenAI call failed: %s", exc)
            return f"[ERROR: OpenAI call failed: {exc}]", {"error": str(exc)}


class GoogleGeminiBackend(ModelBackend):
    """Backend for Google Gemini HTTP API."""

    def __init__(self, config: dict):
        super().__init__(config)
        self.endpoint_template = config.get("gemini_endpoint") or DEFAULT_GEMINI_ENDPOINT
        self.api_key = (
            config.get("google_api_key")
            or os.getenv("GEMINI_API_KEY")
            or os.getenv("GOOGLE_API_KEY")
        )
        self.timeout = config.get("google_gemini_timeout", DEFAULT_GEMINI_TIMEOUT)
        self.model = config.get("gemini_model") or DEFAULT_GEMINI_MODEL
        self.endpoint = self._format_endpoint(self.endpoint_template, self.model)

    def _assemble_prompt(self, messages: list) -> str:
        lines = [
            f"[{(m.get('role') or 'user').upper()}] {m.get('content') or ''}" for m in messages
        ]
        return "\n".join(lines).strip()

    def _format_endpoint(self, template: str, model: str) -> str:
        target_model = model or DEFAULT_GEMINI_MODEL
        url = template.strip()
        if "{model}" in url:
            return url.format(model=target_model)
        return url

    def generate(
        self, messages: list, options: dict | None = None, timeout: int | float | None = None
    ) -> tuple[str, dict]:
        prompt = self._assemble_prompt(messages)
        if not self.api_key:
            return "[ERROR: Gemini API key missing]", {"error": "api_key_missing"}
        headers = {"Content-Type": "application/json", "x-goog-api-key": self.api_key}
        endpoint_url = self.endpoint
        if "key=" not in endpoint_url:
            endpoint_url += f"{'&' if '?' in endpoint_url else '?'}key={self.api_key}"
        payload = {"contents": [{"parts": [{"text": prompt}]}]}
        try:
            response = requests.post(
                endpoint_url, headers=headers, json=payload, timeout=timeout or self.timeout
            )
            response.raise_for_status()
            data = response.json()
            text = data["candidates"][0]["content"]["parts"][0]["text"]
            return text, {"model": self.model, "backend": "google_gemini"}
        except (RequestException, KeyError, IndexError, TypeError, json.JSONDecodeError) as exc:
            logger.exception("[Backends] Gemini call failed: %s", exc)
            return f"[ERROR: Gemini call failed: {exc}]", {"error": str(exc)}


class OpenRouterBackend(ModelBackend):
    """Backend for OpenRouter Chat Completions API."""

    def __init__(self, config: dict):
        super().__init__(config)
        self.endpoint = config.get("openrouter_endpoint") or DEFAULT_OPENROUTER_ENDPOINT
        self.api_key = config.get("openrouter_api_key") or os.getenv("OPENROUTER_API_KEY")
        self.timeout = config.get("openrouter_timeout", DEFAULT_OPENROUTER_TIMEOUT)
        self.model = config.get("openrouter_model") or DEFAULT_OPENROUTER_MODEL
        self.site_url = config.get("openrouter_site_url") or os.getenv("OPENROUTER_SITE_URL")
        self.app_name = config.get("openrouter_app_name") or os.getenv("OPENROUTER_APP_NAME")

    def _normalized_messages(self, messages: list) -> list[dict]:
        normalized = []
        for message in messages or []:
            if not isinstance(message, dict):
                continue
            role = str(message.get("role") or "user").strip() or "user"
            content = message.get("content")
            if isinstance(content, list):
                parts = []
                for item in content:
                    if isinstance(item, dict):
                        text = item.get("text")
                        if text is not None:
                            parts.append(str(text))
                    elif item is not None:
                        parts.append(str(item))
                content = "\n".join(p for p in parts if p).strip()
            else:
                content = str(content or "").strip()
            normalized.append({"role": role, "content": content})
        return normalized

    def generate(
        self, messages: list, options: dict | None = None, timeout: int | float | None = None
    ) -> tuple[str, dict]:
        if not self.api_key:
            return "[ERROR: OpenRouter API key missing]", {"error": "api_key_missing"}

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        if self.site_url:
            headers["HTTP-Referer"] = self.site_url
        if self.app_name:
            headers["X-Title"] = self.app_name

        payload: dict = {
            "model": self.model,
            "messages": self._normalized_messages(messages),
        }
        if options and isinstance(options, dict):
            for key in ("temperature", "top_p", "max_tokens", "presence_penalty", "frequency_penalty"):
                value = options.get(key)
                if value is not None:
                    payload[key] = value

        try:
            response = requests.post(
                self.endpoint,
                headers=headers,
                json=payload,
                timeout=timeout or self.timeout,
            )
            response.raise_for_status()
            data = response.json()
            choice = ((data.get("choices") or [{}])[0]) if isinstance(data, dict) else {}
            message = choice.get("message", {}) if isinstance(choice, dict) else {}
            content = message.get("content", "") if isinstance(message, dict) else ""
            if isinstance(content, list):
                chunks = []
                for chunk in content:
                    if isinstance(chunk, dict):
                        text = chunk.get("text")
                        if text is not None:
                            chunks.append(str(text))
                    elif chunk is not None:
                        chunks.append(str(chunk))
                content = "\n".join(chunks).strip()
            else:
                content = str(content or "")
            return content, {"model": self.model, "backend": "openrouter"}
        except (RequestException, KeyError, IndexError, TypeError, json.JSONDecodeError) as exc:
            logger.exception("[Backends] OpenRouter call failed: %s", exc)
            return f"[ERROR: OpenRouter call failed: {exc}]", {"error": str(exc)}


def get_backend(backend_id: str | None = None, overrides: dict | None = None) -> ModelBackend:
    target_id = backend_id or current_backend_id
    fallback_order = [
        target_id,
        current_backend_id,
        PRIMARY_BACKEND_ID,
        SECONDARY_BACKEND_ID,
        TERTIARY_BACKEND_ID,
    ]
    base_config = None
    for candidate_id in fallback_order:
        if candidate_id and candidate_id in BACKEND_REGISTRY:
            base_config = BACKEND_REGISTRY[candidate_id]
            break
    if not isinstance(base_config, dict):
        raise LookupError("No configured backends available.")
    config = copy.deepcopy(base_config)
    if overrides:
        config.update(overrides)
    provider = config.get("provider")
    if provider == "ollama":
        return OllamaBackend(config)
    if provider == "openai":
        return OpenAIBackend(config)
    if provider == "openrouter":
        return OpenRouterBackend(config)
    if provider == "google_gemini":
        return GoogleGeminiBackend(config)
    raise NotImplementedError(f"No provider: {provider}")


def configure_backends(brain_id: str | None = None, tool_id: str | None = None) -> None:
    global brain_backend_id, tool_backend_id, current_backend_id
    if brain_id in BACKEND_REGISTRY:
        brain_backend_id = current_backend_id = brain_id
    if tool_id in BACKEND_REGISTRY:
        tool_backend_id = tool_id


def get_brain_backend() -> ModelBackend:
    return get_backend(brain_backend_id)


def get_tool_backend() -> ModelBackend:
    return get_backend(tool_backend_id)


def set_brain_backend_id(backend_id: str) -> None:
    if backend_id in BACKEND_REGISTRY:
        configure_backends(brain_id=backend_id)


def set_tool_backend_id(backend_id: str) -> None:
    if backend_id in BACKEND_REGISTRY:
        configure_backends(tool_id=backend_id)
