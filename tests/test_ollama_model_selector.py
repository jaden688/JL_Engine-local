from __future__ import annotations

import json

import pytest
from fastapi import HTTPException

from jl_platform.controllers import backend_controller
from jl_platform.services.api import main as api_main


def test_set_ollama_model_updates_registry_and_persists_canonical_headless_config(tmp_path, monkeypatch):
    path_one = tmp_path / "JLframe_Engine_Framework.headless.json"
    path_two = tmp_path / "config" / "JLframe_Engine_Framework.headless.json"
    service_path = tmp_path / "gemini_config.json"
    path_two.parent.mkdir(parents=True, exist_ok=True)

    seed = {
        "jl_engine": {
            "backends": {
                "brain_config": {
                    "modelName": "dolphin3:latest",
                    "model_name": "dolphin3:latest",
                }
            }
        }
    }
    path_one.write_text(json.dumps(seed), encoding="utf-8")
    path_two.write_text(json.dumps(seed), encoding="utf-8")
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
    configure_calls: list[tuple[str, str]] = []

    monkeypatch.setattr(backend_controller, "BACKEND_REGISTRY", registry)
    monkeypatch.setattr(backend_controller, "_CANONICAL_HEADLESS_CONFIG_PATH", path_one)
    monkeypatch.setattr(backend_controller, "_LEGACY_HEADLESS_CONFIG_PATH", path_two)
    monkeypatch.setattr(backend_controller, "_SERVICE_CONFIG_PATH", service_path)
    monkeypatch.setattr(backend_controller.core_backends, "brain_backend_id", "ollama-local")
    monkeypatch.setattr(backend_controller.core_backends, "tool_backend_id", "ollama-local")
    monkeypatch.setattr(
        backend_controller.core_backends,
        "configure_backends",
        lambda brain_id=None, tool_id=None: configure_calls.append((brain_id, tool_id)),
    )

    result = backend_controller.set_ollama_model("qwen3-vl:4b", persist=True)

    assert registry["ollama-local"]["modelName"] == "qwen3-vl:4b"
    assert registry["ollama-local"]["model_name"] == "qwen3-vl:4b"
    assert configure_calls == [("ollama-local", "ollama-local")]
    assert result["model_name"] == "qwen3-vl:4b"
    assert set(result["persisted_paths"]) == {str(path_one), str(service_path)}

    saved_one = json.loads(path_one.read_text(encoding="utf-8"))
    brain_config = saved_one["jl_engine"]["backends"]["brain_config"]
    assert brain_config["modelName"] == "qwen3-vl:4b"
    assert brain_config["model_name"] == "qwen3-vl:4b"

    saved_two = json.loads(path_two.read_text(encoding="utf-8"))
    legacy_brain_config = saved_two["jl_engine"]["backends"]["brain_config"]
    assert legacy_brain_config["modelName"] == "dolphin3:latest"
    assert legacy_brain_config["model_name"] == "dolphin3:latest"

    service_saved = json.loads(service_path.read_text(encoding="utf-8"))
    assert service_saved["ollama_model"] == "qwen3-vl:4b"


def test_ollama_settings_reports_current_model_and_inventory(monkeypatch):
    monkeypatch.setattr(api_main.backend_controller, "get_brain_backend_id", lambda: "ollama-local")
    monkeypatch.setattr(api_main.backend_controller, "get_tool_backend_id", lambda: "ollama-local")
    monkeypatch.setattr(api_main.backend_controller, "get_ollama_base_url", lambda: "http://127.0.0.1:11434")
    monkeypatch.setattr(api_main.backend_controller, "get_ollama_model", lambda: "qwen3-vl:4b")
    monkeypatch.setattr(
        api_main.backend_controller,
        "list_ollama_models",
        lambda: [{"name": "qwen3-vl:4b", "size_mb": 2800.0}],
    )

    result = api_main.ollama_settings()

    assert result["status"] == "ok"
    assert result["current_model"] == "qwen3-vl:4b"
    assert result["models"][0]["name"] == "qwen3-vl:4b"


def test_ollama_set_model_rejects_unknown_installed_model(monkeypatch):
    monkeypatch.setattr(
        api_main.backend_controller,
        "list_ollama_models",
        lambda: [{"name": "dolphin3:latest"}],
    )

    with pytest.raises(HTTPException) as exc:
        api_main.ollama_set_model(api_main.OllamaModelSelectionRequest(model_name="qwen3-vl:4b"))

    assert exc.value.status_code == 400
    assert exc.value.detail == "model_not_installed:qwen3-vl:4b"


def test_ollama_set_model_returns_updated_selection(monkeypatch):
    installed = [
        {"name": "dolphin3:latest"},
        {"name": "qwen3-vl:4b"},
    ]
    monkeypatch.setattr(api_main.backend_controller, "list_ollama_models", lambda: installed)
    monkeypatch.setattr(
        api_main.backend_controller,
        "set_ollama_model",
        lambda model_name, persist=True: {
            "backend_id": "ollama-local",
            "brain_backend_id": "ollama-local",
            "tool_backend_id": "ollama-local",
            "model_name": model_name,
            "base_url": "http://127.0.0.1:11434",
            "persisted_paths": ["jl_engine_core/data/config/JLframe_Engine_Framework.headless.json"],
        },
    )

    result = api_main.ollama_set_model(api_main.OllamaModelSelectionRequest(model_name="qwen3-vl:4b"))

    assert result["status"] == "ok"
    assert result["model_name"] == "qwen3-vl:4b"
    assert result["models"] == installed
