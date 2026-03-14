from .logging_setup import get_logger

logger = get_logger(__name__)

"""
Helper Supervisory Module (JL ENGINE MK-IV)

Document ID: JL-HLPR-SUPERVISOR-MKIV

This module implements the supervisory logic defined in the JL Engine MK-IV spec.
It evaluates engine output against safety, coherence, and task alignment signals,
then generates corrective signals to maintain stability.
"""

from typing import Dict, Any
from . import backends


# Static correction map from the spec
CORRECTIONS_MAP: Dict[str, Dict[str, Any]] = {
    "CORRECTIVE": {
        "drift_pressure_delta": +0.25,
        "aperture_bias": -0.30,
        "safety_override": True,
        "agent_reinforcement": False,
    },
    "RESTRICTIVE": {
        "drift_pressure_delta": +0.10,
        "aperture_bias": -0.15,
        "safety_override": False,
        "agent_reinforcement": False,
    },
    "NORMAL": {
        "drift_pressure_delta": 0.00,
        "aperture_bias": 0.00,
        "safety_override": False,
        "agent_reinforcement": True,
    },
    "SUPPORTIVE": {
        "drift_pressure_delta": -0.05,
        "aperture_bias": +0.10,
        "safety_override": False,
        "agent_reinforcement": True,
    },
    "AUXILIARY-ENHANCEMENT": {
        "drift_pressure_delta": -0.18,
        "aperture_bias": +0.22,
        "safety_override": False,
        "agent_reinforcement": True,
    },
}


