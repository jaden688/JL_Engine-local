"""Backend controller for JL Platform UI interactions.

Licensed under the Apache License, Version 2.0. See LICENSE.md and NOTICE.
"""

from __future__ import annotations

import json
import os
from copy import deepcopy
from pathlib import Path

import requests

from jl_engine_core import backends as core_backends
from jl_platform.core.util.logging import get_logger

logger = get_logger(__name__)

BACKEND_REGISTRY = core_backends.BACKEND_REGISTRY
OLLAMA_CONNECT_TIMEOUT = core_backends.OLLAMA_CONNECT_TIMEOUT
OLLAMA_READ_TIMEOUT = core_backends.OLLAMA_READ_TIMEOUT
_REPO_ROOT = Path(__file__).resolve().parents[3]
_CANONICAL_HEADLESS_CONFIG_PATH = (
    _REPO_ROOT / "jl_engine_core" / "data" / "config" / "JLframe_Engine_Framework.headless.json"
)
_LEGACY_HEADLESS_CONFIG_PATH = _REPO_ROOT / "config" / "JLframe_Engine_Framework.headless.json"
_SERVICE_CONFIG_PATH = _REPO_ROOT / "jl_engine_core" / "gemini_config.json"
_SENSITIVE_KEYS = {
    "apikey",
    "api_key",
    "google_api_key",
    "gemini_api_key",
    "openai_api_key",
    "openrouter_api_key",
}
_VALID_RUNTIME_MODES = {"local_only", "hybrid"}
_LOCAL_BACKEND_ID = "ollama-local"
_EXTERNAL_BACKEND_IDS = ("openai", "openrouter", "google-gemini")


def _enforce_ollama_base_url(raw_url: str, service_config: dict | None = None) -> str:
    base = (raw_url or "").strip()
    if not base:
        base = "http://127.0.0.1:11434"
    if not base.startswith(("http://", "https://")):
        base = f"http://{base}"
    if service_config and isinstance(service_config, dict):
        service_config["ollama_base_url"] = base
    return base.rstrip("/")


def _enforce_openai_base_url(raw_url: str, service_config: dict | None = None) -> str:
    base = (raw_url or "").strip()
    if not base:
        base = core_backends.DEFAULT_OPENAI_BASE_URL
    if not base.startswith(("http://", "https://")):
        base = f"https://{base}"
    normalized = base.rstrip("/")
    if service_config and isinstance(service_config, dict):
        service_config["openai_base_url"] = normalized
    return normalized


def _list_ollama_models(base_url: str) -> list[dict]:
    try:
        resp = requests.get(f"{base_url}/api/tags", timeout=(OLLAMA_CONNECT_TIMEOUT, 10))
        resp.raise_for_status()
        payload = resp.json()
        models = payload.get("models") or []
        results: list[dict] = []
        for item in models:
            if not isinstance(item, dict):
                continue
            name = str(item.get("name") or "").strip()
            if not name:
                continue
            size_raw = item.get("size") or 0
            try:
                size = int(size_raw)
            except (TypeError, ValueError):
                size = 0
            results.append(
                {
                    "name": name,
                    "size": size,
                    "size_mb": round(size / (1024 * 1024), 1) if size > 0 else 0.0,
                    "modified_at": item.get("modified_at"),
                }
            )
        return results
    except requests.RequestException as exc:
        logger.exception("[BackendController] Failed to list Ollama models: %s", exc)
        return []


def _load_json_dict(path: Path) -> dict:
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        logger.exception("[BackendController] Failed to read config '%s': %s", path, exc)
        return {}
    return data if isinstance(data, dict) else {}


def _write_json_dict(path: Path, data: dict) -> bool:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
        return True
    except Exception as exc:
        logger.exception("[BackendController] Failed to write config '%s': %s", path, exc)
        return False


def _headless_config_read_paths() -> tuple[Path, ...]:
    # The runtime data tree is the source of truth. Keep the legacy root config
    # as a read-only fallback so older local checkouts do not lose settings.
    paths: list[Path] = []
    for path in (_CANONICAL_HEADLESS_CONFIG_PATH, _LEGACY_HEADLESS_CONFIG_PATH):
        if path not in paths:
            paths.append(path)
    return tuple(paths)


def _headless_config_write_path() -> Path:
    return _CANONICAL_HEADLESS_CONFIG_PATH


def _sanitize_backend_config(config: dict | None) -> dict:
    payload = deepcopy(config or {})
    for key in list(payload.keys()):
        if str(key).strip().lower() in _SENSITIVE_KEYS:
            payload.pop(key, None)
    return payload


