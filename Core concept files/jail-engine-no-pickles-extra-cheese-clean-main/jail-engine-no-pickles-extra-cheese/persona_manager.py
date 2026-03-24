from __future__ import annotations

"""
persona_manager.py - Lightweight persona blender for JL Engine.

Keeps the active persona data, exposes a slowly drifting trait weight, and can
merge overlapping attributes from a secondary persona when the supervisor
identifies a multi-state fit. The manager is intentionally minimal to avoid
rewriting the persona system; it feeds a blended projection back to the
orchestrator for prompt construction.
"""

import os
from copy import deepcopy
from typing import Any, Dict, Optional

from logging_setup import get_logger
from framework.mpf.binary_io import load_mpf

logger = get_logger(__name__)


def _clamp(val: float, lo: float = 0.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, val))


class PersonaManager:
    def __init__(self) -> None:
        self.active_name: str | None = None
        self.base_data: Dict[str, Any] = {}
        self.secondary_data: Dict[str, Any] | None = None
        self.dynamic_trait_weight: float = 0.5

    def set_active_persona(self, name: str, data: Dict[str, Any], registry: Dict[str, Any] | None = None) -> None:
        """Attach the active persona and opportunistically cache a related profile for blending."""
        self.active_name = name
        self.base_data = data or {}
        self.secondary_data = self._find_related_persona(name, registry) if registry else None
        self.dynamic_trait_weight = 0.5

    def _find_related_persona(self, name: str, registry: Dict[str, Any]) -> Dict[str, Any] | None:
        """Pick a neighboring persona (shared tag/drive) for blending if available."""
        try:
            for display_name, profile in (registry or {}).items():
                if display_name == name:
                    continue
                tags = set((getattr(profile, "tags", None) or []))
                if self.base_data:
                    base_tags = set(self.base_data.get("tags", []) or [])
                    if base_tags and tags and base_tags.intersection(tags):
                        candidate_file = getattr(profile, "persona_file", None)
                        if candidate_file:
                            persona_path = os.path.join("personas", candidate_file)
                            if os.path.exists(persona_path):
                                return dict(load_mpf(persona_path))
        except Exception as exc:
            logger.debug("[PersonaManager] Unable to find related persona: %s", exc)
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

    def _merge_traits(self, base: Dict[str, Any], secondary: Dict[str, Any], weight: float) -> Dict[str, Any]:
        """Combine overlapping persona traits using the supplied weight."""
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

    def get_projection(self, intent: str | None = None) -> Dict[str, Any]:
        """
        Return a blended persona dict without mutating the underlying files.
        Includes a `dynamic_trait_weight` for downstream prompt builders.
        If intent is provided, filters traits for token efficiency (Dynamic Context Injection).
        """
        persona = deepcopy(self.base_data)
        persona["dynamic_trait_weight"] = round(self.dynamic_trait_weight, 3)
        
        # 1) Blending logic
        if self.secondary_data and self.dynamic_trait_weight > 0.05:
            persona["operational_behavioral_traits"] = self._merge_traits(
                self.base_data,
                self.secondary_data,
                self.dynamic_trait_weight,
            )

        # 2) Intent-based filtering (Dynamic Context Injection)
        if intent:
            raw_traits = persona.get("operational_behavioral_traits") or {}
            persona["operational_behavioral_traits"] = self._filter_traits_by_intent(raw_traits, intent)

        return persona

    def _filter_traits_by_intent(self, traits: Dict[str, Any], intent: str) -> Dict[str, Any]:
        """
        Reduces persona trait count based on the current user intent.
        Prioritizes technical traits for 'technical' intent, creative for 'creative', etc.
        """
        if not traits:
            return {}

        intent_lower = intent.lower()
        
        # Define keyword sets for filtering
        keywords = {
            "technical": {"technical", "logic", "code", "debug", "precise", "accuracy", "math", "reasoning", "syntax", "rules", "structure", "efficiency"},
            "creative": {"creative", "chaos", "metaphor", "humor", "playful", "mischief", "sass", "story", "invention", "wild", "unconvention", "energy"},
            "chat": {"conversation", "empathy", "supportive", "friendly", "informal", "casual", "chat", "listening", "rapport"}
        }

        # If it's a known broad category, we filter. Otherwise, we keep all (or a default subset).
        target_set = set()
        for cat, kw_set in keywords.items():
            if cat in intent_lower:
                target_set.update(kw_set)

        if not target_set:
            # Fallback: if no specific intent matches, we don't filter or we keep a general subset
            return traits

        def _filter_list(items: list[str]) -> list[str]:
            if not items:
                return []
            # Prioritize items that contain target keywords
            matches = [item for item in items if any(kw in item.lower() for kw in target_set)]
            others = [item for item in items if item not in matches]
            
            # Return all matches + a few 'personality' anchors to maintain flavor
            # We limit to 3 matches and 1 other to stay token-efficient
            return (matches[:3] + others[:1])[:4]

        filtered = {
            "positive": _filter_list(traits.get("positive", [])),
            "negative": _filter_list(traits.get("negative", [])),
            "boundaries": traits.get("boundaries", []),  # Always keep boundaries for safety
            "dynamic_weight": traits.get("dynamic_weight", 0.5)
        }
        return filtered
