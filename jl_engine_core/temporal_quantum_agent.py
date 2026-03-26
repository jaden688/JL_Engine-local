from __future__ import annotations

import logging
from copy import deepcopy
from dataclasses import dataclass, field
from datetime import UTC, datetime
from threading import Event, RLock, Thread
from typing import Any, Dict, Tuple

logger = logging.getLogger(__name__)
SPEC_NUMBER_PRECISION = 4


def _clamp(val: float, lo: float = 0.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, val))


def _round_spec_numbers(value: Any, *, places: int = SPEC_NUMBER_PRECISION) -> Any:
    if isinstance(value, bool):
        return value
    if isinstance(value, float):
        return round(value, places)
    if isinstance(value, dict):
        return {key: _round_spec_numbers(item, places=places) for key, item in value.items()}
    if isinstance(value, list):
        return [_round_spec_numbers(item, places=places) for item in value]
    if isinstance(value, tuple):
        return tuple(_round_spec_numbers(item, places=places) for item in value)
    return value


@dataclass
class TemporalState:
    timestamp: datetime
    agent: str | None
    outcome: str | None
    metrics: Dict[str, Any] = field(default_factory=dict)


@dataclass
class TemporalQuantumFrame:
    past_state: TemporalState
    present_state: TemporalState
    future_projection: TemporalState