def _persist_backend_selection_to_path(
    path: Path,
    *,
    brain_backend_id: str,
    tool_backend_id: str,
) -> bool:
    data = _load_json_dict(path)
    if not isinstance(data, dict):
        data = {}
    jl_engine = data.setdefault("jl_engine", {})
    if not isinstance(jl_engine, dict):
        jl_engine = {}
        data["jl_engine"] = jl_engine
    backends_cfg = jl_engine.setdefault("backends", {})
    if not isinstance(backends_cfg, dict):
        backends_cfg = {}
        jl_engine["backends"] = backends_cfg
    backends_cfg["default"] = brain_backend_id
    backends_cfg["brain_backend"] = brain_backend_id
    backends_cfg["tool_backend"] = tool_backend_id
    brain_cfg = _sanitize_backend_config(BACKEND_REGISTRY.get(brain_backend_id))
    tool_cfg = _sanitize_backend_config(BACKEND_REGISTRY.get(tool_backend_id))
    if brain_cfg:
        backends_cfg["brain_config"] = brain_cfg
    if tool_cfg:
        backends_cfg["tool_config"] = tool_cfg
    return _write_json_dict(path, data)


def _persist_service_config_updates(updates: dict[str, str | None]) -> list[str]:
    data = _load_json_dict(_SERVICE_CONFIG_PATH)
    for key, value in updates.items():
        if value is None:
            data.pop(key, None)
            continue
        text = str(value).strip()
        if text:
            data[key] = text
        else:
            data.pop(key, None)
    if not _write_json_dict(_SERVICE_CONFIG_PATH, data):
        return []
    return [str(_SERVICE_CONFIG_PATH)]


def get_ollama_base_url() -> str:
    cfg = BACKEND_REGISTRY.get("ollama-local", {})
    return _enforce_ollama_base_url(str(cfg.get("baseUrl") or cfg.get("base_url") or ""))


def get_ollama_configured_model() -> str:
    cfg = BACKEND_REGISTRY.get("ollama-local", {})
    return str(cfg.get("modelName") or cfg.get("model_name") or "").strip()


def get_ollama_model() -> str:
    return core_backends.resolve_ollama_model_name(
        get_ollama_configured_model(),
        base_url=get_ollama_base_url(),
        allow_unavailable=False,
        fallback_to_first_installed=True,
    )


def list_ollama_models() -> list[dict]:
    return _list_ollama_models(get_ollama_base_url())


def get_openai_base_url() -> str:
    cfg = BACKEND_REGISTRY.get("openai", {})
    return _enforce_openai_base_url(
        str(cfg.get("openai_base_url") or cfg.get("openai_endpoint") or cfg.get("baseUrl") or "")
    )


def get_openai_model() -> str:
    cfg = BACKEND_REGISTRY.get("openai", {})
    return str(cfg.get("openai_model") or "").strip()


def has_openai_api_key() -> bool:
    cfg = BACKEND_REGISTRY.get("openai", {})
    return bool(str(cfg.get("openai_api_key") or os.getenv("OPENAI_API_KEY") or "").strip())


def _read_runtime_mode_from_path(path: Path) -> str | None:
    data = _load_json_dict(path)
    jl_engine = data.get("jl_engine") if isinstance(data, dict) else None
    if isinstance(jl_engine, dict):
        mode = str(jl_engine.get("runtime_mode") or "").strip().lower()
        if mode in _VALID_RUNTIME_MODES:
            return mode
    return None


def _persist_runtime_mode_to_path(path: Path, mode: str) -> bool:
    data = _load_json_dict(path)
    if not isinstance(data, dict):
        data = {}
    jl_engine = data.setdefault("jl_engine", {})
    if not isinstance(jl_engine, dict):
        jl_engine = {}
        data["jl_engine"] = jl_engine
    jl_engine["runtime_mode"] = mode
    return _write_json_dict(path, data)


def _normalize_backend_id(value: str | None) -> str | None:
    candidate = str(value or "").strip()
    if not candidate or candidate not in BACKEND_REGISTRY:
        return None
    return candidate


