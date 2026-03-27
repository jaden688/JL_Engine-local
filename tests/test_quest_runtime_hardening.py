from __future__ import annotations

from jl_platform.core import quest_runtime as quest_runtime_module


def test_quest_runtime_uses_safe_interpreter_defaults(monkeypatch):
    runtime = quest_runtime_module.FatQuestRuntime()
    captured: dict[str, object] = {}

    class FakeEngine:
        def set_agent(self, agent_name: str) -> None:
            self.agent_name = agent_name

    class FakeForge:
        pass

    class FakeInterpreterSession:
        def __init__(self, **kwargs):
            captured.update(kwargs)
            self.engine = kwargs.get("engine")
            self.history = []

    monkeypatch.delenv("JL_INTERPRETER_ALLOW_DIRECT_ACTION_FALLBACK", raising=False)
    monkeypatch.delenv("JL_LOCAL_UNSAFE_TOOLS", raising=False)
    monkeypatch.setattr(quest_runtime_module, "JLEngineCore", FakeEngine)
    monkeypatch.setattr(quest_runtime_module, "PrivilegedMemoryForge", FakeForge)
    monkeypatch.setattr(quest_runtime_module, "InterpreterSession", FakeInterpreterSession)
    monkeypatch.setattr(runtime, "_apply_runtime_backend_mode", lambda: None)
    monkeypatch.setattr(runtime, "_activate_engine", lambda engine: None)
    monkeypatch.setattr(
        runtime,
        "_resolve_agent_selection_from_name",
        lambda agent_name: {
            "lane": "fat_agent",
            "child": agent_name,
            "agent_name": agent_name,
            "generated_instance_id": None,
        },
    )
    monkeypatch.setattr(runtime, "_set_agent_selection_state", lambda *args, **kwargs: None)

    agent = runtime.ensure_agent("agent-1", agent_name="SparkByte")

    print(f"\n\nCAPTURED IS: {captured}\n\n")

    assert agent.agent == "SparkByte"
    assert captured["allow_unsafe_tools"] is False
    assert captured["allow_direct_action_fallback"] is False
