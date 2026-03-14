from __future__ import annotations

from .logging_setup import get_logger

logger = get_logger(__name__)
from dataclasses import dataclass
from typing import Any, Dict, Literal, TypedDict

GearType = Literal["worm", "spur", "cvt", "planetary"]


@dataclass
class GearModifiers:
    reaction_speed: float  # how fast state changes propagate (0..1)
    noise_sensitivity: float  # how much small fluctuations matter (0..1)
    mode_inertia: float  # resistance to changing cognitive mode (0..1)
    multi_mode: bool  # whether multiple modes can be active/blended


class GearConfig(TypedDict):
    reaction_speed: float
    noise_sensitivity: float
    mode_inertia: float
    multi_mode: bool


class RuntimeGearSelection(TypedDict):
    active_label: str
    runtime_gear: GearType
    reason: str


DEFAULT_GEAR_CONFIG: Dict[GearType, GearConfig] = {
    "worm": {  # high torque, low flexibility
        "reaction_speed": 0.2,  # slow to react
        "noise_sensitivity": 0.1,  # ignores tiny emotional/context noise
        "mode_inertia": 0.9,  # very hard to change cognitive mode
        "multi_mode": False,  # only one mode at a time
    },
    "spur": {  # normal stepped gears, baseline operation
        "reaction_speed": 0.5,  # moderate reaction
        "noise_sensitivity": 0.5,  # normal sensitivity
        "mode_inertia": 0.5,  # moderate inertia
        "multi_mode": False,  # usually one primary mode
    },
    "cvt": {  # continuously variable, smooth and slippy
        "reaction_speed": 0.8,  # very responsive
        "noise_sensitivity": 0.9,  # reacts to small changes
        "mode_inertia": 0.3,  # easy to shift modes
        "multi_mode": False,  # still one main mode, but moves between ratios
    },
    "planetary": {  # planetary gear set, parallel cognition
        "reaction_speed": 0.6,  # fairly responsive
        "noise_sensitivity": 0.6,  # moderate sensitivity
        "mode_inertia": 0.7,  # somewhat stable, but not locked
        "multi_mode": True,  # can blend multiple modes at once
    },
}

DEFAULT_RUNTIME_GEAR = "spur"

_CUSTOM_GEAR_ALIASES: Dict[str, GearType] = {
    "RAW_LOGIC": "worm",
    "STEPWISE": "worm",
    "QUIET_PRECISION": "worm",
    "HIGH_FIDELITY": "worm",
    "TASK_FLOW": "spur",
    "LITE_REASONING": "spur",
    "BALANCED": "spur",
    "EXPRESSIVE_SYNTH": "cvt",
    "RAPID_PROTOTYPE": "cvt",
    "SCRAP_LOGIC": "planetary",
    "CHAOS_CHAIN": "planetary",
    "BAD_IDEA_GENERATOR": "planetary",
    "SLOPPY_REASONIN": "planetary",
    "SLOPPY_REASONING": "planetary",
    "DUMB_LUCK": "planetary",
    "HALF_CORRECT_LOGIC": "spur",
}

_PRECISION_LABELS = {
    "RAW_LOGIC",
    "STEPWISE",
    "QUIET_PRECISION",
    "HIGH_FIDELITY",
}
_STRUCTURED_LABELS = {
    "TASK_FLOW",
    "LITE_REASONING",
    "BALANCED",
    "HALF_CORRECT_LOGIC",
}
_CREATIVE_LABELS = {
    "EXPRESSIVE_SYNTH",
    "RAPID_PROTOTYPE",
    "SCRAP_LOGIC",
    "CHAOS_CHAIN",
    "BAD_IDEA_GENERATOR",
    "SLOPPY_REASONIN",
    "SLOPPY_REASONING",
    "DUMB_LUCK",
}
_PRECISION_TERMS = (
    "safe",
    "safety",
    "exact",
    "precise",
    "careful",
    "critical",
    "blocked",
    "debug",
    "error",
    "trace",
    "stack",
    "risk",
    "danger",
    "destructive",
)
_STRUCTURED_TERMS = (
    "step",
    "steps",
    "plan",
    "patch",
    "build",
    "implement",
    "integrate",
    "fix",
    "workflow",
    "route",
    "task",
)
_CREATIVE_TERMS = (
    "brainstorm",
    "creative",
    "stylized",
    "style",
    "riff",
    "invent",
    "prototype",
    "concept",
    "idea",
    "explore",
)


def _normalize_token(value: Any) -> str:
    text = str(value or "").strip().upper()
    chars = [ch if ch.isalnum() else "_" for ch in text]
    normalized = "".join(chars)
    while "__" in normalized:
        normalized = normalized.replace("__", "_")
    return normalized.strip("_")


