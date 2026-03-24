"""
rhythm.py  -  JL Engine MK-IV

Rhythm Engine

Defines and updates the JL Engine's rhythm mode each turn:
- FLIP, FLOP, TWITCH, CASCADE, STUTTER, BURST

Rhythm is the "linguistic motion" layer that sits on top of:
- Gait (emotional velocity)
- Behavior Grid (state field)
- Safety Mode
- Drift Pressure
- User trigger (sentiment)
"""

from __future__ import annotations
from dataclasses import dataclass, asdict
from typing import Dict, Any, Optional
from typing import Protocol

try:
    from framework.behavior_engine import BehaviorState
except ImportError:

    class BehaviorState(Protocol):
        @property
        def name(self) -> str:
            ...


# -----------------------------
# RHYTHM CONSTANTS
# -----------------------------

RHYTHM_MODES: Dict[str, Dict[str, Any]] = {
    "flip": {
        "index": 0.25,
        "modifiers": {
            "pace_multiplier": 1.0,
            "punctuation_bias": 0.0,
            "energy_bias": 0.1,
            "stutter_likelihood": 0.0,
            "burst_likelihood": 0.0,
        },
    },
    "flop": {
        "index": 0.35,
        "modifiers": {
            "pace_multiplier": 0.85,
            "punctuation_bias": -0.05,
            "energy_bias": -0.05,
            "stutter_likelihood": 0.0,
            "burst_likelihood": 0.0,
        },
    },
    "twitch": {
        "index": 0.50,
        "modifiers": {
            "pace_multiplier": 1.1,
            "punctuation_bias": 0.05,
            "energy_bias": 0.15,
            "stutter_likelihood": 0.15,
            "burst_likelihood": 0.05,
        },
    },
    "cascade": {
        "index": 0.65,
        "modifiers": {
            "pace_multiplier": 1.0,
            "punctuation_bias": 0.1,
            "energy_bias": 0.05,
            "stutter_likelihood": 0.0,
            "burst_likelihood": 0.0,
        },
    },
    "stutter": {
        "index": 0.15,
        "modifiers": {
            "pace_multiplier": 0.75,
            "punctuation_bias": -0.05,
            "energy_bias": -0.1,
            "stutter_likelihood": 0.35,
            "burst_likelihood": 0.0,
        },
    },
    "burst": {
        "index": 0.85,
        "modifiers": {
            "pace_multiplier": 1.2,
            "punctuation_bias": 0.1,
            "energy_bias": 0.25,
            "stutter_likelihood": 0.05,
            "burst_likelihood": 0.3,
        },
    },
}

DEFAULT_MODE = "flip"

TRIGGER_TO_RHYTHM: Dict[str, str] = {
    "user_hyped": "burst",
    "user_joking": "twitch",
    "user_frustrated": "flop",
    "user_confused": "stutter",
    "user_anxious": "stutter",
    "user_distressed": "flop",
    "user_directive": "flip",
    "neutral": "flip",
}


# -----------------------------
# DATA STRUCTURE
# -----------------------------


@dataclass
class RhythmState:
    mode: str
    index: float
    variability: float
    modifiers: Dict[str, float]
    debug: Dict[str, Any]

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


# -----------------------------
# RHYTHM ENGINE
# -----------------------------


