from __future__ import annotations

import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
for module_name in list(sys.modules):
    if module_name == "jl_engine_core" or module_name.startswith("jl_engine_core."):
        del sys.modules[module_name]

from jl_engine_core.engine_core import JLEngineCore
from jl_engine_core.temporal_field import (
    TemporalFieldController,
    WarmLaneCPUChannel,
    apply_temporal_sampling_bias,
)


def _simple_palette() -> list[dict]:
    return [
        {
            "id": "playful_intrigue",
            "label": "playful intrigue",
            "style": "light teasing curiosity",
            "score_range": [0.2, 0.8],
            "intensity": 0.5,
            "sentiment": "positive",
            "sampling_bias": {"temperature": 0.03, "top_p": 0.02},
        },
        {
            "id": "focused_support",
            "label": "focused support",
            "style": "calm, concise",
            "score_range": [0.1, 0.7],
            "intensity": 0.35,
            "sentiment": "neutral",
            "sampling_bias": {"temperature": -0.04, "top_p": -0.03},
        },
    ]


def _simple_wheel() -> dict:
    return {
        "baseline_root": "playful_energy",
        "baseline_family": "playful",
        "roots": [
            {
                "id": "playful_energy",
                "label": "playful energy",
                "default_weight": 0.75,
                "families": [
                    {
                        "id": "playful",
                        "label": "playful spark",
                        "default_weight": 0.75,
                        "repeat_penalty": 0.2,
                        "cooldown_turns": 2,
                        "sensation": {"id": "buzzy", "label": "buzzy lightness"},
                        "scenes": [
                            {
                                "id": "banter",
                                "label": "curious banter",
                                "default_weight": 0.75,
                                "facet_ids": ["playful_intrigue"],
                            }
                        ],
                    }
                ],
            },
            {
                "id": "focused_drive",
                "label": "focused drive",
                "default_weight": 0.7,
                "families": [
                    {
                        "id": "focused",
                        "label": "focused assist",
                        "default_weight": 0.72,
                        "repeat_penalty": 0.15,
                        "cooldown_turns": 1,
                        "sensation": {"id": "tight", "label": "tight alignment"},
                        "scenes": [
                            {
                                "id": "guidance",
                                "label": "calm guidance",
                                "default_weight": 0.76,
                                "facet_ids": ["focused_support"],
                            }
                        ],
                    }
                ],
            },
        ],
    }


class RecordingBackend:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    def generate(self, messages, options=None, timeout=None):
        self.calls.append(
            {"messages": messages, "options": dict(options or {}), "timeout": timeout}
        )
        return "Temporal field reply.", {"backend": "fake"}


def test_temporal_field_probe_reports_backend_keys():
    backend = WarmLaneCPUChannel()
    status = backend.probe_backend()

    assert status["backend_name"] == "cpu_shim"
    assert "warm_lane_detected" in status
    assert "status" in status
    assert "reason" in status


def test_temporal_field_controller_ticks_live_and_stops():
    controller = TemporalFieldController(interval_seconds=0.05)
    controller.set_ontology("SparkByte", _simple_wheel(), _simple_palette())
    controller.start_loop()
    try:
        first = controller.sample_field()
        time.sleep(0.18)
        second = controller.sample_field()
        assert second["tick_count"] > first["tick_count"]
        assert second["field_age_seconds"] > first["field_age_seconds"]
        assert controller.get_loop_status()["running"] is True
    finally:
        controller.stop_loop()

    assert controller.get_loop_status()["running"] is False


def test_temporal_field_start_loop_primes_first_scene():
    controller = TemporalFieldController(interval_seconds=0.05)
    controller.set_ontology("SparkByte", _simple_wheel(), _simple_palette())
    controller.start_loop()
    try:
        sample = controller.sample_field()
    finally:
        controller.stop_loop()

    assert sample["tick_count"] >= 1
    assert sample["root_label"]
    assert sample["scene_label"]
    assert sample["sampling_ready"] is False


def test_temporal_field_controllers_keep_separate_state():
    controller_a = TemporalFieldController(interval_seconds=0.05)
    controller_b = TemporalFieldController(interval_seconds=0.05)
    try:
        controller_a.set_ontology("SparkByte", _simple_wheel(), _simple_palette())
        controller_b.set_ontology("SparkByte", _simple_wheel(), _simple_palette())
        controller_a.update_turn_context(
            signals={"sentiment": 0.9, "arousal": 0.8, "directive": False, "confusion": 0.0},
            aperture_state={"score": 0.7},
            behavior_profile="expressive",
        )
        controller_b.update_turn_context(
            signals={"sentiment": 0.0, "arousal": 0.3, "directive": True, "confusion": 0.9},
            aperture_state={"score": 0.45},
            behavior_profile="expressive",
        )
        controller_a.pulse()
        controller_a.pulse()
        controller_b.pulse()
        controller_b.pulse()
        sample_a = controller_a.sample_field()
        sample_b = controller_b.sample_field()
    finally:
        controller_a.stop_loop()
        controller_b.stop_loop()

    assert sample_a["root_id"] != sample_b["root_id"]


