from __future__ import annotations

import logging
from copy import deepcopy
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, Tuple

logger = logging.getLogger(__name__)


def _clamp(val: float, lo: float = 0.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, val))


@dataclass
class TemporalState:
    timestamp: datetime
    persona: str | None
    outcome: str | None
    metrics: Dict[str, Any] = field(default_factory=dict)


@dataclass
class TemporalQuantumFrame:
    past_state: TemporalState
    present_state: TemporalState
    future_projection: TemporalState


class TemporalQuantumAgent:
    """Temporal Quantum Agent controller tracking three coexisting time states."""

    def __init__(self) -> None:
        bootstrap = self._new_state(persona=None, outcome=None)
        self.frame = TemporalQuantumFrame(
            past_state=deepcopy(bootstrap),
            present_state=deepcopy(bootstrap),
            future_projection=deepcopy(bootstrap),
        )

    def _new_state(self, persona: str | None, outcome: str | None, metrics: Dict[str, Any] | None = None) -> TemporalState:
        defaults: Dict[str, Any] = {
            "action_type": None,
            "error_signature": None,
            "task_intent": None,
            "risk_level": "low",
            "cognitive_load": "low",
            "burnout_risk": 0.0,
            "failure_cascade_probability": 0.0,
            "performance_regression_probability": 0.0,
            "operator_overwhelm_probability": 0.0,
        }
        merged = {**defaults, **(metrics or {})}
        return TemporalState(timestamp=datetime.utcnow(), persona=persona, outcome=outcome, metrics=merged)

    def update_present_state(
        self,
        persona: str,
        task_intent: str,
        risk_level: str,
        cognitive_load: str,
        action_type: str | None = None,
        error_signature: str | None = None,
        memory_snapshot: Dict[str, Any] | None = None,
    ) -> None:
        metrics = {
            "task_intent": task_intent,
            "risk_level": risk_level,
            "cognitive_load": cognitive_load,
            "action_type": action_type,
            "error_signature": error_signature,
            "memory_snapshot": memory_snapshot,
        }
        self.frame.present_state = self._new_state(persona=persona, outcome=self.frame.present_state.outcome, metrics=metrics)

    def update_future_projection(
        self,
        burnout_risk: float,
        failure_cascade_probability: float,
        performance_regression_probability: float,
        operator_overwhelm_probability: float,
        persona: str | None = None,
        outcome: str | None = None,
    ) -> None:
        metrics = {
            "burnout_risk": _clamp(burnout_risk),
            "failure_cascade_probability": _clamp(failure_cascade_probability),
            "performance_regression_probability": _clamp(performance_regression_probability),
            "operator_overwhelm_probability": _clamp(operator_overwhelm_probability),
        }
        persona = persona or self.frame.present_state.persona
        outcome = outcome or self.frame.present_state.outcome
        self.frame.future_projection = self._new_state(persona=persona, outcome=outcome, metrics=metrics)

    def apply_biases(self, requested_persona: str) -> Tuple[str, str]:
        """Apply soft routing biases based on the future projection."""
        metrics = self.frame.future_projection.metrics or {}
        persona_choice = requested_persona
        reasons: list[str] = []
        burnout_risk = metrics.get("burnout_risk", 0.0)
        failure_prob = metrics.get("failure_cascade_probability", 0.0)
        perf_regression = metrics.get("performance_regression_probability", 0.0)
        operator_overwhelm = metrics.get("operator_overwhelm_probability", 0.0)

        if burnout_risk > 0.7:
            persona_choice = "Forgebinder" if requested_persona != "Forgebinder" else requested_persona
            reasons.append(f"burnout_risk={burnout_risk:.2f}")
            if requested_persona not in {"Forgebinder", "Scribe"}:
                persona_choice = "Forgebinder"
        if failure_prob > 0.7:
            persona_choice = "Slappy"
            reasons.append(f"failure_cascade_probability={failure_prob:.2f}")
        if perf_regression > 0.6:
            persona_choice = "Optimizer"
            reasons.append(f"performance_regression_probability={perf_regression:.2f}")
        if operator_overwhelm > 0.6:
            persona_choice = "Jado"
            reasons.append(f"operator_overwhelm_probability={operator_overwhelm:.2f}")

        reason = ", ".join(reasons)
        return persona_choice, reason

    def collapse(self, reason: str, outcome: str, error_signature: str | None = None) -> None:
        """
        Execute the deterministic collapse rule:
        1. Past state T-1 is set to the current Present T0.
        2. Present state T0 is set to the Future Projection T+1 (realizing the projected risk).
        3. Future projection T+1 is re-calculated based on the new Present state.
        """
        original_present = deepcopy(self.frame.present_state)
        realized_state = deepcopy(self.frame.future_projection)
        
        # Realize the outcome and error in the new present state
        realized_state.outcome = outcome
        if error_signature:
            realized_state.metrics["error_signature"] = error_signature
            
        # Shift temporal frames
        self.frame.past_state = original_present
        self.frame.present_state = realized_state
        
        # Recalculate future based on the realization
        self.frame.future_projection = self._generate_projection(self.frame.present_state)
        
        logger.info(
            "[TQA] Deterministic Collapse | reason=%s | error=%s | realized_outcome=%s",
            reason, error_signature, outcome
        )

    def _generate_projection(self, anchor: TemporalState) -> TemporalState:
        """
        Generates a deterministic future projection based on the current anchor state.
        Uses granular weights to predict system drift pressure.
        """
        m = anchor.metrics or {}
        risk_label = str(m.get("risk_level", "low")).lower()
        load_label = str(m.get("cognitive_load", "low")).lower()
        
        # Granular base weights
        risk_weight = {"low": 0.02, "medium": 0.12, "high": 0.28}.get(risk_label, 0.1)
        load_weight = {"low": 0.04, "medium": 0.18, "high": 0.32}.get(load_label, 0.1)
        
        # Derived probabilities
        burnout = _clamp(m.get("burnout_risk", 0.0) + (load_weight * 1.1))
        failure_cascade = _clamp(risk_weight + (load_weight * 0.8))
        perf_regress = _clamp(risk_weight * 1.2 + (load_weight * 0.3))
        operator_over = _clamp(load_weight * 1.5 + (burnout * 0.1))
        
        return self._new_state(
            persona=anchor.persona,
            outcome=None,
            metrics={
                "burnout_risk": round(burnout, 4),
                "failure_cascade_probability": round(failure_cascade, 4),
                "performance_regression_probability": round(perf_regress, 4),
                "operator_overwhelm_probability": round(operator_over, 4),
                "drift_pressure_projection": round((burnout + failure_cascade) / 2, 4)
            }
        )

    def snapshot(self) -> Dict[str, Any]:
        """Provides a comprehensive telemetry snapshot for the engine feedback loop."""
        f = self.frame
        return {
            "timestamp": datetime.utcnow().isoformat(),
            "past": {"persona": f.past_state.persona, "outcome": f.past_state.outcome, "metrics": f.past_state.metrics},
            "present": {"persona": f.present_state.persona, "outcome": f.present_state.outcome, "metrics": f.present_state.metrics},
            "future": {"persona": f.future_projection.persona, "metrics": f.future_projection.metrics},
            "stability_index": round(1.0 - f.future_projection.metrics.get("failure_cascade_probability", 0.0), 4)
        }