def _read_backend_selection_from_path(path: Path) -> tuple[str | None, str | None]:
    data = _load_json_dict(path)
    jl_engine = data.get("jl_engine") if isinstance(data, dict) else None
    if not isinstance(jl_engine, dict):
        return None, None
    backends_cfg = jl_engine.get("backends")
    if not isinstance(backends_cfg, dict):
        return None, None

    default_backend = _normalize_backend_id(backends_cfg.get("default"))
    brain_backend = _normalize_backend_id(backends_cfg.get("brain_backend")) or default_backend
    tool_backend = _normalize_backend_id(backends_cfg.get("tool_backend")) or default_backend
    return brain_backend, tool_backend


def _configured_backend_selection() -> tuple[str | None, str | None]:
    env_brain = _normalize_backend_id(os.getenv("JL_ENGINE_BRAIN_BACKEND"))
    env_tool = _normalize_backend_id(os.getenv("JL_ENGINE_TOOL_BACKEND"))
    if env_brain or env_tool:
        return env_brain, env_tool

    for path in _headless_config_read_paths():
        brain_backend, tool_backend = _read_backend_selection_from_path(path)
        if brain_backend or tool_backend:
            return brain_backend, tool_backend
    return None, None


def get_runtime_mode() -> str:
    env_mode = str(os.getenv("JL_RUNTIME_MODE") or "").strip().lower()
    if env_mode in _VALID_RUNTIME_MODES:
        return env_mode
    for path in _headless_config_read_paths():
        mode = _read_runtime_mode_from_path(path)
        if mode:
            return mode
    return "local_only"


def _has_backend_credential(backend_id: str) -> bool:
    cfg = dict(BACKEND_REGISTRY.get(backend_id, {}) or {})
    provider = str(cfg.get("provider") or "").strip().lower()
    if backend_id == "openai" or provider == "openai":
        return bool(str(cfg.get("openai_api_key") or os.getenv("OPENAI_API_KEY") or "").strip())
    if backend_id == "openrouter" or provider == "openrouter":
        return bool(
            str(cfg.get("openrouter_api_key") or os.getenv("OPENROUTER_API_KEY") or "").strip()
        )
    if backend_id == "google-gemini" or provider == "google_gemini":
        return bool(
            str(
                cfg.get("google_api_key")
                or cfg.get("gemini_api_key")
                or os.getenv("GOOGLE_API_KEY")
                or os.getenv("GEMINI_API_KEY")
                or ""
            ).strip()
        )
    return False


def has_external_provider_configured() -> bool:
    return any(_has_backend_credential(backend_id) for backend_id in _EXTERNAL_BACKEND_IDS)


def get_runtime_mode_status() -> dict:
    configured_mode = get_runtime_mode()
    effective_mode = configured_mode
    fallback_reason: str | None = None

    configured_brain, configured_tool = _configured_backend_selection()
    resolved_brain = str(
        configured_brain or core_backends.brain_backend_id or _LOCAL_BACKEND_ID
    ).strip() or _LOCAL_BACKEND_ID
    resolved_tool = str(
        configured_tool or core_backends.tool_backend_id or _LOCAL_BACKEND_ID
    ).strip() or _LOCAL_BACKEND_ID

    if configured_mode == "local_only":
        resolved_brain = _LOCAL_BACKEND_ID
        resolved_tool = _LOCAL_BACKEND_ID
    elif not has_external_provider_configured():
        effective_mode = "local_only"
        fallback_reason = "missing_external_provider_config"
        resolved_brain = _LOCAL_BACKEND_ID
        resolved_tool = _LOCAL_BACKEND_ID

    return {
        "configured_mode": configured_mode,
        "effective_mode": effective_mode,
        "fallback_reason": fallback_reason,
        "brain_backend_id": resolved_brain,
        "tool_backend_id": resolved_tool,
    }


def get_effective_model_name() -> str:
    status = get_runtime_mode_status()
    backend_id = str(status.get("brain_backend_id") or _LOCAL_BACKEND_ID).strip() or _LOCAL_BACKEND_ID
    if backend_id == "openai":
        return get_openai_model()
    if backend_id == "ollama-local":
        return get_ollama_model() or get_ollama_configured_model()
    cfg = dict(BACKEND_REGISTRY.get(backend_id, {}) or {})
    for key in ("model_name", "modelName", "openrouter_model", "gemini_model"):
        text = str(cfg.get(key) or "").strip()
        if text:
            return text
    return ""


def apply_runtime_mode() -> dict:
    status = get_runtime_mode_status()
    core_backends.configure_backends(
        brain_id=str(status.get("brain_backend_id") or _LOCAL_BACKEND_ID),
        tool_id=str(status.get("tool_backend_id") or _LOCAL_BACKEND_ID),
    )
    return get_runtime_mode_status()


