from __future__ import annotations

from dataclasses import dataclass
from typing import Optional
from .logging_setup import get_logger

logger = get_logger(__name__)


"""
===========================
 JL ENGINE MK-IV — MODULE 3
  DRIFT PRESSURE SYSTEM
===========================

PURPOSE:
The Drift Pressure subsystem monitors how far the assistant’s responses
are drifting away from the agent’s intended behavior, tone, rhythm,
and state-field coordinates. It generates a corrective “pressure"
signal between 0.0 and 1.0 that the middleware uses to self-stabilize
the agent.
"""


@dataclass
class DriftPressureInput:
    agent_alignment_score: float = 1.0
    behavior_grid_alignment_score: float = 1.0
    safety_alignment_score: float = 1.0
    memory_alignment_score: float = 1.0
    conversational_coherence_score: float = 1.0

    def clamp(self) -> "DriftPressureInput":
        self.agent_alignment_score = max(0.0, min(1.0, self.agent_alignment_score))
        self.behavior_grid_alignment_score = max(0.0, min(1.0, self.behavior_grid_alignment_score))
        self.safety_alignment_score = max(0.0, min(1.0, self.safety_alignment_score))
        self.memory_alignment_score = max(0.0, min(1.0, self.memory_alignment_score))
        self.conversational_coherence_score = max(
            0.0, min(1.0, self.conversational_coherence_score)
        )
        return self


@dataclass
class DriftResponse:
    pressure: float
    action_level: str
    temperature_delta: float = 0.0
    force_gait: Optional[str] = None
    force_rhythm: Optional[str] = None
    supervisor_warning: Optional[str] = None
    reinforce_gait: bool = False


class DriftPressureSystem:
    """
    Computes a scalar drift pressure from alignment scores and produces
    a qualitative response object used by the orchestrator.
    """

    def calculate(self, signals: DriftPressureInput) -> float:
        """
        Calculate the drift pressure using a weighted complement of alignment scores.
        Lower alignment -> higher pressure.
        """
        signals = signals.clamp()
        pressure = 1.0 - (
            0.30 * signals.agent_alignment_score
            + 0.25 * signals.behavior_grid_alignment_score
            + 0.20 * signals.safety_alignment_score
            + 0.15 * signals.memory_alignment_score
            + 0.10 * signals.conversational_coherence_score
        )
        pressure = max(0.0, min(1.0, pressure))
        logger.debug(
            "[Drift] agent=%.4f behavior=%.4f safety=%.4f memory=%.4f coherence=%.4f -> pressure=%.4f",
            signals.agent_alignment_score,
            signals.behavior_grid_alignment_score,
            signals.safety_alignment_score,
            signals.memory_alignment_score,
            signals.conversational_coherence_score,
            pressure,
        )
        return pressure

    def get_response_action(self, pressure: float) -> DriftResponse:
        """
        Map a pressure value into a qualitative DriftResponse used to slightly
        adjust generation parameters or trigger supervisory behavior.
        """
        if pressure < 0.10:
            return DriftResponse(pressure=pressure, action_level="Nominal")
        elif pressure < 0.50:
            return DriftResponse(
                pressure=pressure,
                action_level="Soft Drift",
                temperature_delta=-0.05,
                reinforce_gait=True,
            )
        elif pressure < 0.75:
            return DriftResponse(
                pressure=pressure,
                action_level="Moderate Drift",
                temperature_delta=-0.10,
                supervisor_warning="FIRM: Treat this like a growing drift fluctuation; slow down and re-check alignment.",
            )
        else:
            return DriftResponse(
                pressure=pressure,
                action_level="Hard Drift",
                temperature_delta=-0.20,
                force_gait="lockstep",
                force_rhythm="strict",
                supervisor_warning="HARD_LOCK: Containment protocols engaged. This is your safety line, not a suggestion.",
            )
