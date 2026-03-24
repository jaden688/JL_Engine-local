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
        """Execute the collapse rule: T+1 -> T0, T0 -> T-1, regenerate T+1."""
        prev_zero = deepcopy(self.frame.present_state)
        new_zero = deepcopy(self.frame.future_projection)
        new_zero.outcome = outcome
        new_zero.metrics["error_signature"] = error_signature
        self.frame.past_state = prev_zero
        self.frame.present_state = new_zero
        self.frame.future_projection = self._generate_projection(new_zero)
        logger.info(
            "[TQA] Collapse event | prev_T0=%s | new_T0=%s | reason=%s | projection_basis=%s",
            {
                "persona": prev_zero.persona,
                "outcome": prev_zero.outcome,
                "metrics": prev_zero.metrics,
            },
            {
                "persona": new_zero.persona,
                "outcome": new_zero.outcome,
                "metrics": new_zero.metrics,
            },
            reason,
            self.frame.future_projection.metrics,
        )

    def _generate_projection(self, anchor: TemporalState) -> TemporalState:
        metrics = anchor.metrics or {}
        risk_level = metrics.get("risk_level", "low")
        cognitive_load = metrics.get("cognitive_load", "low")
        burnout_risk = metrics.get("burnout_risk", 0.1)

        risk_bias = {"low": 0.05, "medium": 0.15, "high": 0.3}.get(str(risk_level).lower(), 0.1)
        load_bias = {"low": 0.05, "medium": 0.2, "high": 0.35}.get(str(cognitive_load).lower(), 0.1)

        burnout = _clamp(burnout_risk + load_bias)
        failure_cascade = _clamp(risk_bias + load_bias)
        perf_regression = _clamp(risk_bias * 0.6)
        operator_overwhelm = _clamp(load_bias + (burnout * 0.25))

        return self._new_state(
            persona=anchor.persona,
            outcome=None,
            metrics={
                "burnout_risk": burnout,
                "failure_cascade_probability": failure_cascade,
                "performance_regression_probability": perf_regression,
                "operator_overwhelm_probability": operator_overwhelm,
            },
        )

    def snapshot(self) -> TemporalQuantumFrame:
        return deepcopy(self.frame)