def _persist_ollama_model_to_path(path: Path, model_name: str) -> bool:
    if not path.exists():
        return False
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        logger.exception("[BackendController] Failed to read config '%s': %s", path, exc)
        return False
    if not isinstance(data, dict):
        return False

    jl_engine = data.setdefault("jl_engine", {})
    if not isinstance(jl_engine, dict):
        jl_engine = {}
        data["jl_engine"] = jl_engine
    backends_cfg = jl_engine.setdefault("backends", {})
    if not isinstance(backends_cfg, dict):
        backends_cfg = {}
        jl_engine["backends"] = backends_cfg

    def _is_ollama_target(config: dict, selected_backend: str) -> bool:
        target_id = str(
            config.get("id") or config.get("backend_id") or config.get("backend") or selected_backend or ""
        ).strip()
        return target_id in {"", "ollama-local"}

    brain_cfg = backends_cfg.setdefault("brain_config", {})
    if not isinstance(brain_cfg, dict):
        brain_cfg = {}
        backends_cfg["brain_config"] = brain_cfg
    selected_brain = str(backends_cfg.get("brain_backend") or backends_cfg.get("default") or "").strip()
    if _is_ollama_target(brain_cfg, selected_brain):
        brain_cfg["modelName"] = model_name
        brain_cfg["model_name"] = model_name

    tool_cfg = backends_cfg.setdefault("tool_config", {})
    if not isinstance(tool_cfg, dict):
        tool_cfg = {}
        backends_cfg["tool_config"] = tool_cfg
    selected_tool = str(backends_cfg.get("tool_backend") or backends_cfg.get("default") or "").strip()
    if _is_ollama_target(tool_cfg, selected_tool):
        tool_cfg["modelName"] = model_name
        tool_cfg["model_name"] = model_name

    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    return True


def set_ollama_model(model_name: str, persist: bool = True) -> dict:
    model = str(model_name or "").strip()
    if not model:
        raise ValueError("model_name_required")

    cfg = dict(BACKEND_REGISTRY.get("ollama-local", {}) or {})
    if not cfg:
        raise LookupError("ollama_backend_missing")

    cfg["modelName"] = model
    cfg["model_name"] = model
    BACKEND_REGISTRY["ollama-local"] = cfg

    core_backends.configure_backends(
        brain_id=core_backends.brain_backend_id,
        tool_id=core_backends.tool_backend_id,
    )

    persisted_paths: list[str] = []
    if persist:
        config_path = _headless_config_write_path()
        if _persist_ollama_model_to_path(config_path, model):
            persisted_paths.append(str(config_path))
        for path in _persist_service_config_updates({"ollama_model": model}):
            if path not in persisted_paths:
                persisted_paths.append(path)

    return {
        "backend_id": "ollama-local",
        "brain_backend_id": core_backends.brain_backend_id,
        "tool_backend_id": core_backends.tool_backend_id,
        "model_name": model,
        "base_url": get_ollama_base_url(),
        "persisted_paths": persisted_paths,
    }


def set_openai_config(
    *,
    api_key: str | None = None,
    model_name: str | None = None,
    base_url: str | None = None,
    persist: bool = True,
) -> dict:
    cfg = dict(BACKEND_REGISTRY.get("openai", {}) or {})
    if not cfg:
        raise LookupError("openai_backend_missing")

    if api_key is not None:
        cfg["openai_api_key"] = str(api_key or "").strip() or None
        if cfg["openai_api_key"]:
            os.environ["OPENAI_API_KEY"] = str(cfg["openai_api_key"])
        else:
            os.environ.pop("OPENAI_API_KEY", None)
    if model_name is not None:
        model = str(model_name or "").strip()
        cfg["openai_model"] = model or core_backends.DEFAULT_OPENAI_MODEL
        os.environ["JL_OPENAI_MODEL"] = cfg["openai_model"]
        os.environ["OPENAI_MODEL"] = cfg["openai_model"]
    if base_url is not None:
        normalized = _enforce_openai_base_url(base_url)
        cfg["openai_base_url"] = normalized
        os.environ["JL_OPENAI_BASE_URL"] = normalized
        os.environ["OPENAI_BASE_URL"] = normalized

    BACKEND_REGISTRY["openai"] = cfg

    persisted_paths: list[str] = []
    if persist:
        persisted_paths = _persist_service_config_updates(
            {
                "openai_api_key": None if api_key is not None and not str(api_key or "").strip() else cfg.get("openai_api_key"),
                "openai_model": cfg.get("openai_model"),
                "openai_base_url": cfg.get("openai_base_url"),
            }
        )

    return {
        "backend_id": "openai",
        "brain_backend_id": core_backends.brain_backend_id,
        "tool_backend_id": core_backends.tool_backend_id,
        "model_name": str(cfg.get("openai_model") or "").strip(),
        "base_url": get_openai_base_url(),
        "api_key_configured": has_openai_api_key(),
        "persisted_paths": persisted_paths,
    }