class TemporalQuantumAgent:
    """Temporal Quantum Agent controller tracking three coexisting time states."""

    def __init__(
        self,
        *,
        internal_loop_interval_seconds: float = 0.75,
        autostart_internal_loop: bool = True,
    ) -> None:
        self._lock = RLock()
        bootstrap = self._new_state(agent=None, outcome=None)
        self.frame = TemporalQuantumFrame(
            past_state=deepcopy(bootstrap),
            present_state=deepcopy(bootstrap),
            future_projection=deepcopy(bootstrap),
        )
        self._loop_interval_seconds = max(0.1, float(internal_loop_interval_seconds or 0.75))
        self._loop_stop = Event()
        self._loop_thread: Thread | None = None
        self._loop_ticks: int = 0
        self._loop_last_tick_at: datetime | None = None
        if autostart_internal_loop:
            self.start_internal_loop()

    def _new_state(
        self, agent: str | None, outcome: str | None, metrics: Dict[str, Any] | None = None
    ) -> TemporalState:
        defaults: Dict[str, Any] = {
            "action_type": None,
            "error_signature": None,
            "task_intent": None,
            "risk_level": "low",
            "cognitive_load": "low",
            "stability_index": 1.0,
            "burnout_risk": 0.0,
            "failure_cascade_probability": 0.0,
            "performance_regression_probability": 0.0,
            "operator_overwhelm_probability": 0.0,
        }
        merged = {**defaults, **(metrics or {})}
        return TemporalState(
            timestamp=datetime.now(UTC), agent=agent, outcome=outcome, metrics=merged
        )

    def update_present_state(
        self,
        agent: str,
        task_intent: str,
        risk_level: str,
        cognitive_load: str,
        action_type: str | None = None,
        error_signature: str | None = None,
    ) -> None:
        metrics = {
            "task_intent": task_intent,
            "risk_level": risk_level,
            "cognitive_load": cognitive_load,
            "action_type": action_type,
            "error_signature": error_signature,
        }
        with self._lock:
            self.frame.present_state = self._new_state(
                agent=agent, outcome=self.frame.present_state.outcome, metrics=metrics
            )

    def update_future_projection(
        self,
        burnout_risk: float,
        failure_cascade_probability: float,
        performance_regression_probability: float,
        operator_overwhelm_probability: float,
        agent: str | None = None,
        outcome: str | None = None,
    ) -> None:
        metrics = {
            "burnout_risk": _clamp(burnout_risk),
            "failure_cascade_probability": _clamp(failure_cascade_probability),
            "performance_regression_probability": _clamp(performance_regression_probability),
            "operator_overwhelm_probability": _clamp(operator_overwhelm_probability),
        }
        with self._lock:
            agent = agent or self.frame.present_state.agent
            outcome = outcome or self.frame.present_state.outcome
            self.frame.future_projection = self._new_state(
                agent=agent, outcome=outcome, metrics=metrics
            )

    def apply_biases(self, requested_agent: str) -> Tuple[str, str]:
        """Apply soft routing biases based on the future projection."""
        with self._lock:
            metrics = dict(self.frame.future_projection.metrics or {})
        agent_choice = requested_agent
        reasons: list[str] = []
        burnout_risk = metrics.get("burnout_risk", 0.0)
        failure_prob = metrics.get("failure_cascade_probability", 0.0)
        perf_regression = metrics.get("performance_regression_probability", 0.0)
        operator_overwhelm = metrics.get("operator_overwhelm_probability", 0.0)

        if burnout_risk > 0.7:
            agent_choice = (
                "Forgebinder" if requested_agent != "Forgebinder" else requested_agent
            )
            reasons.append(f"burnout_risk={burnout_risk:.4f}")
            if requested_agent not in {"Forgebinder", "Scribe"}:
                agent_choice = "Forgebinder"
        if failure_prob > 0.7:
            agent_choice = "Slappy"
            reasons.append(f"failure_cascade_probability={failure_prob:.4f}")
        if perf_regression > 0.6:
            agent_choice = "Optimizer"
            reasons.append(f"performance_regression_probability={perf_regression:.4f}")
        if operator_overwhelm > 0.6:
            agent_choice = "Jado"
            reasons.append(f"operator_overwhelm_probability={operator_overwhelm:.4f}")

        reason = ", ".join(reasons)
        return agent_choice, reason

    def collapse(self, reason: str, outcome: str, error_signature: str | None = None) -> None:
        """Execute the collapse rule: T+1 -> T0, T0 -> T-1, regenerate T+1."""
        with self._lock:
            prev_zero = deepcopy(self.frame.present_state)
            # The probability cloud collapses: the previously projected future is now the present.
            new_present = deepcopy(self.frame.future_projection)
            new_present.timestamp = datetime.now(UTC)
            new_present.outcome = outcome

            # Merge metrics from actual outcome if provided (error signatures indicate entropy spikes)
            if error_signature:
                new_present.metrics["error_signature"] = error_signature
                # Collapse event entropy penalty
                prev_stability = new_present.metrics.get("stability_index", 1.0)
                new_present.metrics["stability_index"] = _clamp(prev_stability - 0.15)

            self.frame.past_state = prev_zero
            self.frame.present_state = new_present
            self.frame.future_projection = self._generate_projection(new_present)
            projection_metrics = dict(self.frame.future_projection.metrics)
        logger.info(
            "[TQA] Collapse event | prev_T0=%s | new_T0=%s | reason=%s | projection_basis=%s",
            {
                "agent": prev_zero.agent,
                "outcome": prev_zero.outcome,
                "metrics": _round_spec_numbers(prev_zero.metrics),
            },
            {
                "agent": new_present.agent,
                "outcome": new_present.outcome,
                "metrics": _round_spec_numbers(new_present.metrics),
            },
            reason,
            _round_spec_numbers(projection_metrics),
        )

    def _generate_projection(self, anchor: TemporalState) -> TemporalState:
        """Generate a deterministic future projection based on present anchor metrics."""
        metrics = anchor.metrics or {}
        risk_level = metrics.get("risk_level", "low")
        cognitive_load = metrics.get("cognitive_load", "low")
        stability_index = metrics.get("stability_index", 1.0)
        burnout_risk = metrics.get("burnout_risk", 0.1)

        # Deterministic entropy scaling
        risk_bias = {"low": 0.05, "medium": 0.15, "high": 0.3}.get(str(risk_level).lower(), 0.1)
        load_bias = {"low": 0.05, "medium": 0.2, "high": 0.35}.get(str(cognitive_load).lower(), 0.1)

        # Stability works as an inverse multiplier for risk propagation
        instability_factor = 1.0 - stability_index

        burnout = _clamp(burnout_risk + load_bias + (instability_factor * 0.1))
        failure_cascade = _clamp(risk_bias + load_bias + (instability_factor * 0.2))
        perf_regression = _clamp(risk_bias * 0.6 + (instability_factor * 0.15))
        operator_overwhelm = _clamp(load_bias + (burnout * 0.25) + (instability_factor * 0.1))

        # New stability projection (tends towards homeostasis unless load is high)
        projected_stability = _clamp(stability_index + (0.05 if load_bias < 0.2 else -0.05))

        return self._new_state(
            agent=anchor.agent,
            outcome=None,
            metrics={
                "burnout_risk": burnout,
                "failure_cascade_probability": failure_cascade,
                "performance_regression_probability": perf_regression,
                "operator_overwhelm_probability": operator_overwhelm,
                "stability_index": projected_stability,
                "risk_level": risk_level,
                "cognitive_load": cognitive_load,
            },
        )

    def snapshot(self) -> TemporalQuantumFrame:
        with self._lock:
            return deepcopy(self.frame)

    def start_internal_loop(self, interval_seconds: float | None = None) -> None:
        with self._lock:
            if interval_seconds is not None:
                self._loop_interval_seconds = max(0.1, float(interval_seconds))
            if self._loop_thread and self._loop_thread.is_alive():
                return
            self._loop_stop.clear()
            self._loop_thread = Thread(
                target=self._internal_loop_worker,
                daemon=True,
                name="tqa-internal-loop",
            )
            self._loop_thread.start()

    def stop_internal_loop(self, join_timeout_seconds: float = 1.0) -> None:
        thread: Thread | None
        with self._lock:
            thread = self._loop_thread
            self._loop_stop.set()
        if thread and thread.is_alive():
            thread.join(timeout=max(0.1, float(join_timeout_seconds or 1.0)))
        with self._lock:
            if self._loop_thread is thread and (thread is None or not thread.is_alive()):
                self._loop_thread = None
                self._loop_stop.clear()

    def get_internal_loop_status(self) -> Dict[str, Any]:
        with self._lock:
            running = bool(self._loop_thread and self._loop_thread.is_alive())
            return {
                "running": running,
                "interval_seconds": round(self._loop_interval_seconds, 4),
                "ticks": self._loop_ticks,
                "last_tick_at": self._loop_last_tick_at.isoformat()
                if isinstance(self._loop_last_tick_at, datetime)
                else None,
                "thread_name": self._loop_thread.name if self._loop_thread else None,
            }

    def pulse_internal_loop(self) -> None:
        self._internal_tick()

    def set_future_stability_index(self, value: float) -> None:
        with self._lock:
            self.frame.future_projection.metrics["stability_index"] = _clamp(float(value))

    def _internal_loop_worker(self) -> None:
        while not self._loop_stop.wait(self._loop_interval_seconds):
            self._internal_tick()
        with self._lock:
            self._loop_thread = None

    def _internal_tick(self) -> None:
        with self._lock:
            anchor = deepcopy(self.frame.present_state)
            self.frame.future_projection = self._generate_projection(anchor)
            self._loop_ticks += 1
            self._loop_last_tick_at = datetime.now(UTC)
