from __future__ import annotations

import json

from jl_engine_core import backends as core_backends
from jl_platform.controllers import backend_controller
from jl_platform.services.api import main as api_main


def test_get_ollama_model_prefers_installed_model_when_config_is_stale(monkeypatch):
    registry = {
        "ollama-local": {
            "id": "ollama-local",
            "provider": "ollama",
            "baseUrl": "http://127.0.0.1:11434",
            "modelName": "dolphin3:latest",
            "model_name": "dolphin3:latest",
        }
    }
    monkeypatch.setattr(backend_controller, "BACKEND_REGISTRY", registry)
    monkeypatch.setattr(
        backend_controller.core_backends,
        "resolve_ollama_model_name",
        lambda preferred, base_url=None, allow_unavailable=True, fallback_to_first_installed=True: "qwen3:4b",
    )

    assert backend_controller.get_ollama_model() == "qwen3:4b"


def test_get_effective_model_name_prefers_resolved_local_model(monkeypatch):
    monkeypatch.setattr(
        backend_controller,
        "get_runtime_mode_status",
        lambda: {
            "configured_mode": "local_only",
            "effective_mode": "local_only",
            "fallback_reason": None,
            "brain_backend_id": "ollama-local",
            "tool_backend_id": "ollama-local",
        },
    )
    monkeypatch.setattr(backend_controller, "get_ollama_model", lambda: "gemma3:4b")
    monkeypatch.setattr(backend_controller, "get_ollama_configured_model", lambda: "dolphin3:latest")

    assert backend_controller.get_effective_model_name() == "gemma3:4b"


def test_set_active_backends_persists_selection_without_secrets(tmp_path, monkeypatch):
    config_path = tmp_path / "JLframe_Engine_Framework.headless.json"
    config_path.write_text("{}", encoding="utf-8")

    registry = {
        "ollama-local": {
            "id": "ollama-local",
            "provider": "ollama",
            "baseUrl": "http://127.0.0.1:11434",
            "modelName": "qwen3:4b",
            "model_name": "qwen3:4b",
        },
        "openai": {
            "id": "openai",
            "provider": "openai",
            "openai_model": "gpt-5.2",
            "openai_base_url": "https://api.openai.com/v1",
            "openai_api_key": "sk-test-secret",
        },
    }

    monkeypatch.setattr(backend_controller, "BACKEND_REGISTRY", registry)
    monkeypatch.setattr(backend_controller, "_CANONICAL_HEADLESS_CONFIG_PATH", config_path)
    monkeypatch.setattr(backend_controller, "_LEGACY_HEADLESS_CONFIG_PATH", tmp_path / "legacy.json")

    def fake_configure_backends(brain_id=None, tool_id=None):
        if brain_id:
            backend_controller.core_backends.brain_backend_id = brain_id
        if tool_id:
            backend_controller.core_backends.tool_backend_id = tool_id

    monkeypatch.setattr(backend_controller.core_backends, "brain_backend_id", "ollama-local")
    monkeypatch.setattr(backend_controller.core_backends, "tool_backend_id", "ollama-local")
    monkeypatch.setattr(backend_controller.core_backends, "configure_backends", fake_configure_backends)

    result = backend_controller.set_active_backends(
        brain_backend_id="openai",
        tool_backend_id="ollama-local",
        persist=True,
    )

    assert result["brain_backend_id"] == "openai"
    assert result["tool_backend_id"] == "ollama-local"

    saved = json.loads(config_path.read_text(encoding="utf-8"))
    backends_cfg = saved["jl_engine"]["backends"]
    assert backends_cfg["brain_backend"] == "openai"
    assert backends_cfg["tool_backend"] == "ollama-local"
    assert backends_cfg["brain_config"]["openai_model"] == "gpt-5.2"
    assert "openai_api_key" not in backends_cfg["brain_config"]


def test_set_ollama_model_persists_service_and_headless_config(tmp_path, monkeypatch):
    config_path = tmp_path / "JLframe_Engine_Framework.headless.json"
    config_path.write_text("{}", encoding="utf-8")
    service_path = tmp_path / "gemini_config.json"
    service_path.write_text("{}", encoding="utf-8")

    registry = {
        "ollama-local": {
            "id": "ollama-local",
            "provider": "ollama",
            "baseUrl": "http://127.0.0.1:11434",
            "modelName": "dolphin3:latest",
            "model_name": "dolphin3:latest",
        }
    }

    monkeypatch.setattr(backend_controller, "BACKEND_REGISTRY", registry)
    monkeypatch.setattr(backend_controller, "_CANONICAL_HEADLESS_CONFIG_PATH", config_path)
    monkeypatch.setattr(backend_controller, "_LEGACY_HEADLESS_CONFIG_PATH", tmp_path / "legacy.json")
    monkeypatch.setattr(backend_controller, "_SERVICE_CONFIG_PATH", service_path)

    def fake_configure_backends(brain_id=None, tool_id=None):
        if brain_id:
            backend_controller.core_backends.brain_backend_id = brain_id
        if tool_id:
            backend_controller.core_backends.tool_backend_id = tool_id

    monkeypatch.setattr(backend_controller.core_backends, "brain_backend_id", "ollama-local")
    monkeypatch.setattr(backend_controller.core_backends, "tool_backend_id", "ollama-local")
    monkeypatch.setattr(backend_controller.core_backends, "configure_backends", fake_configure_backends)

    result = backend_controller.set_ollama_model("gemma3:4b", persist=True)

    assert result["model_name"] == "gemma3:4b"
    saved = json.loads(config_path.read_text(encoding="utf-8"))
    assert saved["jl_engine"]["backends"]["brain_config"]["modelName"] == "gemma3:4b"
    assert saved["jl_engine"]["backends"]["tool_config"]["modelName"] == "gemma3:4b"
    service_saved = json.loads(service_path.read_text(encoding="utf-8"))
    assert service_saved["ollama_model"] == "gemma3:4b"


