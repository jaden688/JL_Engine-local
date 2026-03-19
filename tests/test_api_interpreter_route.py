from __future__ import annotations

from fastapi.testclient import TestClient

from jl_platform.services.api import main as api_main
from jl_platform.services.api.schemas import InterpreterRequest


def test_interpreter_run_defaults_to_safe_direct_action_behavior(monkeypatch):
    captured: dict[str, object] = {}

    class FakeSession:
        def __init__(self, **kwargs):
            captured.update(kwargs)

        def run(self, message: str) -> dict:
            return {"status": "ok", "final": message, "tool_trace": [], "telemetry": {}}

    monkeypatch.delenv("JL_INTERPRETER_ALLOW_DIRECT_ACTION_FALLBACK", raising=False)
    monkeypatch.setattr(api_main, "InterpreterSession", FakeSession)
    monkeypatch.setattr(api_main, "_INTERPRETER_SESSIONS", {})

    result = api_main.interpreter_run(InterpreterRequest(message="hello", session_id="route-test"))

    assert result["status"] == "ok"
    assert result["session_id"] == "route-test"
    assert captured["allow_unsafe_tools"] is None
    assert captured["allow_direct_action_fallback"] is False


def test_interpreter_run_respects_direct_action_fallback_env(monkeypatch):
    captured: dict[str, object] = {}

    class FakeSession:
        def __init__(self, **kwargs):
            captured.update(kwargs)

        def run(self, message: str) -> dict:
            return {"status": "ok", "final": message, "tool_trace": [], "telemetry": {}}

    monkeypatch.setenv("JL_INTERPRETER_ALLOW_DIRECT_ACTION_FALLBACK", "1")
    monkeypatch.setattr(api_main, "InterpreterSession", FakeSession)
    monkeypatch.setattr(api_main, "_INTERPRETER_SESSIONS", {})

    result = api_main.interpreter_run(InterpreterRequest(message="hello", session_id="route-test-2"))

    assert result["status"] == "ok"
    assert captured["allow_direct_action_fallback"] is True


def test_cc_run_route_uses_commissioner_backend(monkeypatch):
    captured: dict[str, object] = {}

    def fake_run_cc_command(payload: dict) -> dict:
        captured.update(payload)
        return {"stdout": "ok", "stderr": "", "returncode": 0, "ok": True, "duration_ms": 1.0}

    monkeypatch.setattr(api_main, "run_cc_command", fake_run_cc_command)

    client = TestClient(api_main.app)
    response = client.post("/tools/cc-run", json={"command": "dir", "cwd": "."})

    assert response.status_code == 200
    assert response.json()["ok"] is True
    assert captured["command"] == "dir"
    assert captured["cwd"] == "."