def test_apply_temporal_sampling_bias_clamps():
    temp, top_p = apply_temporal_sampling_bias(
        1.45,
        0.99,
        {
            "root_id": "bright_triumph",
            "transition_bias": 0.9,
            "novelty_pressure": 0.9,
            "loop_pressure": 0.0,
        },
    )

    assert 0.1 <= temp <= 1.5
    assert 0.1 <= top_p <= 1.0


def test_engine_temporal_field_exposes_live_prompt_and_telemetry(monkeypatch):
    monkeypatch.setenv("JL_TQA_INTERNAL_LOOP", "0")
    monkeypatch.setenv("JL_TEMPORAL_FIELD_INTERVAL", "0.05")
    fake_backend = RecordingBackend()
    monkeypatch.setattr("jl_engine_core.engine_core.get_brain_backend", lambda: fake_backend)

    engine = JLEngineCore()
    try:
        reply, telemetry, _feedback = engine.generate_response("hey there")
    finally:
        engine.shutdown()

    assert reply == "Temporal field reply."
    assert telemetry["temporal_loop"]["running"] is True
    assert telemetry["thinking_root"]
    assert telemetry["thinking_scene"]
    assert telemetry["temporal_sampling_ready"] is False
    system_prompt = fake_backend.calls[-1]["messages"][0]["content"]
    assert "Thinking root:" in system_prompt
    assert "Thinking scene:" in system_prompt


def test_engine_temporal_sampling_waits_for_live_field(monkeypatch):
    monkeypatch.setenv("JL_TQA_INTERNAL_LOOP", "0")
    fake_backend = RecordingBackend()
    monkeypatch.setattr("jl_engine_core.engine_core.get_brain_backend", lambda: fake_backend)

    def fail_if_called(_temp, _top_p, _state):
        raise AssertionError("Temporal sampling should wait for a live field.")

    monkeypatch.setattr("jl_engine_core.engine_core.apply_temporal_sampling_bias", fail_if_called)

    engine = JLEngineCore()
    engine.emotional_sampling = False
    try:
        engine.generate_response("hello")
    finally:
        engine.shutdown()


def test_engine_temporal_sampling_activates_once_live(monkeypatch):
    monkeypatch.setenv("JL_TQA_INTERNAL_LOOP", "0")
    monkeypatch.setenv("JL_TEMPORAL_FIELD_INTERVAL", "0.05")
    fake_backend = RecordingBackend()
    monkeypatch.setattr("jl_engine_core.engine_core.get_brain_backend", lambda: fake_backend)

    seen = {}

    def fake_apply(temp, top_p, state):
        seen["state"] = dict(state)
        return temp + 0.11, top_p - 0.07

    monkeypatch.setattr("jl_engine_core.engine_core.apply_temporal_sampling_bias", fake_apply)

    engine = JLEngineCore()
    engine.emotional_sampling = False
    engine.temp = 0.7
    engine.top_p = 0.9
    engine._update_dynamic_aperture = lambda: None
    try:
        time.sleep(0.18)
        _reply, telemetry, _feedback = engine.generate_response("hello")
    finally:
        engine.shutdown()

    assert seen["state"]["sampling_ready"] is True
    assert telemetry["temporal_sampling_ready"] is True
    assert round(fake_backend.calls[-1]["options"]["temperature"], 2) == 0.81
    assert round(fake_backend.calls[-1]["options"]["top_p"], 2) == 0.83


def test_engine_temporal_sampling_can_be_disabled_independently(monkeypatch):
    monkeypatch.setenv("JL_TQA_INTERNAL_LOOP", "0")
    fake_backend = RecordingBackend()
    monkeypatch.setattr("jl_engine_core.engine_core.get_brain_backend", lambda: fake_backend)

    def fail_if_called(_temp, _top_p, _state):
        raise AssertionError("Temporal sampling bias should be disabled.")

    monkeypatch.setattr("jl_engine_core.engine_core.apply_temporal_sampling_bias", fail_if_called)

    engine = JLEngineCore()
    engine.temporal_field_sampling = False
    engine.emotional_sampling = False
    try:
        engine.generate_response("hello")
    finally:
        engine.shutdown()
