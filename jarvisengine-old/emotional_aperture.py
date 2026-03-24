from logging_setup import get_logger
logger = get_logger(__name__)

from typing import Optional
from cognitive_gears import GearType, get_gear_modifiers

class EmotionalAperture:
    """
    Implements the Emotional Aperture Module as per the JL-EMO-APERTURE-MKIV spec.
    This module calculates a single score to determine the engine's expressive mode.
    """

    def __init__(self, drive_type: GearType = "spur"):
        self.drive_type: GearType = drive_type
        self._current_emotion: Optional[str] = None
        self._focus_level: float = 0.0
        self._overload_level: float = 0.0
        self._last_state = self._build_state(0.25, "GUARDED", self.MODIFIERS["GUARDED"])

    MODIFIERS = {
        "CLOSED": {"temperature": 0.10, "top_p": 0.20, "persona_amplitude": 0.05, "creativity_bias": 0.05, "expressiveness": 0.06},
        "GUARDED": {"temperature": 0.25, "top_p": 0.45, "persona_amplitude": 0.20, "creativity_bias": 0.18, "expressiveness": 0.22},
        "BALANCED": {"temperature": 0.45, "top_p": 0.70, "persona_amplitude": 0.45, "creativity_bias": 0.45, "expressiveness": 0.50},
        "OPEN": {"temperature": 0.65, "top_p": 0.85, "persona_amplitude": 0.70, "creativity_bias": 0.75, "expressiveness": 0.78},
        "WIDE_OPEN": {"temperature": 0.85, "top_p": 0.95, "persona_amplitude": 0.95, "creativity_bias": 0.98, "expressiveness": 1.00},
    }

    def _get_mode_from_score(self, score: float) -> str:
        if score <= 0.12: return "CLOSED"
        if score <= 0.28: return "GUARDED"
        if score <= 0.55: return "BALANCED"
        if score <= 0.78: return "OPEN"
        return "WIDE_OPEN"

    def set_drive_type(self, drive_type: GearType) -> None:
        if self.drive_type != drive_type:
            print(f"[Aperture] drive_type set to {drive_type}")
            self.drive_type = drive_type

    def get_drive_type(self) -> GearType:
        return self.drive_type

    def get_gear_modifiers(self):
        return get_gear_modifiers(self.drive_type)

    def reset(self):
        """Reset aperture state back to a safe baseline."""
        self._current_emotion = None
        self._focus_level = 0.0
        self._overload_level = 0.0
        self._last_state = self._build_state(0.25, "GUARDED", self.MODIFIERS["GUARDED"])

    def get_state(self) -> dict:
        """Return the last computed aperture state."""
        return dict(self._last_state)

    def update_from_signals(self, behavior_state=None, gait: str = "walk", rhythm: str = "flop", **signals):
        """
        Update aperture using a simplified signal set from the main app.
        Missing signals fall back to neutral defaults to avoid crashes.
        """
        behavior_intensity = getattr(behavior_state, "expressiveness", 0.5)
        gait_range = self._map_gait_to_range(gait)
        rhythm_variability = self._map_rhythm_to_variability(rhythm)

        signal_payload = {
            "behavior_intensity": behavior_intensity,
            "persona_vividness": signals.get("persona_vividness", 0.6),
            "safety_mode": signals.get("safety_mode", True),
            "drift_pressure": signals.get("drift_pressure", 0.0),
            "user_sentiment": signals.get("user_sentiment", 0.0),
            "conversation_pacing": signals.get("conversation_pacing", 0.5),
            "memory_density": signals.get("memory_density", 0.0),
            "gait_range": gait_range,
            "rhythm_variability": rhythm_variability,
            "aperture_bias": signals.get("aperture_bias", 0.0),
        }

        computed = self.compute(signal_payload)
        self._last_state = self._build_state(
            computed.get("score", 0.0),
            computed.get("mode", "GUARDED"),
            computed.get("modifiers"),
        )
        return self._last_state

    def update_from_signal(self, emotion: Optional[str] = None, focus_delta: float = 0.0, overload_delta: float = 0.0):
        """
        Update aperture from new measurements. This method is gear-aware:
        the gear determines how fast and how stably aperture changes.
        """
        mods = self.get_gear_modifiers()

        # 1) update discrete emotion with some inertia
        if emotion is not None:
            self._current_emotion = emotion

        # 2) update continuous dimensions with gear-scaled deltas
        # reaction_speed: how strongly we apply the incoming change
        scaled_focus = focus_delta * mods.reaction_speed
        scaled_overload = overload_delta * mods.reaction_speed

        # mode_inertia reduces how fast we move away from prior state
        inertia = mods.mode_inertia
        inv_inertia = 1.0 - inertia

        # apply like a leaky integrator
        self._focus_level = self._focus_level * inertia + scaled_focus * inv_inertia
        self._overload_level = self._overload_level * inertia + scaled_overload * inv_inertia

        # clamp to 0..1
        self._focus_level = max(0.0, min(1.0, self._focus_level))
        self._overload_level = max(0.0, min(1.0, self._overload_level))
        self._last_state["focus_level"] = self._focus_level
        self._last_state["overload_level"] = self._overload_level

    def get_focus_level(self) -> float:
        return self._focus_level

    def get_overload_level(self) -> float:
        return self._overload_level

    def compute(self, signals: dict) -> dict:
        """
        Computes the aperture score and resolves the final state.
        `signals` is a dictionary containing the nine input signals.
        """
        # Use .get() to provide defaults for missing signals
        behavior_intensity = signals.get("behavior_intensity", 0.5)
        persona_vividness = signals.get("persona_vividness", 0.5)
        safety_mode = signals.get("safety_mode", True)
        drift_pressure = signals.get("drift_pressure", 0.0)
        user_sentiment = signals.get("user_sentiment", 0.0)
        conversation_pacing = signals.get("conversation_pacing", 0.5)
        memory_density = signals.get("memory_density", 0.0)
        gait_range = signals.get("gait_range", 0.3) # Default to WALK
        rhythm_variability = signals.get("rhythm_variability", 0.5)

        # Per spec failure mode: if any signal is missing, default to GUARDED.
        # .get() with defaults handles this, but an explicit check for None is safer.
        if any(signals.get(k) is None for k in [
            "behavior_intensity", "persona_vividness", "safety_mode", "drift_pressure",
            "user_sentiment", "conversation_pacing", "memory_density", "gait_range", "rhythm_variability"
        ]):
             return {
                "score": 0.25,
                "mode": "GUARDED",
                "modifiers": self.MODIFIERS["GUARDED"],
             }

        # Calculate weighted score
        score = (
            (behavior_intensity * 0.18) +
            (persona_vividness * 0.16) +
            (user_sentiment * 0.22) +
            (conversation_pacing * 0.08) +
            (memory_density * 0.12) +
            (gait_range * 0.06) +
            (rhythm_variability * 0.08) -
            (drift_pressure * 0.20)
        )
        
        # Apply bias from supervisor
        score += signals.get("aperture_bias", 0.0)

        # Clamp score to be within [0, 1]
        score = max(0.0, min(1.0, score))

        # Apply safety clamp
        if safety_mode:
            score = min(score, 0.39)

        # Resolve mode and modifiers
        mode = self._get_mode_from_score(score)
        modifiers = self.MODIFIERS.get(mode)

        return {
            "score": score,
            "mode": mode,
            "modifiers": modifiers,
        }

    def _build_state(self, score: float, mode: str, modifiers: dict | None = None) -> dict:
        mods = modifiers or self.MODIFIERS.get(mode, self.MODIFIERS["BALANCED"])
        return {
            "score": score,
            "mode": mode,
            "modifiers": mods,
            "temp": mods.get("temperature", 0.45),
            "top_p": mods.get("top_p", 0.7),
            "focus_level": self._focus_level,
            "overload_level": self._overload_level,
        }

    def _map_gait_to_range(self, gait: str) -> float:
        """Map gait string to a normalized range value used by the aperture compute step."""
        return {
            "idle": 0.1,
            "walk": 0.3,
            "trot": 0.55,
            "gallop": 0.75,
            "sprint": 0.9,
        }.get(gait, 0.3)

    def _map_rhythm_to_variability(self, rhythm: str) -> float:
        """Map rhythm name to a variability score."""
        return {
            "flop": 0.2,
            "flip": 0.35,
            "twitch": 0.55,
            "cascade": 0.45,
            "stutter": 0.3,
            "burst": 0.65,
        }.get(rhythm, 0.4)