def set_active_backends(
    *,
    brain_backend_id: str | None = None,
    tool_backend_id: str | None = None,
    persist: bool = True,
) -> dict:
    resolved_brain = str(brain_backend_id or core_backends.brain_backend_id or "").strip()
    resolved_tool = str(tool_backend_id or core_backends.tool_backend_id or "").strip()
    if resolved_brain and resolved_brain not in BACKEND_REGISTRY:
        raise LookupError(f"unknown_backend:{resolved_brain}")
    if resolved_tool and resolved_tool not in BACKEND_REGISTRY:
        raise LookupError(f"unknown_backend:{resolved_tool}")
    if not resolved_brain:
        resolved_brain = str(core_backends.brain_backend_id or "").strip()
    if not resolved_tool:
        resolved_tool = str(core_backends.tool_backend_id or "").strip()

    core_backends.configure_backends(brain_id=resolved_brain, tool_id=resolved_tool)

    persisted_paths: list[str] = []
    if persist:
        config_path = _headless_config_write_path()
        if _persist_backend_selection_to_path(
            config_path,
            brain_backend_id=resolved_brain,
            tool_backend_id=resolved_tool,
        ):
            persisted_paths.append(str(config_path))

    return {
        "brain_backend_id": core_backends.brain_backend_id,
        "tool_backend_id": core_backends.tool_backend_id,
        "persisted_paths": persisted_paths,
    }


def set_runtime_mode(mode: str, persist: bool = True) -> dict:
    normalized = str(mode or "").strip().lower()
    if normalized not in _VALID_RUNTIME_MODES:
        raise ValueError(f"invalid_runtime_mode:{normalized}")

    os.environ["JL_RUNTIME_MODE"] = normalized
    persisted_paths: list[str] = []
    if persist:
        config_path = _headless_config_write_path()
        if _persist_runtime_mode_to_path(config_path, normalized):
            persisted_paths.append(str(config_path))

    if normalized == "local_only":
        set_active_backends(
            brain_backend_id=_LOCAL_BACKEND_ID,
            tool_backend_id=_LOCAL_BACKEND_ID,
            persist=persist,
        )
    else:
        apply_runtime_mode()

    status = get_runtime_mode_status()
    status["persisted_paths"] = persisted_paths
    return status


def list_backends() -> list[dict]:
    """Return available backend registry entries."""
    backends: list[dict] = []
    for backend_id, cfg in BACKEND_REGISTRY.items():
        item = _sanitize_backend_config(cfg)
        item["id"] = backend_id
        item["selected_for_brain"] = backend_id == core_backends.brain_backend_id
        item["selected_for_tool"] = backend_id == core_backends.tool_backend_id
        backends.append(item)
    return backends


def get_backend_label(backend_id: str) -> str:
    """Return label for a backend id."""
    backend = BACKEND_REGISTRY.get(backend_id)
    if not backend:
        return backend_id
    return backend.get("label") or backend.get("name") or backend_id


def configure_backends(brain_id: str | None = None, tool_id: str | None = None) -> None:
    core_backends.configure_backends(brain_id=brain_id, tool_id=tool_id)


def set_brain_backend_id(backend_id: str) -> None:
    core_backends.set_brain_backend_id(backend_id)


def set_tool_backend_id(backend_id: str) -> None:
    core_backends.set_tool_backend_id(backend_id)


def get_brain_backend_id() -> str:
    return core_backends.brain_backend_id


def get_tool_backend_id() -> str:
    return core_backends.tool_backend_id


def apply_backend_overrides(backends_cfg: dict) -> None:
    core_backends.apply_backend_overrides(backends_cfg)


def get_brain_backend():
    return core_backends.get_brain_backend()


def get_backend(backend_id: str | None = None, overrides: dict | None = None):
    return core_backends.get_backend(backend_id=backend_id, overrides=overrides)


try:
    apply_runtime_mode()
except Exception as exc:  # pragma: no cover - defensive import-time sync
    logger.exception("[BackendController] Failed to apply runtime mode on import: %s", exc)
