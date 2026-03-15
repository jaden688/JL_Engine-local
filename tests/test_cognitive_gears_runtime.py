from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))

from jl_engine_core import engine_core as engine_core_module
from jl_engine_core.cognitive_gears import select_active_runtime_gear
from jl_engine_core.cognitive_modes import CognitiveModeState


def _sparkbyte_gears() -> dict:
    return {
        "cognitive_gears": {
            "preferred_gears": ["LITE_REASONING", "EXPRESSIVE_SYNTH", "TASK_FLOW"],
            "fallback_gears": ["RAW_LOGIC", "STEPWISE"],
        }
    }


def test_select_active_runtime_gear_prefers_creative_path() -> None:
    selection = select_active_runtime_gear(
        _sparkbyte_gears(),
        user_text="brainstorm a stylized concept riff for this feature",
    )

    assert selection["active_label"] == "EXPRESSIVE_SYNTH"
    assert selection["runtime_gear"] == "cvt"
    assert selection["reason"] == "creative"


def test_select_active_runtime_gear_prefers_precision_fallback() -> None:
    selection = select_active_runtime_gear(
        _sparkbyte_gears(),
        user_text="this is safety-critical and needs exact debugging",
        context={"risk_level_override": "high"},
    )

    assert selection["active_label"] == "RAW_LOGIC"
    assert selection["runtime_gear"] == "worm"
    assert selection["reason"] == "precision"


def test_engine_uses_resolved_runtime_gear(monkeypatch) -> None:
    class StubBackend:
        def generate(self, messages, options=None, timeout=None):
            return "Stub reply", {"stub": True}

    monkeypatch.setenv("JL_TQA_INTERNAL_LOOP", "0")
    monkeypatch.setattr(engine_core_module, "get_brain_backend", lambda: StubBackend())

    engine = engine_core_module.JLEngineCore()
    engine.feedback_enabled = False
    engine.set_agent("SparkByte")

    captured: dict[str, str] = {}

    def fake_select_modes(*, gear, focus_level, overload_level):
        captured["gear"] = gear
        return CognitiveModeState(active_modes={"balanced": 0.7, "expansion": 0.3})

    monkeypatch.setattr(engine.cognitive_selector, "select_modes", fake_select_modes)
    monkeypatch.setattr(engine.cognitive_selector, "get_dominant_mode", lambda: "balanced")

    _reply, telemetry, _feedback = engine.generate_response(
        "brainstorm a stylized concept riff for this feature"
    )

    assert captured["gear"] == "cvt"
    assert telemetry["cognitive_gear"]["active_label"] == "EXPRESSIVE_SYNTH"
    assert telemetry["cognitive_gear"]["runtime_gear"] == "cvt"
    assert telemetry["cognitive_modes"] == {"balanced": 0.7, "expansion": 0.3}