def _as_list(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    if isinstance(value, str) and value.strip():
        return [value.strip()]
    return []


def _pick_matching(labels: list[str], bucket: set[str]) -> str:
    for label in labels:
        normalized = _normalize_token(label)
        if normalized in bucket:
            return label
    return ""


def resolve_runtime_gear_type(
    label: str,
    runtime_map: Dict[str, Any] | None = None,
) -> GearType:
    normalized = _normalize_token(label)
    canonical = normalized.lower()
    if canonical in DEFAULT_GEAR_CONFIG:
        return canonical  # type: ignore[return-value]

    if isinstance(runtime_map, dict):
        for raw_key, raw_value in runtime_map.items():
            if _normalize_token(raw_key) != normalized:
                continue
            mapped = _normalize_token(raw_value).lower()
            if mapped in DEFAULT_GEAR_CONFIG:
                return mapped  # type: ignore[return-value]

    alias = _CUSTOM_GEAR_ALIASES.get(normalized)
    if alias:
        return alias

    if any(token in normalized for token in ("PRECISION", "STEP", "RAW", "LOGIC")):
        return "worm"
    if any(token in normalized for token in ("FLOW", "LITE", "BALANCE")):
        return "spur"
    if any(token in normalized for token in ("SYNTH", "PROTO", "STYLE", "EXPRESS")):
        return "cvt"
    if any(token in normalized for token in ("CHAOS", "SCRAP", "IDEA", "CHAIN", "LUCK")):
        return "planetary"
    return DEFAULT_RUNTIME_GEAR


def select_active_runtime_gear(
    agent_config: Dict[str, Any] | None,
    *,
    user_text: str = "",
    context: Dict[str, Any] | None = None,
    focus_level: float = 0.0,
    overload_level: float = 0.0,
) -> RuntimeGearSelection:
    payload = agent_config if isinstance(agent_config, dict) else {}
    gears = payload.get("cognitive_gears") if isinstance(payload.get("cognitive_gears"), dict) else {}
    preferred = _as_list(gears.get("preferred_gears"))
    fallback = _as_list(gears.get("fallback_gears"))
    runtime_map = gears.get("runtime_map") if isinstance(gears.get("runtime_map"), dict) else None
    ordered = preferred + [label for label in fallback if label not in preferred]
    if not ordered:
        return {
            "active_label": "TASK_FLOW",
            "runtime_gear": DEFAULT_RUNTIME_GEAR,
            "reason": "default",
        }

    runtime_context = context if isinstance(context, dict) else {}
    risk_level = str(
        runtime_context.get("risk_level_override")
        or runtime_context.get("risk_level")
        or ""
    ).strip().lower()
    task_intent = str(runtime_context.get("task_intent") or "").strip().lower()
    action_type = str(runtime_context.get("action_type") or "").strip().lower()
    execution_directive = str(runtime_context.get("execution_directive") or "").strip().lower()
    combined_text = " ".join(
        part for part in (user_text, task_intent, action_type, execution_directive) if part
    ).lower()

    needs_precision = (
        risk_level in {"high", "critical"}
        or overload_level >= 0.68
        or any(term in combined_text for term in _PRECISION_TERMS)
    )
    needs_creativity = any(term in combined_text for term in _CREATIVE_TERMS)
    needs_structure = (
        any(term in combined_text for term in _STRUCTURED_TERMS)
        or focus_level >= 0.55
    )

    active_label = ""
    reason = "preferred"
    if needs_precision:
        active_label = _pick_matching(fallback + ordered, _PRECISION_LABELS)
        reason = "precision"
    elif needs_creativity:
        active_label = _pick_matching(ordered + fallback, _CREATIVE_LABELS)
        reason = "creative"
    elif needs_structure:
        active_label = _pick_matching(ordered + fallback, _STRUCTURED_LABELS)
        reason = "structured"

    if not active_label:
        active_label = ordered[0]

    return {
        "active_label": active_label,
        "runtime_gear": resolve_runtime_gear_type(active_label, runtime_map),
        "reason": reason,
    }


def get_gear_modifiers(gear: GearType) -> GearModifiers:
    cfg = DEFAULT_GEAR_CONFIG.get(gear, DEFAULT_GEAR_CONFIG["spur"])
    return GearModifiers(
        reaction_speed=cfg["reaction_speed"],
        noise_sensitivity=cfg["noise_sensitivity"],
        mode_inertia=cfg["mode_inertia"],
        multi_mode=cfg["multi_mode"],
    )
