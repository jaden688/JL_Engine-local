from __future__ import annotations

import jl_engine_core.engine_core as engine_core_module
from jl_engine_core.engine_core import JLEngineCore


class RecordingBackend:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    def generate(self, messages, options=None, timeout=None):
        self.calls.append(
            {
                "messages": list(messages or []),
                "options": dict(options or {}),
                "timeout": timeout,
            }
        )
        return "Synthetic reply.", {"backend": "recording"}


def _new_engine(monkeypatch) -> JLEngineCore:
    monkeypatch.setenv("JL_TQA_INTERNAL_LOOP", "0")
    engine = JLEngineCore()
    engine.supervisor_enabled = False
    engine.supervisor_gating = False
    engine.supervisor_postprocess = False
    engine._update_dynamic_aperture = lambda: None
    return engine


def test_game_npc_mode_injects_reactivity_overlay(monkeypatch):
    backend = RecordingBackend()
    monkeypatch.setattr(engine_core_module, "get_brain_backend", lambda: backend)
    monkeypatch.setenv("JL_GAME_NPC_MODE", "1")
    engine = _new_engine(monkeypatch)

    _reply, telemetry, _feedback = engine.generate_response(
        "The gremlin got his hand bitten off and started screaming.",
        context={"suppress_memory_write": True, "suppress_feedback_log": True},
    )

    system_message = backend.calls[-1]["messages"][0]["content"]
    assert "GAME NPC REACTIVITY MODE:" in system_message
    assert "Scene threat cues:" in system_message
    assert telemetry["game_npc_mode_enabled"] is True
    assert telemetry["game_npc_scene_cues"]
    assert telemetry["aperture_state"]["emotion"] == "threat_spike"
    assert telemetry["aperture_state"]["overload_level"] > 0.0
    assert telemetry["engine_status"]["game_npc_mode"] is True


def test_game_npc_mode_stays_out_when_disabled(monkeypatch):
    backend = RecordingBackend()
    monkeypatch.setattr(engine_core_module, "get_brain_backend", lambda: backend)
    monkeypatch.delenv("JL_GAME_NPC_MODE", raising=False)
    engine = _new_engine(monkeypatch)

    engine.generate_response(
        "The gremlin got his hand bitten off and started screaming.",
        context={"suppress_memory_write": True, "suppress_feedback_log": True},
    )

    system_message = backend.calls[-1]["messages"][0]["content"]
    assert "GAME NPC REACTIVITY MODE:" not in system_message
