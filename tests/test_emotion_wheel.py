from __future__ import annotations

from jl_engine_core.emotional_aperture import EmotionalAperture
from jl_engine_core.engine_core import JLEngineCore


def test_emotion_wheel_enriches_selected_meta():
    aperture = EmotionalAperture()
    aperture.set_emotion_model(
        [
            {
                "id": "playful_intrigue",
                "label": "playful intrigue",
                "style": "light teasing curiosity",
                "score_range": [0.2, 0.7],
                "intensity": 0.5,
                "sentiment": "positive",
                "sampling_bias": {"temperature": 0.03, "top_p": 0.02},
            }
        ],
        {
            "baseline_root": "playful_energy",
            "baseline_family": "playful",
            "roots": [
                {
                    "id": "playful_energy",
                    "label": "playful energy",
                    "default_weight": 0.9,
                    "families": [
                        {
                            "id": "playful",
                            "label": "playful spark",
                            "default_weight": 0.8,
                            "repeat_penalty": 0.2,
                            "cooldown_turns": 2,
                            "sensation": {
                                "id": "buzzy_light",
                                "label": "buzzy lightness",
                                "style": "bright, fizzy, socially electric",
                            },
                            "scenes": [
                                {
                                    "id": "curious_banter",
                                    "label": "curious banter",
                                    "default_weight": 1.0,
                                    "facet_ids": ["playful_intrigue"],
                                }
                            ],
                        }
                    ],
                }
            ],
        },
    )

    state = aperture.update_from_signals(user_sentiment=0.3, safety_mode=False)

    assert state["emotion"] == "playful intrigue"
    assert state["emotion_root"] == "playful energy"
    assert state["emotion_family"] == "playful spark"
    assert state["emotion_scene"] == "curious banter"
    assert state["emotion_sensation"] == "buzzy lightness"
    assert state["emotion_meta"]["root_id"] == "playful_energy"
    assert state["emotion_meta"]["family_id"] == "playful"
    assert state["emotion_meta"]["scene_id"] == "curious_banter"
    assert state["emotion_meta"]["facet_id"] == "playful_intrigue"


def test_emotion_wheel_repeat_penalty_pushes_alternate_facet():
    aperture = EmotionalAperture()
    aperture.set_emotion_model(
        [
            {
                "id": "a",
                "label": "facet a",
                "style": "a",
                "score_range": [0.2, 0.7],
                "intensity": 0.5,
                "sentiment": "neutral",
            },
            {
                "id": "b",
                "label": "facet b",
                "style": "b",
                "score_range": [0.2, 0.7],
                "intensity": 0.5,
                "sentiment": "neutral",
            },
        ],
        {
            "roots": [
                {
                    "id": "playful_energy",
                    "label": "playful energy",
                    "families": [
                        {
                            "id": "playful",
                            "label": "playful spark",
                            "default_weight": 1.0,
                            "repeat_penalty": 0.85,
                            "cooldown_turns": 2,
                            "scenes": [
                                {
                                    "id": "teasing_heat",
                                    "label": "teasing heat",
                                    "facet_ids": ["a", "b"],
                                }
                            ],
                        }
                    ],
                }
            ]
        },
    )

    first = aperture.update_from_signals(safety_mode=False)
    second = aperture.update_from_signals(safety_mode=False)

    assert first["emotion_meta"]["facet_id"] == "a"
    assert second["emotion_meta"]["facet_id"] == "b"


def test_engine_loads_sparkbyte_emotion_wheel(monkeypatch):
    monkeypatch.setenv("JL_TQA_INTERNAL_LOOP", "0")
    engine = JLEngineCore()
    engine.set_agent("SparkByte")

    assert engine.emotional_aperture.emotion_wheel.get("baseline_root") == "playful_energy"
    assert engine.emotional_aperture.emotion_wheel.get("baseline_family") == "playful"
    assert any(
        entry.get("root_id") == "playful_energy"
        for entry in engine.emotional_aperture.emotion_palette
    )
    assert any(
        entry.get("family_id") == "playful" for entry in engine.emotional_aperture.emotion_palette
    )
    assert any(
        entry.get("scene_id") == "curious_banter"
        for entry in engine.emotional_aperture.emotion_palette
    )
