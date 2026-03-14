from __future__ import annotations
from dataclasses import dataclass
from typing import Dict, List, Literal, Tuple
from .cognitive_gears import GearType, get_gear_modifiers

CognitiveMode = Literal[
    "balanced", "compression", "expansion", "pattern_tech", "rebinding", "high_fidelity"
]


@dataclass
class CognitiveModeState:
    active_modes: Dict[CognitiveMode, float]  # mode -> weight


class CognitiveModeSelector:
    def __init__(self, default_mode: CognitiveMode = "balanced"):
        self.default_mode = default_mode
        self.state = CognitiveModeState(active_modes={default_mode: 1.0})

    def select_modes(
        self, *, gear: GearType, focus_level: float, overload_level: float
    ) -> CognitiveModeState:
        mods = get_gear_modifiers(gear)
        # basic heuristic:
        # - high focus + low overload in worm/planetary -> high_fidelity
        # - moderate focus + cvt -> pattern_tech or expansion
        # - high overload -> compression or rebinding
        # - otherwise balanced
        modes: Dict[CognitiveMode, float] = {}

        def add(mode: CognitiveMode, weight: float):
            if weight <= 0:
                return
            modes[mode] = modes.get(mode, 0.0) + weight

        # base weight balanced on focus/overload
        if overload_level > 0.7:
            add("compression", 0.6)
            add("rebinding", 0.4)
        elif focus_level > 0.7:
            add("high_fidelity", 0.6)
            add("expansion", 0.4)
        else:
            add("balanced", 0.7)

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
        if not self.state.active_modes:
            return self.default_mode
        return max(self.state.active_modes.items(), key=lambda kv: kv[1])[0]
