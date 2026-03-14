from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Literal, Tuple

from .logging_setup import get_logger
from .cognitive_gears import GearType, get_gear_modifiers

logger = get_logger(__name__)

CognitiveMode = Literal[
    "balanced", "compression", "expansion", "pattern_tech", "rebinding", "high_fidelity"
]


@dataclass
class CognitiveModeState:
    """Snapshot of active cognitive modes and weights."""

    active_modes: Dict[CognitiveMode, float]  # mode -> weight


class CognitiveModeSelector:
    """Selects cognitive modes based on focus/overload and gear modifiers."""

    def __init__(self, default_mode: CognitiveMode = "balanced"):
        """Initialize selector with a default mode."""
        self.default_mode = default_mode
        self.state = CognitiveModeState(active_modes={default_mode: 1.0})

    def select_modes(
        self, *, gear: GearType, focus_level: float, overload_level: float
    ) -> CognitiveModeState:
        """Compute mode weights based on focus/overload signals."""
        mods = get_gear_modifiers(gear)
        # heuristic:
        # - overload drives compression/rebinding sooner (>=0.4)
        # - focus drives expansion/pattern/high_fidelity sooner (>=0.4)
        # - gear tweaks adjust blending vs single-mode
        modes: Dict[CognitiveMode, float] = {}

        def add(mode: CognitiveMode, weight: float):
            if weight <= 0:
                return
            modes[mode] = modes.get(mode, 0.0) + weight

        # base weighting from overload/focus
        if overload_level >= 0.6:
            add("compression", 0.55)
            add("rebinding", 0.35)
            add("balanced", 0.10)
        elif overload_level >= 0.4:
            add("compression", 0.40)
            add("rebinding", 0.25)
            add("balanced", 0.35)
        elif focus_level >= 0.6:
            add("high_fidelity", 0.50)
            add("expansion", 0.30)
            add("balanced", 0.20)
        elif focus_level >= 0.4:
            add("expansion", 0.35)
            add("pattern_tech", 0.25)
            add("balanced", 0.40)
        else:
            add("balanced", 0.8)

        # gear-specific tweaks
        if gear == "worm":  # very stable, deep focus bias
            if focus_level > 0.5:
                add("high_fidelity", 0.3)
        elif gear == "cvt":  # fluid, adaptive; pattern-leaning
            if focus_level > 0.4 and overload_level < 0.6:
                add("pattern_tech", 0.4)
        elif gear == "planetary":  # allow true multi-mode blending
            if mods.multi_mode:
                add("pattern_tech", 0.3)
                add("expansion", 0.3)
        elif gear == "spur":  # basic behavior, keep whatever is chosen
            pass

        # normalize weights
        total = sum(modes.values())
        if total <= 0:
            modes = {self.default_mode: 1.0}
        else:
            for k in list(modes.keys()):
                modes[k] = modes[k] / total

        self.state = CognitiveModeState(active_modes=modes)
        return self.state

    def get_dominant_mode(self) -> CognitiveMode:
        """Return the highest-weight cognitive mode."""
        if not self.state.active_modes:
            return self.default_mode
        return max(self.state.active_modes.items(), key=lambda kv: kv[1])[0]
