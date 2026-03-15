from __future__ import annotations

"""
agent_manager.py - Lightweight agent blender for JL Engine.

Keeps the active agent data, exposes a slowly drifting trait weight, and can
merge overlapping attributes from a secondary agent when the supervisor
identifies a multi-state fit. The manager is intentionally minimal to avoid
rewriting the agent system; it feeds a blended projection back to the
orchestrator for prompt construction.
"""

from copy import deepcopy
import json
from typing import Any, Dict, Optional

from .logging_setup import get_logger

logger = get_logger(__name__)


def _clamp(val: float, lo: float = 0.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, val))


class AgentManager:
    def __init__(self) -> None:
        self.active_name: str | None = None
        self.base_data: Dict[str, Any] = {}
        self.secondary_data: Dict[str, Any] | None = None
        self.dynamic_trait_weight: float = 0.5

    def set_active_agent(
        self, name: str, data: Dict[str, Any], registry: Dict[str, Any] | None = None
    ) -> None:
        """Attach the active agent and opportunistically cache a related profile for blending."""
        self.active_name = name
        self.base_data = data or {}
        self.secondary_data = self._find_related_agent(name, registry) if registry else None
        self.dynamic_trait_weight = 0.5

    def _find_related_agent(self, name: str, registry: Dict[str, Any]) -> Dict[str, Any] | None:
        """Pick a neighboring agent (shared tag/drive) for blending if available."""
        try:
            for display_name, profile in (registry or {}).items():
                if display_name == name:
                    continue
                tags = set((getattr(profile, "tags", None) or []))
                if self.base_data:
                    base_tags = set(self.base_data.get("tags", []) or [])
                    if base_tags and tags and base_tags.intersection(tags):
                        candidate_file = getattr(profile, "agent_file", None)
                        if candidate_file:
                            import json, os

                            agent_path = os.path.join("agents", candidate_file)
                            if os.path.exists(agent_path):
                                with open(agent_path, "r", encoding="utf-8") as f:
                                    return json.load(f)
        except (OSError, json.JSONDecodeError, TypeError, ValueError) as exc:
            logger.exception("[AgentManager] Unable to find related agent: %s", exc)
        return None

    def apply_supervisor_bias(self, bias: float) -> None:
        """Supervisor can gently steer trait weighting (-1..1)."""
        try:
            bias = float(bias)
        except (TypeError, ValueError):
            return
        self.dynamic_trait_weight = _clamp(self.dynamic_trait_weight + bias * 0.25, 0.0, 1.0)

    def update_dynamic_weight(
        self,
        signals: Any = None,
        rhythm_state: Optional[Dict[str, Any]] = None,
        aperture_state: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Adjust the dynamic trait blend based on current vibes."""
        sentiment = getattr(signals, "sentiment", 0.0) if signals else 0.0
        variability = 0.0
        if isinstance(rhythm_state, dict):
            variability = float(rhythm_state.get("variability", 0.0) or 0.0)
        aperture_score = 0.0
        if isinstance(aperture_state, dict):
            aperture_score = float(aperture_state.get("score", 0.0) or 0.0)

        delta = sentiment * 0.15 + variability * 0.1 + (aperture_score - 0.5) * 0.2
        self.dynamic_trait_weight = _clamp(self.dynamic_trait_weight * 0.9 + delta, 0.0, 1.0)

    def _merge_traits(
        self, base: Dict[str, Any], secondary: Dict[str, Any], weight: float
    ) -> Dict[str, Any]:
        """Combine overlapping agent traits using the supplied weight."""
        base_traits = base.get("operational_behavioral_traits") or {}
        sec_traits = secondary.get("operational_behavioral_traits") or {}

        def _merge_list(key: str) -> list:
            merged = []
            merged.extend(base_traits.get(key) or [])
            merged.extend(sec_traits.get(key) or [])
            # keep order stable but unique
            seen = set()
            uniq = []
            for item in merged:
                if item in seen:
                    continue
                seen.add(item)
                uniq.append(item)
            return uniq

        blended = {
            "positive": _merge_list("positive"),
            "negative": _merge_list("negative"),
            "boundaries": _merge_list("boundaries"),
        }
        blended["dynamic_weight"] = round(weight, 3)
        return blended

    def get_projection(self) -> Dict[str, Any]:
        """
        Return a blended agent dict without mutating the underlying files.
        Includes a `dynamic_trait_weight` for downstream prompt builders.
        """
        agent = deepcopy(self.base_data)
        agent["dynamic_trait_weight"] = round(self.dynamic_trait_weight, 3)
        if self.secondary_data and self.dynamic_trait_weight > 0.05:
            agent["operational_behavioral_traits"] = self._merge_traits(
                self.base_data,
                self.secondary_data,
                self.dynamic_trait_weight,
            )
        return agent
