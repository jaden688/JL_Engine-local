"""Standalone Temporal Quantum Agent test driver."""

from __future__ import annotations

import logging
from typing import Dict, Any

from temporal_quantum_agent import TemporalQuantumAgent

logging.basicConfig(level=logging.INFO, format="%(message)s")


def render_state(state: Any) -> Dict[str, Any]:
    return {
        "persona": getattr(state, "persona", None),
        "outcome": getattr(state, "outcome", None),
        "metrics": getattr(state, "metrics", {}),
    }


def show_frame(agent: TemporalQuantumAgent, label: str) -> None:
    snap = agent.snapshot()
    print(f"{label} -> T-1: {render_state(snap.past_state)} | T0: {render_state(snap.present_state)} | T+1: {render_state(snap.future_projection)}")


def run_step(agent: TemporalQuantumAgent, requested_persona: str, task_intent: str, risk: str, load: str, future_metrics: Dict[str, float], outcome: str, reason: str) -> None:
    agent.update_present_state(
        persona=requested_persona,
        task_intent=task_intent,
        risk_level=risk,
        cognitive_load=load,
        action_type="build",
    )
    agent.update_future_projection(
        burnout_risk=future_metrics.get("burnout", 0.0),
        failure_cascade_probability=future_metrics.get("failure", 0.0),
        performance_regression_probability=future_metrics.get("performance", 0.0),
        operator_overwhelm_probability=future_metrics.get("overwhelm", 0.0),
    )
    biased_persona, bias_reason = agent.apply_biases(requested_persona)
    print(f"Requested: {requested_persona} -> Routed: {biased_persona} | Bias: {bias_reason or 'none'}")
    agent.collapse(reason=reason, outcome=outcome)
    show_frame(agent, "Collapse")


def rapid_gremlin_loop(agent: TemporalQuantumAgent) -> None:
    print("\n[1] Rapid Gremlin chaos loop")
    for idx in range(3):
        run_step(
            agent,
            requested_persona="Gremlin",
            task_intent="chaos refactor blitz",
            risk="high",
            load="high",
            future_metrics={"burnout": 0.8, "failure": 0.4, "performance": 0.2, "overwhelm": 0.3},
            outcome="partial" if idx < 2 else "failure",
            reason=f"gremlin_loop_{idx}",
        )


def repeated_slappy_failures(agent: TemporalQuantumAgent) -> None:
    print("\n[2] Repeated Slappy brute-force failures")
    for idx in range(2):
        run_step(
            agent,
            requested_persona="Slappy",
            task_intent="brute force patch",
            risk="medium",
            load="medium",
            future_metrics={"burnout": 0.3, "failure": 0.85, "performance": 0.25, "overwhelm": 0.2},
            outcome="failure",
            reason=f"slappy_fail_{idx}",
        )


def optimizer_tuning(agent: TemporalQuantumAgent) -> None:
    print("\n[3] Sustained Optimizer performance tuning")
    for idx in range(2):
        run_step(
            agent,
            requested_persona="Optimizer",
            task_intent="tighten hot paths",
            risk="medium",
            load="medium",
            future_metrics={"burnout": 0.35, "failure": 0.25, "performance": 0.7, "overwhelm": 0.2},
            outcome="success",
            reason=f"optimizer_tune_{idx}",
        )


def operator_overwhelm(agent: TemporalQuantumAgent) -> None:
    print("\n[4] Operator overwhelm spikes")
    for idx in range(2):
        run_step(
            agent,
            requested_persona="Forgebinder",
            task_intent="stabilize ops",
            risk="medium",
            load="high",
            future_metrics={"burnout": 0.5, "failure": 0.35, "performance": 0.25, "overwhelm": 0.75},
            outcome="partial",
            reason=f"overwhelm_{idx}",
        )


def main():
    agent = TemporalQuantumAgent()
    show_frame(agent, "Bootstrap")
    rapid_gremlin_loop(agent)
    repeated_slappy_failures(agent)
    optimizer_tuning(agent)
    operator_overwhelm(agent)


if __name__ == "__main__":
    main()
