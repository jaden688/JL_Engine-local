"""Agent card to MPF conversion helpers used by the local UI."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Callable

MPF_SPEC_VERSION = "1.3.0"


def _pick_str(*values: Any, default: str = "") -> str:
    for value in values:
        if isinstance(value, str) and value.strip():
            return value.strip()
    return default


def _as_list(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(v).strip() for v in value if str(v).strip()]
    if isinstance(value, str) and value.strip():
        return [value.strip()]
    return []


def _slugify(value: str) -> str:
    cleaned = "".join(ch if ch.isalnum() or ch in ("-", "_") else "_" for ch in value.strip())
    cleaned = cleaned.strip("_")
    return cleaned or "agent"


_ALLOWED_CARD_SUFFIXES = {".json", ".mpf", ".png"}
_DEFAULT_IMPORT_FOLDERS = ("Desktop", "Documents", "Downloads")


def _is_relative_to(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def _iter_allowed_import_roots() -> list[Path]:
    candidates = [Path.cwd()]
    home = Path.home()
    candidates.extend(home / folder for folder in _DEFAULT_IMPORT_FOLDERS)
    roots: list[Path] = []
    seen: set[str] = set()
    for candidate in candidates:
        try:
            resolved = candidate.resolve()
        except Exception:
            continue
        key = str(resolved).lower()
        if key in seen:
            continue
        seen.add(key)
        roots.append(resolved)
    return roots


def _path_within_allowed_roots(path: Path) -> bool:
    return any(_is_relative_to(path, root) for root in _iter_allowed_import_roots())


def resolve_safe_import_path(path: Path, *, allowed_suffixes: set[str]) -> Path:
    resolved = Path(path).expanduser().resolve()
    if resolved.suffix.lower() not in allowed_suffixes:
        raise ValueError(f"Unsupported card format: {resolved.suffix}")
    if not resolved.is_file():
        raise FileNotFoundError(f"Card file not found: {resolved}")
    if not _path_within_allowed_roots(resolved):
        raise ValueError("path_outside_allowed_import_roots")
    return resolved


def _safe_card_path(path: Path) -> Path:
    """Resolve and validate a card file path before reading."""
    return resolve_safe_import_path(path, allowed_suffixes=_ALLOWED_CARD_SUFFIXES)


def load_card(path: Path) -> dict[str, Any]:
    path = _safe_card_path(Path(path))

    suffix = path.suffix.lower()
    if suffix in {".json", ".mpf"}:
        return json.loads(path.read_text(encoding="utf-8"))

    if suffix == ".png":
        sidecar = path.with_suffix(".json")
        if sidecar.exists():
            return json.loads(sidecar.read_text(encoding="utf-8"))
        # Minimal fallback for image-only cards.
        name = path.stem.replace("_", " ").strip() or "Imported Agent"
        return {
            "identity": {"name": name, "role": "Agent"},
            "meta": {"source_file": str(path), "card_spec": "image_only"},
        }

    raise ValueError(f"Unsupported card format: {path.suffix}")


def normalizeAgentInput(card_or_agent: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(card_or_agent, dict):
        raise TypeError("Agent input must be an object.")

    identity = card_or_agent.get("identity") or {}
    behavior = card_or_agent.get("behavior") or {}
    comms = card_or_agent.get("communication_style") or {}
    gait = card_or_agent.get("gait") or {}
    rhythm = card_or_agent.get("rhythm") or {}
    memory = card_or_agent.get("memory") or {}
    aperture = card_or_agent.get("aperture") or {}
    meta = card_or_agent.get("meta") or {}

    name = _pick_str(
        identity.get("name"),
        card_or_agent.get("display_name"),
        card_or_agent.get("name"),
        default="Unnamed Agent",
    )
    role = _pick_str(
        identity.get("role"),
        card_or_agent.get("role"),
        default="Agent",
    )
    description = _pick_str(
        identity.get("description"),
        card_or_agent.get("description"),
        behavior.get("scenario"),
        default=f"{name} operates as {role}.",
    )

    directives = _as_list(
        behavior.get("core_directives")
        or behavior.get("directives")
        or behavior.get("rules")
        or behavior.get("constraints")
    )
    boundaries = _as_list(behavior.get("avoidances") or behavior.get("boundaries"))
    tags = _as_list(identity.get("tags") or card_or_agent.get("tags"))

    llm_profiles = card_or_agent.get("llm_profiles")
    if not isinstance(llm_profiles, dict):
        base_prompt = _pick_str(card_or_agent.get("base_prompt"))
        llm_profiles = (
            {"generic_llm": {"boot_prompt": base_prompt}}
            if base_prompt
            else {"generic_llm": {"boot_prompt": ""}}
        )

    normalized = {
        "mpf_spec_version": MPF_SPEC_VERSION,
        "identity": {
            "name": name,
            "role": role,
            "archetype": _pick_str(identity.get("archetype")),
            "description": description,
            "tags": tags,
        },
        "communication_style": {
            "voice": _pick_str(comms.get("voice"), identity.get("voice")),
            "agentlity": comms.get("agentlity") or {},
            "style_notes": _as_list(comms.get("style_notes")),
        },
        "behavior": {
            "directives": directives,
            "boundaries": boundaries,
            "tone": _pick_str(behavior.get("tone"), behavior.get("style")),
            "scenario": _pick_str(behavior.get("scenario")),
        },
        "gait": {
            "default": _pick_str(gait.get("default"), card_or_agent.get("default_gait"), default="walk")
        },
        "rhythm": {
            "default": _pick_str(rhythm.get("default"), rhythm.get("mode"), default="flop")
        },
        "memory": {
            "mode": _pick_str(
                memory.get("mode"),
                card_or_agent.get("default_memory_mode"),
                default="HYBRID",
            )
        },
        "aperture": {
            "mode": _pick_str(aperture.get("mode"), aperture.get("safety"), default="balanced")
        },
        "meta": {
            "source_file": _pick_str(meta.get("source_file")),
            "card_spec": _pick_str(meta.get("card_spec"), default="local_card"),
            "version": _pick_str(meta.get("version"), default="1.0"),
        },
        "llm_profiles": llm_profiles,
    }

    for passthrough_key in (
        "engine_alignment",
        "cognitive_gears",
        "cognitive_modes",
        "emotion_palette",
        "operational_behavioral_traits",
        "flip_flop_modes",
        "behavioral_core",
    ):
        if passthrough_key in card_or_agent:
            normalized[passthrough_key] = card_or_agent[passthrough_key]

    return normalized


def inferEmotionalPosture(normalized: dict[str, Any]) -> dict[str, Any]:
    agentlity = ((normalized.get("communication_style") or {}).get("agentlity")) or {}
    temperament = ""
    if isinstance(agentlity, dict):
        temperament = _pick_str(agentlity.get("temperament"))
    elif isinstance(agentlity, str):
        temperament = agentlity.strip()
    temperament_l = temperament.lower()

    valence = 0.5
    arousal = 0.5
    if any(k in temperament_l for k in ("aggressive", "intense", "fierce")):
        arousal = 0.72
    elif any(k in temperament_l for k in ("stoic", "calm", "gentle")):
        arousal = 0.35
    if any(k in temperament_l for k in ("cheerful", "optimistic", "playful")):
        valence = 0.7
    elif any(k in temperament_l for k in ("grim", "anxious", "cold")):
        valence = 0.35
    return {
        "temperament": temperament or "neutral",
        "valence": round(valence, 2),
        "arousal": round(arousal, 2),
    }


def normalizeFinal(normalized: dict[str, Any]) -> dict[str, Any]:
    payload = normalizeAgentInput(normalized)
    emotional_posture = normalized.get("emotional_posture")
    if not isinstance(emotional_posture, dict):
        emotional_posture = inferEmotionalPosture(payload)
    payload["emotional_posture"] = emotional_posture
    return payload


def normalize_card(card: dict[str, Any]) -> tuple[dict[str, Any], list[str]]:
    warnings: list[str] = []
    normalized = normalizeAgentInput(card)
    if not _pick_str((normalized.get("identity") or {}).get("name")):
        warnings.append("identity.name missing; defaulted to 'Unnamed Agent'.")
    if not _pick_str((normalized.get("identity") or {}).get("role")):
        warnings.append("identity.role missing; defaulted to 'Agent'.")
    return normalizeFinal(normalized), warnings


def analyzeAgent(
    card: dict[str, Any],
    backend_fn: Callable[[list[dict[str, str]]], str] | None = None,
) -> dict[str, Any] | None:
    normalized, _warnings = normalize_card(card)
    if backend_fn is None:
        return normalized

    identity = normalized.get("identity") or {}
    if _pick_str(identity.get("description")) and len(_pick_str(identity.get("description"))) >= 24:
        return normalized
    try:
        name = _pick_str(identity.get("name"), default="This agent")
        role = _pick_str(identity.get("role"), default="assistant")
        prompt = (
            f"Write one concise agent description for {name} as a {role}. "
            "Output plain text only."
        )
        generated = backend_fn([{"role": "user", "content": prompt}])
        desc = _pick_str(generated)
        if desc:
            normalized["identity"]["description"] = desc[:280]
        return normalized
    except Exception:
        return normalized


def expandAgent(
    card_or_mpf: dict[str, Any],
    backend_fn: Callable[[list[dict[str, str]]], str] | None = None,
    mode: str = "Merge + enhance",
) -> tuple[dict[str, Any], list[str]]:
    base = normalizeFinal(card_or_mpf)
    changed: list[str] = []
    mode_l = (mode or "").lower()
    if "enhance" in mode_l and backend_fn is not None:
        try:
            name = _pick_str((base.get("identity") or {}).get("name"), default="agent")
            prompt = (
                f"Provide 3 short behavior directives for {name}. "
                "One per line. No numbering."
            )
            generated = backend_fn([{"role": "user", "content": prompt}])
            directives = [line.strip("- ").strip() for line in str(generated).splitlines() if line.strip()]
            directives = [d for d in directives if d][:3]
            if directives:
                behavior = base.setdefault("behavior", {})
                existing = _as_list(behavior.get("directives"))
                merged = existing + [d for d in directives if d not in existing]
                behavior["directives"] = merged[:6]
                changed.append("behavior.directives")
        except Exception:
            pass
    return base, changed


def convert_file(
    card_path: Path,
    output_dir: Path | None = None,
    force: bool = False,
    indent: int = 2,
) -> tuple[Path, list[str]]:
    card = load_card(Path(card_path))
    mpf, warnings = normalize_card(card)
    identity = mpf.get("identity") or {}
    name = _pick_str(identity.get("name"), default=Path(card_path).stem)
    target_dir = Path(output_dir) if output_dir else Path(card_path).resolve().parent
    target_dir.mkdir(parents=True, exist_ok=True)
    target = target_dir / f"{_slugify(name)}.mpf"
    if target.exists() and not force:
        raise FileExistsError(f"Output already exists: {target}")
    target.write_text(json.dumps(mpf, indent=max(0, int(indent)), ensure_ascii=True), encoding="utf-8")
    return target, warnings
