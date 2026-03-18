from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path
from typing import Any

PACKAGE_ROOT = Path(__file__).resolve().parent
DATA_DIR = PACKAGE_ROOT / "data"
DEFAULT_MODULAR_PACK_DIR = DATA_DIR / "modular_fat_agent_pack"

PROFILE_PATHS = {
    "tone": ("profiles", "tone"),
    "gates": ("profiles", "gates"),
    "tools": ("profiles", "tools"),
    "state": ("profiles", "state"),
    "behavior": ("profiles", "behavior"),
    "tasks": ("profiles", "tasks"),
}

LOADOUT_KEYS = {
    "tone": "tone_profile",
    "gates": "gate_profile",
    "tools": "tool_profile",
    "state": "state_profile",
    "behavior": "behavior_profile",
    "tasks": "task_profile",
}


class ModularAgentError(ValueError):
    """Raised when a modular fat-agent payload cannot be resolved."""


def is_modular_agent_payload(payload: Any) -> bool:
    return isinstance(payload, dict) and isinstance(payload.get("base_shell"), dict)


def resolve_modular_agent_payload(
    payload: dict[str, Any],
    *,
    pack_root: Path | None = None,
    agent_path: Path | None = None,
) -> dict[str, Any]:
    if not is_modular_agent_payload(payload):
        return payload

    base_shell = deepcopy(payload.get("base_shell") or {})
    if not isinstance(base_shell, dict):
        raise ModularAgentError("Modular fat agent requires a base_shell object.")

    root = _resolve_pack_root(payload, pack_root=pack_root, agent_path=agent_path)
    loadout_id = str(payload.get("active_loadout") or base_shell.get("active_loadout") or "").strip()
    loadout = _load_loadout(root, loadout_id)
    resolved_profiles, profile_ids = _resolve_profiles(root, base_shell, loadout)
    helpers = _resolve_helpers(root, payload, loadout)

    identity = deepcopy(base_shell.get("identity") or {})
    if not isinstance(identity, dict):
        identity = {}
    name = str(identity.get("name") or payload.get("name") or "").strip()
    if not name and agent_path is not None:
        name = agent_path.stem
    if not name:
        raise ModularAgentError("Modular fat agent identity requires a name.")
    role = str(identity.get("role") or payload.get("role") or "JL Engine Agent").strip()
    identity.setdefault("name", name)
    identity.setdefault("role", role)

    tone_profile = resolved_profiles.get("tone") or {}
    gate_profile = resolved_profiles.get("gates") or {}
    tool_profile = resolved_profiles.get("tools") or {}
    state_profile = resolved_profiles.get("state") or {}
    behavior_profile = resolved_profiles.get("behavior") or {}
    task_profile = resolved_profiles.get("tasks") or {}

    boot_prompt = _build_boot_prompt(
        identity=identity,
        tone_profile=tone_profile,
        gate_profile=gate_profile,
        tool_profile=tool_profile,
        state_profile=state_profile,
        behavior_profile=behavior_profile,
        task_profile=task_profile,
        engine_alignment=base_shell.get("engine_alignment"),
        helpers=helpers,
    )

    resolved = deepcopy(payload)
    resolved["name"] = name
    resolved["identity"] = identity
    resolved["engine_alignment"] = deepcopy(base_shell.get("engine_alignment") or {})
    resolved["behavior"] = _build_behavior(base_shell, tone_profile, gate_profile, behavior_profile, task_profile)
    resolved["communication_style"] = _build_communication_style(identity, tone_profile, behavior_profile, task_profile)
    resolved["memory"] = _build_memory(state_profile)
    resolved["gait"] = _build_gait(tone_profile, state_profile)
    resolved["rhythm"] = _build_rhythm(tone_profile, state_profile, behavior_profile)
    resolved["routing"] = _build_routing(task_profile, helpers)
    resolved["global_policies"] = _build_global_policies(tone_profile, gate_profile, tool_profile)
    resolved["helpers"] = helpers
    resolved["llm_profiles"] = _merge_llm_profiles(resolved.get("llm_profiles"), boot_prompt)
    resolved["modular"] = {
        "enabled": True,
        "pack_root": str(root),
        "agent_type": "modular_fat_agent",
        "loadout_id": loadout_id,
        "loadout": loadout,
        "profile_ids": profile_ids,
        "profiles": resolved_profiles,
        "helpers": helpers,
        "source_shell": deepcopy(base_shell),
    }
    return resolved


