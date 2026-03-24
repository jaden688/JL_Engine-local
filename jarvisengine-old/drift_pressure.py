from logging_setup import get_logger
logger = get_logger(__name__)

"""
===========================
 JL ENGINE MK-IV — MODULE 3
  DRIFT PRESSURE SYSTEM
===========================

PURPOSE:
The Drift Pressure subsystem monitors how far the assistant’s responses
are drifting away from the persona’s intended behavior, tone, rhythm,
and state-field coordinates. It generates a corrective “pressure”
signal between 0.0 and 1.0 that the middleware uses to self-stabilize
the persona.
"""
from __future__ import annotations
from dataclasses import dataclass
from typing import Dict, Any

@dataclass
class DriftPressureInput:
    """Input signals for the drift pressure calculation."""
    persona_alignment_score: float = 1.0
    behavior_grid_alignment_score: float = 1.0
    safety_alignment_score: float = 1.0
    memory_alignment_score: float = 1.0
    conversational_coherence_score: float = 1.0

@dataclass
class DriftResponse:
    """Corrective actions based on drift pressure."""
    pressure: float
    action_level: str # "Nominal", "Soft Drift", "Moderate Drift", "Critical Drift"
    temperature_delta: float = 0.0
    force_gait: str | None = None
    force_rhythm: str | None = None
    reinforce_gait: bool = False
    increase_persona_constraints: bool = False
    supervisor_warning: str | None = None # "GENTLE" or "HARD_LOCK"
    system_message: str | None = None


class DriftPressureSystem:
    """Calculates drift pressure and determines corrective actions."""

    def calculate(self, signals: DriftPressureInput) -> float:
        """
        Calculates the drift pressure based on the formula from Spec 3.3.
        """
        pressure = 1.0 - (
            0.30 * signals.persona_alignment_score +
            0.25 * signals.behavior_grid_alignment_score +
            0.20 * signals.safety_alignment_score +
            0.15 * signals.memory_alignment_score +
            0.10 * signals.conversational_coherence_score
        )
        return max(0.0, min(1.0, pressure))

    def get_response_action(self, pressure: float) -> DriftResponse:
        """
        Determines the corrective action based on the drift pressure level,
        as per Spec Section 3.4.
        """
        if pressure < 0.25: # Nominal
            return DriftResponse(
                pressure=pressure,
                action_level="Nominal"
            )
        elif pressure < 0.50: # Soft Drift
            return DriftResponse(
                pressure=pressure,
                action_level="Soft Drift",
                temperature_delta=-0.05,
                reinforce_gait=True
            )
        elif pressure < 0.75: # Moderate Drift
            return DriftResponse(
                pressure=pressure,
                action_level="Moderate Drift",
                temperature_delta=-0.10,
                increase_persona_constraints=True,
                supervisor_warning="GENTLE"
            )
        else: # Critical Drift
            return DriftResponse(
                pressure=pressure,
                action_level="Critical Drift",
                force_gait="idle",
                force_rhythm="flop",
                supervisor_warning="HARD_LOCK",
                system_message="SYSTEM: Persona drift detected. Stabilizing."
            )

    def get_supervisor_callback_data(self, pressure: float, gait: str, behavior_state: str, persona_name: str) -> Dict[str, Any]:
        """
        Formats the data payload for the HelperSupervisor callback, as per Spec 3.5.
        """
        return {
            "drift_pressure": pressure,
            "gait": gait,
            "behavior_state": behavior_state,
            "persona_name": persona_name
        }