def test_apply_backend_overrides_merges_tool_config(monkeypatch):
    registry = {
        "custom_http": {
            "id": "custom_http",
            "label": "Custom HTTP Backend",
            "provider": "custom_http",
        }
    }
    monkeypatch.setattr(core_backends, "BACKEND_REGISTRY", registry)

    core_backends.apply_backend_overrides(
        {
            "tool_config": {
                "id": "openai",
                "provider": "openai",
                "openai_model": "gpt-5.2",
            }
        }
    )

    assert core_backends.BACKEND_REGISTRY["openai"]["provider"] == "openai"
    assert core_backends.BACKEND_REGISTRY["openai"]["openai_model"] == "gpt-5.2"


def test_openai_backend_generates_text_from_response_payload(monkeypatch):
    captured: dict = {}

    class DummyResponse:
        def raise_for_status(self):
            return None

        def json(self):
            return {
                "id": "resp_123",
                "model": "gpt-5.2",
                "output": [
                    {
                        "type": "message",
                        "content": [
                            {"type": "output_text", "text": "sparkbyte says hi"},
                        ],
                    }
                ],
            }

    def fake_post(url, headers=None, json=None, timeout=None):
        captured["url"] = url
        captured["headers"] = headers
        captured["json"] = json
        captured["timeout"] = timeout
        return DummyResponse()

    monkeypatch.setattr(core_backends.requests, "post", fake_post)

    backend = core_backends.OpenAIBackend(
        {
            "openai_api_key": "sk-test",
            "openai_model": "gpt-5.2",
            "openai_base_url": "https://api.openai.com/v1",
        }
    )
    text, meta = backend.generate(
        [{"role": "user", "content": "Say hello"}],
        options={"temperature": 0.2},
    )

    assert captured["url"] == "https://api.openai.com/v1/responses"
    assert captured["json"]["model"] == "gpt-5.2"
    assert captured["json"]["input"][0]["role"] == "user"
    assert text == "sparkbyte says hi"
    assert meta["backend"] == "openai"


def test_openai_settings_endpoint_reports_backend_state(monkeypatch):
    monkeypatch.setattr(api_main.backend_controller, "get_brain_backend_id", lambda: "openai")
    monkeypatch.setattr(api_main.backend_controller, "get_tool_backend_id", lambda: "ollama-local")
    monkeypatch.setattr(
        api_main.backend_controller,
        "get_openai_base_url",
        lambda: "https://api.openai.com/v1",
    )
    monkeypatch.setattr(api_main.backend_controller, "get_openai_model", lambda: "gpt-5.2")
    monkeypatch.setattr(api_main.backend_controller, "has_openai_api_key", lambda: True)

    result = api_main.openai_settings()

    assert result["backend_id"] == "openai"
    assert result["brain_backend_id"] == "openai"
    assert result["current_model"] == "gpt-5.2"
    assert result["api_key_configured"] is True


def test_runtime_mode_defaults_to_local_only(tmp_path, monkeypatch):
    config_path = tmp_path / "JLframe_Engine_Framework.headless.json"
    config_path.write_text("{}", encoding="utf-8")

    monkeypatch.setattr(backend_controller, "_CANONICAL_HEADLESS_CONFIG_PATH", config_path)
    monkeypatch.setattr(backend_controller, "_LEGACY_HEADLESS_CONFIG_PATH", tmp_path / "legacy.json")
    monkeypatch.delenv("JL_RUNTIME_MODE", raising=False)

    status = backend_controller.get_runtime_mode_status()

    assert status["configured_mode"] == "local_only"
    assert status["effective_mode"] == "local_only"
    assert status["brain_backend_id"] == "ollama-local"