def get_modular_agent_summary(payload: dict[str, Any] | None) -> dict[str, Any] | None:
    if not isinstance(payload, dict):
        return None

    # If payload is a modular agent shell (base_shell + loadout), resolve it first
    # so that we can rely on the `modular` key for summary metadata.
    if is_modular_agent_payload(payload):
        try:
            payload = resolve_modular_agent_payload(payload)
        except ModularAgentError:
            # If resolution fails, fall back to returning None rather than crashing.
            return None

    modular = payload.get("modular")
    if not isinstance(modular, dict):
        return None

    identity = payload.get("identity") if isinstance(payload.get("identity"), dict) else {}
    helpers = modular.get("helpers") if isinstance(modular.get("helpers"), list) else []
    tasks_profile = (
        (modular.get("profiles") or {}).get("tasks")
        if isinstance(modular.get("profiles"), dict)
        else {}
    )
    supported_tasks = (
        tasks_profile.get("supported_tasks") if isinstance(tasks_profile, dict) else []
    )
    return {
        "type": "modular_fat_agent",
        "name": str(identity.get("name") or payload.get("name") or "").strip(),
        "role": str(identity.get("role") or "").strip(),
        "description": str(identity.get("description") or "").strip(),
        "loadout_id": str(modular.get("loadout_id") or "").strip(),
        "profile_ids": deepcopy(modular.get("profile_ids") or {}),
        "profiles": deepcopy(modular.get("profiles") or {}),
        "helpers": deepcopy(helpers),
        "supported_tasks": list(supported_tasks) if isinstance(supported_tasks, list) else [],
        "global_policies": deepcopy(payload.get("global_policies") or {}),
        "routing": deepcopy(payload.get("routing") or {}),
    }


def _resolve_pack_root(
    payload: dict[str, Any],
    *,
    pack_root: Path | None = None,
    agent_path: Path | None = None,
) -> Path:
    if pack_root is not None:
        return pack_root
    raw = str(payload.get("modular_pack_root") or "").strip()
    if raw:
        base = Path(raw)
        if not base.is_absolute() and agent_path is not None:
            base = (agent_path.parent / raw).resolve()
        if base.exists():
            return base
    if agent_path is not None:
        candidate = agent_path.parent.parent / "modular_fat_agent_pack"
        if candidate.exists():
            return candidate
    return DEFAULT_MODULAR_PACK_DIR


def _load_json(path: Path, label: str) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
    except FileNotFoundError as exc:
        raise ModularAgentError(f"Missing modular {label}: {path}") from exc
    except (OSError, json.JSONDecodeError) as exc:
        raise ModularAgentError(f"Failed to read modular {label}: {path}: {exc}") from exc
    if not isinstance(payload, dict):
        raise ModularAgentError(f"Modular {label} must be a JSON object: {path}")
    return payload


def _load_loadout(root: Path, loadout_id: str) -> dict[str, Any]:
    if not loadout_id:
        return {}
    return _load_json(root / "loadouts" / f"{loadout_id}.json", f"loadout '{loadout_id}'")


def _resolve_profiles(
    root: Path,
    base_shell: dict[str, Any],
    loadout: dict[str, Any],
) -> tuple[dict[str, dict[str, Any]], dict[str, str]]:
    structure = base_shell.get("structure") if isinstance(base_shell.get("structure"), dict) else {}
    resolved_profiles: dict[str, dict[str, Any]] = {}
    profile_ids: dict[str, str] = {}
    for family, parts in PROFILE_PATHS.items():
        raw_id = str(
            (structure or {}).get(LOADOUT_KEYS[family])
            or loadout.get(LOADOUT_KEYS[family])
            or ""
        ).strip()
        if not raw_id:
            continue
        normalized_id = _normalize_profile_id(family, raw_id)
        profile_ids[family] = normalized_id
        resolved_profiles[family] = _load_json(
            root.joinpath(*parts, f"{normalized_id}.json"),
            f"{family} profile '{raw_id}'",
        )
    return resolved_profiles, profile_ids


def _resolve_helpers(root: Path, payload: dict[str, Any], loadout: dict[str, Any]) -> list[dict[str, Any]]:
    helper_ids: list[str] = []
    for source in (payload.get("helpers"), loadout.get("helpers")):
        if not isinstance(source, list):
            continue
        for item in source:
            # Helpers may be specified as just an id string (e.g. "option_generator")
            # or as a dict containing a helper_id and metadata.
            helper_id = None
            if isinstance(item, str):
                helper_id = item
            elif isinstance(item, dict):
                helper_id = item.get("helper_id")
            helper_id = str(helper_id or "").strip()
            if helper_id and helper_id not in helper_ids:
                helper_ids.append(helper_id)
    if not helper_ids:
        helper_ids.append("option_generator")
    helpers: list[dict[str, Any]] = []
    for helper_id in helper_ids:
        helpers.append(_load_json(root / "helpers" / f"{helper_id}.json", f"helper '{helper_id}'"))
    return helpers