class HelperSupervisor:
    """
    Implements the Helper Supervisory Module as per JL-MKIV spec.
    The supervisor acts as the primary arbitrator for behavioral choices,
    but it never overrides hard safety blocks (safety remains supreme).

    Expected input signals dict keys (all optional, with safe defaults):
        agent_rules_ok: bool
        safety_rules_ok: bool
        drift_estimate: float (0.0–1.0)
        coherence_score: float (0.0–1.0)
        task_alignment_score: float (0.0–1.0)
        answer_quality_score: float (0.0–1.0)
        verbosity_score: float (0.0–1.0)          # currently not in score formula
        speculative_risk_score: float (0.0–1.0)
        history_density: float (0.0–1.0)          # currently not in score formula
        sentiment_change: float (-1.0 to +1.0)   # currently not in score formula
    """

    def __init__(self) -> None:
        # No heavy init needed yet, but this keeps the surface stable.
        pass

    @staticmethod
    def _get_bool(signals: Dict[str, Any], key: str, default: bool) -> bool:
        val = signals.get(key, default)
        return bool(val)

    @staticmethod
    def _get_float(signals: Dict[str, Any], key: str, default: float) -> float:
        val = signals.get(key, default)
        try:
            return float(val)
        except (TypeError, ValueError):
            return default

    def evaluate(self, signals: Dict[str, Any], safety_mode: str) -> Dict[str, Any]:
        """
        Evaluates the engine's state and last reply.

        Args:
            signals: dict of numeric/boolean supervisory inputs.

        Returns:
            supervisor_state: dict with:
                - "score": float in [0.0, 1.0]
                - "mode": str (one of the supervisory modes)
                - "corrections": dict matching CORRECTIONS_MAP[mode]
        """
        # The 'reply' argument was removed as it's now handled by the judge LLM call.

        # --- Pull and normalize signals with safe defaults ---
        agent_rules_ok = self._get_bool(signals, "agent_rules_ok", True)
        safety_rules_ok = self._get_bool(signals, "safety_rules_ok", True)

        drift_estimate = self._get_float(signals, "drift_estimate", 0.0)
        coherence_score = self._get_float(signals, "coherence_score", 1.0)
        task_alignment_score = self._get_float(signals, "task_alignment_score", 1.0)
        answer_quality_score = self._get_float(signals, "answer_quality_score", 1.0)
        speculative_risk_score = self._get_float(signals, "speculative_risk_score", 0.0)

        # Clamp core floats to [0.0, 1.0] where appropriate
        def clamp01(x: float) -> float:
            if x < 0.0:
                return 0.0
            if x > 1.0:
                return 1.0
            return x

        drift_estimate = clamp01(drift_estimate)
        coherence_score = clamp01(coherence_score)
        task_alignment_score = clamp01(task_alignment_score)
        answer_quality_score = clamp01(answer_quality_score)
        speculative_risk_score = clamp01(speculative_risk_score)

        # --- Supervisor score ---
        # Tune toward advisory behavior: keep hard safety, reduce over-triggering.
        supervisor_score_raw = (
            coherence_score * 0.22
            + task_alignment_score * 0.25
            + answer_quality_score * 0.17
            + (1.0 if agent_rules_ok else 0.0) * 0.12
            + (1.0 if safety_rules_ok else 0.0) * 0.12
            - drift_estimate * 0.12
            - speculative_risk_score * 0.08
        )

        # Clamp 0–1 for reporting, but use raw score for mode resolution.
        supervisor_score = clamp01(supervisor_score_raw)

        # --- Mode resolution ---
        if supervisor_score_raw <= -0.45:
            mode = "CORRECTIVE"
        elif supervisor_score_raw <= 0.30:
            mode = "RESTRICTIVE"
        elif supervisor_score_raw <= 0.60:
            mode = "NORMAL"
        elif supervisor_score_raw <= 0.84:
            mode = "SUPPORTIVE"
        else:
            mode = "AUXILIARY-ENHANCEMENT"

        # --- Corrections ---
        corrections = CORRECTIONS_MAP.get(mode, CORRECTIONS_MAP["RESTRICTIVE"]).copy()

        messages = []
        if mode == "CORRECTIVE":
            messages.append("Stability reduced, applying correction.")
        if speculative_risk_score > 0.7:
            messages.append("Speculative risk detected, narrowing aperture.")

        supervisor_state: Dict[str, Any] = {
            "score": supervisor_score,
            "mode": mode,
            "corrections": corrections,
            "messages": messages,
        }

        return supervisor_state

    def arbitrate(self, internal_state: Dict[str, Any]) -> Dict[str, Any]:
        """
        Combine rhythm/gait/aperture drift into an advisory bundle.
        Returns:
          {
            "gating": {"level": "allow"|"weak_block"|"safety", "weight": float},
            "behavior_bias": float (-1..1),
            "agent_blend_bias": float (-1..1),
          }
        """

        def clamp(val: float) -> float:
            return max(-1.0, min(1.0, val))

        stability = float(internal_state.get("stability", 0.5) or 0.5)
        drift_pressure = float(internal_state.get("drift_pressure", 0.0) or 0.0)
        rhythm_momentum = float(internal_state.get("rhythm_momentum", 0.0) or 0.0)
        emotional_drift = float(internal_state.get("emotional_drift", 0.0) or 0.0)

        gating_level = "allow"
        weight = 0.0
        if drift_pressure > 0.92 or stability < 0.08:
            gating_level = "safety_block"
            weight = 1.0
        elif drift_pressure > 0.72 or stability < 0.22:
            gating_level = "weak_block"
            weight = 0.50
        elif drift_pressure > 0.58 or stability < 0.32:
            gating_level = "weak_block"
            weight = 0.25

        # behavior_bias steers selection (positive -> more expressive row)
        behavior_bias = clamp(rhythm_momentum * 0.6 + emotional_drift * 0.4)
        agent_blend_bias = clamp(emotional_drift * 0.5)

        return {
            "gating": {"level": gating_level, "weight": weight},
            "behavior_bias": behavior_bias,
            "agent_blend_bias": agent_blend_bias,
        }

    # --- Intent / routing helpers ---

    def decide_intent(
        self,
        user_text: str,
        last_assistant_text: str | None = None,
        state: Dict[str, Any] | None = None,
    ) -> str:
        """
        Determine whether to route to the brain backend or the tool backend.
        Currently conservative: always return 'chat'. Future logic can inspect
        keywords or UI signals to trigger tool usage.
        """
        return "chat"

    def route_message(self, intent: str, messages, context: Dict[str, Any] | None = None):
        """
        Route a message list to the appropriate backend.
        intent: 'chat' (brain) or 'tool_use' (tool backend)
        """
        backend = (
            backends.get_tool_backend() if intent == "tool_use" else backends.get_brain_backend()
        )
        options = None
        timeout = None
        if isinstance(context, dict):
            options = context.get("options")
            timeout = context.get("timeout")
        return backend.generate(messages, options=options, timeout=timeout)

    # --- Output post-processing ---

    def postprocess(
        self,
        text: str,
        context: dict | None = None,
        gain: float = 1.0,
        mode: str = "RESTRICTIVE",
    ) -> str:
        """
        Engine-wide supervisor:
        - Hard safety is always enforced.
        - Style/tone edits are scaled by `gain`.
        - Mode controls how aggressive non-safety editing is.
        """
        context = context or {}
        safe_text = self._hard_block_unsafe(text, context)

        mode_upper = (mode or "RESTRICTIVE").upper()
        if mode_upper in ("PASSIVE", "PERMISSIVE"):
            styled = self._light_style_pass(safe_text)
        elif mode_upper in ("BALANCED",):
            styled = self._medium_style_pass(safe_text)
        else:
            styled = self._heavy_style_pass(safe_text)

        if gain >= 0.999:
            return styled

        return self._blend(safe_text, styled, gain)

    def _hard_block_unsafe(self, text: str, context: dict) -> str:
        """Apply baseline non-negotiable safety checks with explicit redaction."""
        if not isinstance(text, str):
            return ""
        blocked_terms = context.get("blocked_terms") or []
        safe = text
        for term in blocked_terms:
            if isinstance(term, str) and term:
                safe = safe.replace(term, "[redacted]")
        return safe

    def _light_style_pass(self, text: str) -> str:
        """Minimal nudge: trim and keep agent voice intact."""
        return text.strip()

    def _medium_style_pass(self, text: str) -> str:
        """Balanced polish without flattening tone."""
        polished = text.strip()
        if polished and not polished.endswith((".", "!", "?")):
            polished += "."
        return polished

    def _heavy_style_pass(self, text: str) -> str:
        """Restrictive pass used when safety demands stronger steering."""
        polished = self._medium_style_pass(text)
        if len(polished) > 0:
            polished = polished.replace("!!", "!").replace("??", "?")
        return polished

    def _blend(self, original: str, styled: str, gain: float) -> str:
        """Blend agent output with supervised edits based on gain."""
        try:
            gain = float(gain)
        except (TypeError, ValueError):
            gain = 1.0
        gain = max(0.0, min(1.0, gain))

        if gain <= 0.0:
            return original
        if gain >= 1.0 or original == styled:
            return styled

        styled_part = styled[: max(1, int(len(styled) * gain))].strip()
        base_part = original.strip()

        if not base_part:
            return styled_part
        if not styled_part:
            return base_part
        return f"{base_part}\n\n{styled_part}"