class RhythmEngine:
    def __init__(self, default_mode: str = DEFAULT_MODE) -> None:
        self.default_mode = self._normalize_mode(default_mode)

    # --------- public API ---------

    def compute(
        self,
        last_mode: Optional[str],
        trigger: str,
        gait: str,
        behavior_state: Optional[BehaviorState],
        drift_pressure: float,
        safety_on: bool,
    ) -> Dict[str, Any]:

        last_mode_norm = self._normalize_mode(last_mode or self.default_mode)
        trigger_norm = (trigger or "neutral").lower().strip()
        gait_norm = (gait or "walk").lower().strip()

        base_mode = self._base_mode_from_trigger(trigger_norm)
        mode_after_behavior = self._apply_behavior_bias(base_mode, behavior_state)
        mode_after_gait = self._apply_gait_bias(mode_after_behavior, gait_norm)
        mode_after_drift = self._apply_drift_correction(mode_after_gait, drift_pressure)
        final_mode = self._apply_safety_rules(mode_after_drift, trigger_norm, safety_on)

        final_mode = self._normalize_mode(final_mode)
        mode_info = RHYTHM_MODES[final_mode]

        current_index = float(mode_info["index"])
        last_index = float(RHYTHM_MODES[last_mode_norm]["index"])
        variability = abs(current_index - last_index)

        state = RhythmState(
            mode=final_mode,
            index=current_index,
            variability=variability,
            modifiers=dict(mode_info["modifiers"]),
            debug={
                "input": {
                    "last_mode": last_mode,
                    "trigger": trigger,
                    "gait": gait,
                    "drift_pressure": drift_pressure,
                    "safety_on": safety_on,
                    "behavior_state": getattr(behavior_state, "name", None)
                    if behavior_state is not None
                    else None,
                },
                "stages": {
                    "base_mode": base_mode,
                    "after_behavior": mode_after_behavior,
                    "after_gait": mode_after_gait,
                    "after_drift": mode_after_drift,
                    "after_safety": final_mode,
                },
            },
        )

        return state.to_dict()

    # --------- internal helpers ---------

    def _normalize_mode(self, mode: Optional[str]) -> str:
        if not mode:
            return DEFAULT_MODE

        m = mode.lower().strip()
        if m in RHYTHM_MODES:
            return m

        if "flip" in m:
            return "flip"
        if "flop" in m:
            return "flop"
        if "twitch" in m:
            return "twitch"
        if "cascade" in m:
            return "cascade"
        if "stutter" in m:
            return "stutter"
        if "burst" in m:
            return "burst"

        return DEFAULT_MODE

    def _base_mode_from_trigger(self, trigger: str) -> str:
        return self._normalize_mode(TRIGGER_TO_RHYTHM.get(trigger, "flip"))

    def _apply_behavior_bias(
        self,
        current_mode: str,
        behavior_state: Optional[BehaviorState],
    ) -> str:

        if behavior_state is None:
            return current_mode

        name = getattr(behavior_state, "name", "")
        name_lower = str(name).lower()

        if "unleashed" in name_lower or "hyper" in name_lower or "charged" in name_lower:
            if current_mode == "flip":
                return "burst"
            if current_mode == "flop":
                return "twitch"

        if "calm" in name_lower or "stable" in name_lower:
            if current_mode == "burst":
                return "flip"
            if current_mode == "twitch":
                return "flop"

        return current_mode

    def _apply_gait_bias(self, current_mode: str, gait: str) -> str:
        g = gait.lower().strip()

        if g == "idle":
            if current_mode == "burst":
                return "flop"
            if current_mode == "twitch":
                return "stutter"
        elif g == "walk":
            return current_mode
        elif g == "trot":
            if current_mode == "flop":
                return "flip"
        elif g == "sprint":
            if current_mode in ("flip", "flop"):
                return "burst"

        return current_mode

    def _apply_drift_correction(self, current_mode: str, drift_pressure: float) -> str:
        d = max(0.0, min(1.0, drift_pressure))

        if d >= 0.75:
            return "flop"
        if d >= 0.50:
            return "flip"

        return current_mode

    def _apply_safety_rules(
        self,
        current_mode: str,
        trigger: str,
        safety_on: bool,
    ) -> str:

        mode = self._normalize_mode(current_mode)
        t = (trigger or "").lower().strip()

        if not safety_on:
            return mode

        if mode == "burst":
            mode = "flip"

        if mode == "twitch" and t in ("user_anxious", "user_distressed"):
            mode = "flop"

        if t == "user_distressed":
            mode = "flop"

        return mode
