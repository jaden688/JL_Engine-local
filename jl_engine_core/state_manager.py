from __future__ import annotations

"""
state_manager.py - Lightweight session-scoped modulator state keeper.

Maintains slow-drifting internal signals (emotional drift, rhythm momentum,
gait bias, behavior blend weights) so the engine can show emergent,
self-stabilizing patterns across turns without persisting anything to disk.
State resets on restart but survives for the lifetime of the engine instance.
"""

from dataclasses import asdict, dataclass
from typing import Any, Dict, Optional

from .logging_setup import get_logger

logger = get_logger(__name__)


def _clamp(val: float, low: float = -1.0, high: float = 1.0) -> float:
    return max(low, min(high, val))


@dataclass
class ModulationState:
    emotional_drift: float = 0.0  # slow bias applied to aperture score (-1..1)
    rhythm_momentum: float = 0.0  # tendency to speed up / slow down (-1..1)
    gait_bias: float = 0.0  # pushes gait higher/lower (-1..1)
    behavior_blend: float = 0.0  # 0=centered, >0 = blend toward expressive states
    last_sentiment: float = 0.0
    attractor: float = 0.5  # stable center for feedback loops (0..1)
    turn_count: int = 0


class StateManager:
    """
    Tracks internal modulation signals within a session and provides
    advisory weights to other subsystems (behavior, rhythm, aperture, gait).
    """

    def __init__(self) -> None:
        self.state = ModulationState()

    def reset(self) -> None:
        """Reset all dynamic modulators to a neutral baseline."""
        self.state = ModulationState()

    # ---- sentiment + drift helpers ----

    def _quick_sentiment(self, text: str) -> float:
        """
        Very small heuristic sentiment pass over the assistant output.
        Returns -1..1.
        """
        if not isinstance(text, str) or not text.strip():
            return 0.0
        lowered = text.lower()
        positive_hits = sum(
            1 for k in ("great", "awesome", "glad", "love", "nice", "!") if k in lowered
        )
        negative_hits = sum(
            1 for k in ("sorry", "concern", "worry", "bad", "confused", "?") if k in lowered
        )
        raw = (positive_hits - negative_hits) / 6.0
        return _clamp(raw, -1.0, 1.0)

    def update_from_output(
        self, output: str, rhythm_state: Optional[Dict[str, Any]] = None, gait: Optional[str] = None
    ) -> None:
        """
        Incorporate the last assistant output into slow drifts.
        Rhythm variability and gait nudge the drift rate.
        """
        sentiment = self._quick_sentiment(output)
        variability = 0.0
        if isinstance(rhythm_state, dict):
            variability = float(rhythm_state.get("variability", 0.0) or 0.0)
        gait_bias = (
            0.05 if gait in ("trot", "gallop", "sprint") else -0.05 if gait == "idle" else 0.0
        )

        drift_rate = 0.04 + variability * 0.12
        self.state.emotional_drift = _clamp(
            self.state.emotional_drift * 0.9 + sentiment * drift_rate,
            -0.35,
            0.35,
        )
        self.state.rhythm_momentum = _clamp(
            self.state.rhythm_momentum * 0.85 + (sentiment + gait_bias) * 0.25,
            -0.7,
            0.7,
        )
        self.state.gait_bias = _clamp(self.state.gait_bias * 0.85 + gait_bias, -0.5, 0.5)
        self.state.behavior_blend = _clamp(
            self.state.behavior_blend * 0.9 + sentiment * 0.2, -0.5, 0.7
        )
        self.state.last_sentiment = sentiment
        self.state.turn_count += 1

        # update attractor: prefer the current rhythm/energy mix unless the user pushes strongly
        attractor_target = (
            0.5 + (self.state.rhythm_momentum * 0.15) + (self.state.emotional_drift * 0.2)
        )
        self.state.attractor = _clamp(
            self.state.attractor * 0.85 + attractor_target * 0.15, 0.0, 1.0
        )

    def advisory_payload(self, stability_score: float, drift_pressure: float) -> Dict[str, Any]:
        """
        Provide soft advisory signals to other subsystems.
        - gating_bias: request weak blocks when stability is low
        - blend_weight: encourage behavior blending near the attractor
        """
        gating_bias = 0.0
        if stability_score < 0.25 or drift_pressure > 0.6:
            gating_bias = 0.6
        elif stability_score < 0.4 or drift_pressure > 0.4:
            gating_bias = 0.3

        blend_weight = 0.5 + self.state.behavior_blend * 0.5

        return {
            "gating_bias": _clamp(gating_bias, 0.0, 1.0),
            "blend_weight": _clamp(blend_weight, 0.0, 1.0),
            "emotional_drift": self.state.emotional_drift,
            "rhythm_momentum": self.state.rhythm_momentum,
            "gait_bias": self.state.gait_bias,
            "attractor": self.state.attractor,
        }

    def export_snapshot(self) -> Dict[str, Any]:
        """Lightweight dict for telemetry or memory hooks."""
        return asdict(self.state)