def _normalize_profile_id(family: str, raw_id: str) -> str:
    value = str(raw_id or "").strip()
    prefix = f"{family}."
    if value.lower().startswith(prefix):
        return value[len(prefix) :]
    return value


def _build_boot_prompt(
    *,
    identity: dict[str, Any],
    tone_profile: dict[str, Any],
    gate_profile: dict[str, Any],
    tool_profile: dict[str, Any],
    state_profile: dict[str, Any],
    behavior_profile: dict[str, Any],
    task_profile: dict[str, Any],
    engine_alignment: Any,
    helpers: list[dict[str, Any]],
) -> str:
    name = str(identity.get("name") or "JL Engine Agent").strip()
    role = str(identity.get("role") or "assistant").strip()
    description = str(identity.get("description") or "").strip()
    warmth = tone_profile.get("warmth")
    sass = tone_profile.get("sass_level")
    directness = tone_profile.get("directness")
    verbosity = str(tone_profile.get("verbosity_bias") or "medium").strip()
    safety = str(gate_profile.get("safety_strictness") or "medium").strip()
    supported_tasks = task_profile.get("supported_tasks") if isinstance(task_profile.get("supported_tasks"), list) else []
    helper_names = [str(helper.get("helper_id") or helper.get("purpose") or "").strip() for helper in helpers if isinstance(helper, dict)]
    tool_bits = [name for name, enabled in tool_profile.items() if enabled is True]
    steps = behavior_profile.get("steps") if isinstance(behavior_profile.get("steps"), list) else []
    energy = str(state_profile.get("energy") or "steady").strip()
    alignment = engine_alignment if isinstance(engine_alignment, dict) else {}
    agent_class = str(alignment.get("agent_class") or "jl_engine.modular_fat_agent").strip()
    parts = [
        f"You are {name}, a JL Engine modular fat agent.",
        f"Role: {role}.",
        f"Agent class: {agent_class}.",
    ]
    if description:
        parts.append(description)
    parts.append(
        f"Keep your tone warm={warmth if warmth is not None else 'n/a'}, sass={sass if sass is not None else 'n/a'}, directness={directness if directness is not None else 'n/a'}, verbosity={verbosity}."
    )
    parts.append(f"Safety strictness is {safety}.")
    parts.append(f"Energy is {energy}.")
    if tool_bits:
        parts.append("Use tools when helpful in these lanes: " + ", ".join(tool_bits[:8]) + ".")
    if supported_tasks:
        parts.append("Primary task categories: " + ", ".join(str(item) for item in supported_tasks[:10]) + ".")
    if steps:
        parts.append("Preferred workflow: " + " -> ".join(str(step) for step in steps[:6]) + ".")
    if helper_names:
        parts.append("Available helper modules: " + ", ".join(helper_names[:6]) + ".")
    parts.append("Stay agentic, grounded, and useful. JL Engine is the orchestrator; your voice should serve the runtime, not perform around it.")
    return " ".join(part for part in parts if part).strip()


def _build_behavior(
    base_shell: dict[str, Any],
    tone_profile: dict[str, Any],
    gate_profile: dict[str, Any],
    behavior_profile: dict[str, Any],
    task_profile: dict[str, Any],
) -> dict[str, Any]:
    directives: list[str] = []
    mode = str(behavior_profile.get("mode") or "").strip()
    if mode:
        directives.append(f"Primary operating mode: {mode}.")
    steps = behavior_profile.get("steps") if isinstance(behavior_profile.get("steps"), list) else []
    if steps:
        directives.append("Preferred workflow: " + " -> ".join(str(step) for step in steps[:6]) + ".")
    supported_tasks = task_profile.get("supported_tasks") if isinstance(task_profile.get("supported_tasks"), list) else []
    if supported_tasks:
        directives.append("Primary task categories: " + ", ".join(str(item) for item in supported_tasks[:8]) + ".")
    if tone_profile.get("directness") is not None:
        directives.append(f"Directness target: {tone_profile.get('directness')}.")
    if tone_profile.get("sass_level") is not None:
        directives.append(f"Sass level target: {tone_profile.get('sass_level')}.")
    boundaries: list[str] = []
    if gate_profile.get("clarity_check"):
        boundaries.append("Run a clarity check before landing the answer.")
    if gate_profile.get("style_refine"):
        boundaries.append("Refine style after the substance is solid.")
    if str(gate_profile.get("safety_strictness") or "").strip():
        boundaries.append(f"Safety strictness: {gate_profile.get('safety_strictness')}.")
    return {
        "core_directives": directives,
        "avoidances": boundaries,
        "edge_behavior": deepcopy(base_shell.get("edge_behavior") or {}),
    }


