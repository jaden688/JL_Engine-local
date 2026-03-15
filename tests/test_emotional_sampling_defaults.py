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


def _install_aperture_state(engine: JLEngineCore, emotion_meta: dict | None) -> None:
    aperture_state = {
        "score": 0.5,
        "mode": "BALANCED",
        "modifiers": {"temperature": engine.temp, "top_p": engine.top_p},
        "focus_level": 0.0,
        "overload_level": 0.0,
        "emotion": "test-emotion" if emotion_meta else None,
        "emotion_meta": emotion_meta,
        "drift_bias": 0.0,
    }
    engine.emotional_aperture.update_from_signals = lambda *args, **kwargs: None
    engine.emotional_aperture.get_state = lambda: dict(aperture_state)
    engine.emotional_aperture.get_focus_level = lambda: 0.0
    engine.emotional_aperture.get_overload_level = lambda: 0.0
    engine.emotional_aperture.apply_output_feedback = lambda *args, **kwargs: None


def _new_engine(monkeypatch) -> JLEngineCore:
    monkeypatch.setenv("JL_TQA_INTERNAL_LOOP", "0")
    engine = JLEngineCore()
    engine.supervisor_enabled = False
    engine.supervisor_gating = False
    engine.supervisor_postprocess = False
    engine._update_dynamic_aperture = lambda: None
    return engine


def test_engine_defaults_emotional_sampling_on(monkeypatch):
    engine = _new_engine(monkeypatch)

    assert engine.emotional_sampling is True


def test_engine_applies_emotion_sampling_bias_when_enabled(monkeypatch):
    backend = RecordingBackend()
    monkeypatch.setattr(engine_core_module, "get_brain_backend", lambda: backend)
    engine = _new_engine(monkeypatch)
    engine.temp = 0.7
    engine.top_p = 0.9
    _install_aperture_state(
        engine,
        {"sampling_bias": {"temperature": 0.33, "top_p": 0.44}},
    )

    engine.generate_response(
        "hello",
        context={"suppress_memory_write": True, "suppress_feedback_log": True},
    )

    assert backend.calls[-1]["options"]["temperature"] == 0.33
    assert backend.calls[-1]["options"]["top_p"] == 0.44


def test_engine_explicit_opt_out_preserves_base_sampling(monkeypatch):
    backend = RecordingBackend()
    monkeypatch.setattr(engine_core_module, "get_brain_backend", lambda: backend)
    engine = _new_engine(monkeypatch)
    engine.emotional_sampling = False
    engine.temp = 0.7
    engine.top_p = 0.9
    _install_aperture_state(
        engine,
        {"sampling_bias": {"temperature": 0.33, "top_p": 0.44}},
    )

    engine.generate_response(
        "hello",
        context={"suppress_memory_write": True, "suppress_feedback_log": True},
    )

    assert backend.calls[-1]["options"]["temperature"] == 0.7
    assert backend.calls[-1]["options"]["top_p"] == 0.9
