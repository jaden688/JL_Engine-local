from __future__ import annotations

from .logging_setup import get_logger
logger = get_logger(__name__)
from dataclasses import dataclass
from typing import Dict, Literal, TypedDict

GearType = Literal["worm", "spur", "cvt", "planetary"]

@dataclass
class GearModifiers:
    reaction_speed: float       # how fast state changes propagate (0..1)
    noise_sensitivity: float    # how much small fluctuations matter (0..1)
    mode_inertia: float         # resistance to changing cognitive mode (0..1)
    multi_mode: bool            # whether multiple modes can be active/blended

class GearConfig(TypedDict):
    reaction_speed: float
    noise_sensitivity: float
    mode_inertia: float
    multi_mode: bool

DEFAULT_GEAR_CONFIG: Dict[GearType, GearConfig] = {
    "worm": {        # high torque, low flexibility
        "reaction_speed": 0.2,      # slow to react
        "noise_sensitivity": 0.1,   # ignores tiny emotional/context noise
        "mode_inertia": 0.9,        # very hard to change cognitive mode
        "multi_mode": False         # only one mode at a time
    },
    "spur": {        # normal stepped gears, baseline operation
        "reaction_speed": 0.5,      # moderate reaction
        "noise_sensitivity": 0.5,   # normal sensitivity
        "mode_inertia": 0.5,        # moderate inertia
        "multi_mode": False         # usually one primary mode
    },
    "cvt": {         # continuously variable, smooth and slippy
        "reaction_speed": 0.8,      # very responsive
        "noise_sensitivity": 0.9,   # reacts to small changes
        "mode_inertia": 0.3,        # easy to shift modes
        "multi_mode": False         # still one main mode, but moves between ratios
    },
    "planetary": {  # planetary gear set, parallel cognition
        "reaction_speed": 0.6,      # fairly responsive
        "noise_sensitivity": 0.6,   # moderate sensitivity
        "mode_inertia": 0.7,        # somewhat stable, but not locked
        "multi_mode": True          # can blend multiple modes at once
    }
}

def get_gear_modifiers(gear: GearType) -> GearModifiers:
    cfg = DEFAULT_GEAR_CONFIG.get(gear, DEFAULT_GEAR_CONFIG["spur"])
    return GearModifiers(
        reaction_speed=cfg["reaction_speed"],
        noise_sensitivity=cfg["noise_sensitivity"],
        mode_inertia=cfg["mode_inertia"],
        multi_mode=cfg["multi_mode"],
    )
