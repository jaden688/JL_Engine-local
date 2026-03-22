from __future__ import annotations

import sys
from pathlib import Path

from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))

for module_name in list(sys.modules):
    if module_name.startswith(("jl_platform", "jl_engine_core")):
        del sys.modules[module_name]

from jl_platform.services.api import main as api_main
from jl_platform.services.api.schemas import InterpreterRequest


def test_interpreter_run_defaults_to_direct_action_fallback_disabled(monkeypatch):
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


def test_interpreter_stream_route_emits_sse_events(monkeypatch):
    class FakeSession:
        def __init__(self, **kwargs):
            pass

        def stream_run(self, message: str, context: dict | None = None):
            yield {"type": "run_started", "message": message}
            yield {"type": "tool_call_started", "tool": "py_exec_stream"}
            yield {
                "type": "turn_result",
                "result": {
                    "status": "ok",
                    "final": "streamed result",
                    "reply": "streamed result",
                    "tool_trace": [],
                    "telemetry": {},
                },
            }

    monkeypatch.setattr(api_main, "InterpreterSession", FakeSession)
    monkeypatch.setattr(api_main, "_INTERPRETER_SESSIONS", {})

    client = TestClient(api_main.app)
    response = client.post(
        "/interpreter/stream",
        json={"message": "hello", "session_id": "stream-route"},
    )

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    assert "event: run_started" in response.text
    assert "event: turn_result" in response.text
    assert "streamed result" in response.text


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


def test_quest_chat_stream_route_emits_sse_events(monkeypatch):
    captured: dict[str, object] = {}

    def fake_stream_chat(
        *,
        agent_id: str,
        message: str,
        agent: str | None = None,
        lane: str | None = None,
        child: str | None = None,
        new_instance: bool = False,
        context: dict | None = None,
        execution_mode: str = "auto",
        return_trace: bool = True,
        allow_clone: bool = True,
    ):
        captured["execution_mode"] = execution_mode
        captured["context"] = dict(context or {})
        yield {"type": "quest_chat_started", "agent_id": agent_id, "agent": agent}
        yield {"type": "tool_output", "tool": "run_cc_command", "stream": "stdout", "chunk": "hello\n"}
        yield {
            "type": "turn_result",
            "result": {
                "status": "ok",
                "reply": "quest stream done",
                "tool_trace": [],
                "telemetry": {},
            },
        }

    monkeypatch.setattr(api_main._QUEST_RUNTIME, "stream_chat", fake_stream_chat)

    client = TestClient(api_main.app)
    response = client.post("/quest/chat/stream", json={"message": "hello"})

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    assert "event: quest_chat_started" in response.text
    assert "event: turn_result" in response.text
    assert "quest stream done" in response.text
    assert captured["execution_mode"] == "execute"
    assert captured["context"]["tooling_mode"] == "forge_first"
    assert captured["context"]["external_tool_fallback"] is True


def test_quest_chat_rejects_invalid_tooling_mode():
    client = TestClient(api_main.app)
    response = client.post(
        "/quest/chat",
        json={
            "message": "hello",
            "context": {"tooling_mode": "invalid_mode"},
        },
    )

    assert response.status_code == 400
    assert "invalid_tooling_mode" in str(response.json().get("detail") or "")


def test_quest_chat_rejects_invalid_external_fallback_value():
    client = TestClient(api_main.app)
    response = client.post(
        "/quest/chat",
        json={
            "message": "hello",
            "context": {"external_tool_fallback": "maybe"},
        },
    )

    assert response.status_code == 400
    assert "invalid_boolean_value" in str(response.json().get("detail") or "")