def test_runtime_mode_hybrid_without_provider_falls_back_to_local(tmp_path, monkeypatch):
    config_path = tmp_path / "JLframe_Engine_Framework.headless.json"
    config_path.write_text("{}", encoding="utf-8")

    registry = {
        "ollama-local": {
            "id": "ollama-local",
            "provider": "ollama",
            "baseUrl": "http://127.0.0.1:11434",
            "modelName": "qwen3:4b",
            "model_name": "qwen3:4b",
        },
        "openai": {
            "id": "openai",
            "provider": "openai",
            "openai_model": "gpt-5.2",
            "openai_base_url": "https://api.openai.com/v1",
            "openai_api_key": "",
        },
    }

    monkeypatch.setattr(backend_controller, "BACKEND_REGISTRY", registry)
    monkeypatch.setattr(backend_controller, "_CANONICAL_HEADLESS_CONFIG_PATH", config_path)
    monkeypatch.setattr(backend_controller, "_LEGACY_HEADLESS_CONFIG_PATH", tmp_path / "legacy.json")
    monkeypatch.setattr(backend_controller.core_backends, "brain_backend_id", "openai")
    monkeypatch.setattr(backend_controller.core_backends, "tool_backend_id", "ollama-local")

    recorded: dict[str, str] = {}

    def fake_configure_backends(brain_id=None, tool_id=None):
        recorded["brain_backend_id"] = brain_id or ""
        recorded["tool_backend_id"] = tool_id or ""
        backend_controller.core_backends.brain_backend_id = brain_id
        backend_controller.core_backends.tool_backend_id = tool_id

    monkeypatch.setattr(backend_controller.core_backends, "configure_backends", fake_configure_backends)

    result = backend_controller.set_runtime_mode("hybrid", persist=True)

    saved = json.loads(config_path.read_text(encoding="utf-8"))

    assert result["configured_mode"] == "hybrid"
    assert result["effective_mode"] == "local_only"
    assert result["fallback_reason"] == "missing_external_provider_config"
    assert recorded == {"brain_backend_id": "ollama-local", "tool_backend_id": "ollama-local"}
    assert saved["jl_engine"]["runtime_mode"] == "hybrid"


def test_runtime_mode_uses_persisted_backend_selection_when_provider_available(tmp_path, monkeypatch):
    config_path = tmp_path / "JLframe_Engine_Framework.headless.json"
    config_path.write_text(
        json.dumps(
            {
                "jl_engine": {
                    "runtime_mode": "hybrid",
                    "backends": {
                        "default": "openai",
                        "brain_backend": "openai",
                        "tool_backend": "openai",
                    },
                }
            }
        ),
        encoding="utf-8",
    )

    registry = {
        "ollama-local": {
            "id": "ollama-local",
            "provider": "ollama",
            "baseUrl": "http://127.0.0.1:11434",
            "modelName": "qwen3:4b",
            "model_name": "qwen3:4b",
        },
        "openai": {
            "id": "openai",
            "provider": "openai",
            "openai_model": "grok-3",
            "openai_base_url": "https://api.x.ai/v1",
            "openai_api_key": "xai-test",
        },
    }

    monkeypatch.setattr(backend_controller, "BACKEND_REGISTRY", registry)
    monkeypatch.setattr(backend_controller, "_CANONICAL_HEADLESS_CONFIG_PATH", config_path)
    monkeypatch.setattr(backend_controller, "_LEGACY_HEADLESS_CONFIG_PATH", tmp_path / "legacy.json")
    monkeypatch.delenv("JL_RUNTIME_MODE", raising=False)
    monkeypatch.delenv("JL_ENGINE_BRAIN_BACKEND", raising=False)
    monkeypatch.delenv("JL_ENGINE_TOOL_BACKEND", raising=False)
    monkeypatch.setattr(backend_controller.core_backends, "brain_backend_id", "ollama-local")
    monkeypatch.setattr(backend_controller.core_backends, "tool_backend_id", "ollama-local")

    status = backend_controller.get_runtime_mode_status()

    assert status["configured_mode"] == "hybrid"
    assert status["effective_mode"] == "hybrid"
    assert status["brain_backend_id"] == "openai"
    assert status["tool_backend_id"] == "openai"


def test_ollama_model_allowed_filters_large_models():
    assert core_backends.ollama_model_allowed("gemma3:4b") is True
    assert core_backends.ollama_model_allowed("llama3.1:70b") is False
    assert core_backends.ollama_model_allowed("") is False


def test_ensure_ollama_server_autostarts_and_recovers(monkeypatch):
    attempts = {"get": 0, "start": 0}

    class _DummyResponse:
        status_code = 200

    def fake_get(_url, timeout=None):
        attempts["get"] += 1
        if attempts["get"] < 3:
            raise core_backends.RequestException("down")
        return _DummyResponse()

    def fake_start():
        attempts["start"] += 1
        return True

    monkeypatch.setattr(core_backends.requests, "get", fake_get)
    monkeypatch.setattr(core_backends, "_start_ollama_server_process", fake_start)
    monkeypatch.setattr(core_backends.time, "sleep", lambda _seconds: None)
    monkeypatch.setattr(core_backends, "_OLLAMA_AUTOSTART_ATTEMPTS", set())

    ready = core_backends.ensure_ollama_server(
        "http://127.0.0.1:11434",
        autostart=True,
        wait_timeout=1.0,
        poll_interval=0.1,
    )

    assert ready is True
    assert attempts["start"] == 1