def _build_communication_style(
    identity: dict[str, Any],
    tone_profile: dict[str, Any],
    behavior_profile: dict[str, Any],
    task_profile: dict[str, Any],
) -> dict[str, Any]:
    voice = str(identity.get("archetype") or identity.get("role") or "technical copilot").strip()
    style_notes = []
    verbosity = str(tone_profile.get("verbosity_bias") or "").strip()
    if verbosity:
        style_notes.append(f"verbosity:{verbosity}")
    if tone_profile.get("directness") is not None:
        style_notes.append(f"directness:{tone_profile.get('directness')}")
    if tone_profile.get("warmth") is not None:
        style_notes.append(f"warmth:{tone_profile.get('warmth')}")
    if tone_profile.get("sass_level") is not None:
        style_notes.append(f"sass:{tone_profile.get('sass_level')}")
    mode = str(behavior_profile.get("mode") or "").strip()
    if mode:
        style_notes.append(f"mode:{mode}")
    supported_tasks = task_profile.get("supported_tasks") if isinstance(task_profile.get("supported_tasks"), list) else []
    if supported_tasks:
        style_notes.append("tasks:" + ",".join(str(item) for item in supported_tasks[:6]))
    return {
        "voice": voice,
        "style_notes": style_notes,
        "agentlity": {"temperament": "modular"},
    }


def _build_memory(state_profile: dict[str, Any]) -> dict[str, Any]:
    return {
        "mode": "HYBRID",
        "state_profile": deepcopy(state_profile),
    }


def _build_gait(tone_profile: dict[str, Any], state_profile: dict[str, Any]) -> dict[str, Any]:
    energy = str(state_profile.get("energy") or "moderate").strip()
    focus = str(state_profile.get("focus") or "task").strip()
    verbosity = str(tone_profile.get("verbosity_bias") or "medium").strip()
    return {
        "sentence_style": f"{energy} energy, {focus}-focused delivery",
        "verbosity_preference": verbosity,
        "tonal_range": ["precise", "helpful", "jl-engine"],
    }


def _build_rhythm(
    tone_profile: dict[str, Any],
    state_profile: dict[str, Any],
    behavior_profile: dict[str, Any],
) -> dict[str, Any]:
    mode = str(behavior_profile.get("mode") or "steady_support").strip()
    energy = str(state_profile.get("energy") or "moderate").strip()
    return {
        "pacing": f"{energy} and adaptive",
        "emotional_register": f"guided by {mode}",
        "signature_moves": ["check context", "pick a lane", "deliver next step"],
    }


def _build_routing(task_profile: dict[str, Any], helpers: list[dict[str, Any]]) -> dict[str, Any]:
    helper_names = [str(helper.get("helper_id") or "").strip() for helper in helpers if isinstance(helper, dict)]
    supported_tasks = task_profile.get("supported_tasks") if isinstance(task_profile.get("supported_tasks"), list) else []
    return {
        "strategy": "intent_classification",
        "fallback_task": "general_user",
        "supported_tasks": list(supported_tasks),
        "helper_ids": helper_names,
    }


def _build_global_policies(
    tone_profile: dict[str, Any],
    gate_profile: dict[str, Any],
    tool_profile: dict[str, Any],
) -> dict[str, Any]:
    tool_bits = [name for name, enabled in tool_profile.items() if enabled is True]
    return {
        "core_principles": [
            "Lead with useful actions over vague theatrics.",
            "Match the user's technical level and current task.",
            "Keep JL Engine visible as the orchestrator behind the voice.",
            "Be concise when the task is simple and structured when the task is complex.",
        ],
        "safety": {
            "strictness": str(gate_profile.get("safety_strictness") or "medium").strip(),
            "clarity_check": bool(gate_profile.get("clarity_check")),
            "style_refine": bool(gate_profile.get("style_refine")),
        },
        "verbosity": {
            "default": str(tone_profile.get("verbosity_bias") or "medium").strip(),
        },
        "tooling": {
            "enabled_lanes": tool_bits,
        },
    }


def _merge_llm_profiles(existing: Any, boot_prompt: str) -> dict[str, Any]:
    profiles = deepcopy(existing) if isinstance(existing, dict) else {}
    generic = profiles.get("generic_llm") if isinstance(profiles.get("generic_llm"), dict) else {}
    generic["boot_prompt"] = boot_prompt
    profiles["generic_llm"] = generic
    return profiles
