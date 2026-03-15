"""
MPF registry loader.

Provides a minimal reader for the MPF registry file (`JL_Agents.mpf.json`).
The loader returns a mapping of display names to MPFProfile objects so the UI
can build its jl-agent menu without scanning the folder directly.
"""

from dataclasses import dataclass, field
import json
import os
from pathlib import Path
from typing import Dict, List, Optional


@dataclass
class MPFProfile:
    """Represents a single entry from the MPF registry."""

    jl_agent_file: str
    default_memory_mode: Optional[str] = None
    default_backend_id: Optional[str] = None
    drive_type: Optional[str] = None
    tags: List[str] = field(default_factory=list)
    schema_version: Optional[str] = None
    schema_url: Optional[str] = None
    aliases: List[str] = field(default_factory=list)

    @property
    def agent_file(self) -> str:
        """Backward-compatible alias for legacy callers."""
        return self.jl_agent_file


REQUIRED_BASELINE_AGENTS = ("SparkByte", "The Gremlin", "Slappy")
CANONICAL_RUNTIME_REGISTRY = (
    Path(__file__).resolve().parents[3] / "jl_engine_core" / "data" / "agents" / "JL_Agents.mpf.json"
)



def _resolve_registry_path(registry_path: str) -> str:
    """Resolve registry path with support for `.mpf.json` and `.mpf` variants."""
    resolved_path = (
        registry_path if os.path.isabs(registry_path) else os.path.join(os.getcwd(), registry_path)
    )
    if os.path.exists(resolved_path):
        return resolved_path

    alternates: list[str] = []
    if resolved_path.endswith(".mpf.json"):
        alternates.append(resolved_path[: -len(".json")])
    elif resolved_path.endswith(".mpf"):
        alternates.append(f"{resolved_path}.json")

    for alt in alternates:
        if os.path.exists(alt):
            return alt
    return resolved_path


def _build_profiles(raw_registry: dict) -> Dict[str, MPFProfile]:
    profiles: Dict[str, MPFProfile] = {}
    for display_name, entry in raw_registry.items():
        if not isinstance(entry, dict):
            print(f"[MPF] Skipping '{display_name}' - entry must be an object.")
            continue

        jl_agent_file = entry.get("jl_agent_file") or entry.get("agent_file")
        if not jl_agent_file:
            print(f"[MPF] Skipping '{display_name}' - missing 'jl_agent_file'.")
            continue

        profiles[display_name] = MPFProfile(
            jl_agent_file=jl_agent_file,
            default_memory_mode=entry.get("default_memory_mode"),
            default_backend_id=entry.get("default_backend_id"),
            drive_type=entry.get("drive_type"),
            tags=entry.get("tags") or [],
            schema_version=entry.get("schema_version"),
            schema_url=entry.get("schema_url"),
            aliases=entry.get("aliases") or [],
        )
    return profiles


def _read_registry_file(path: str) -> dict:
    try:
        with open(path, "r", encoding="utf-8") as f:
            payload = json.load(f)
    except Exception as exc:
        print(f"[MPF] Failed to read registry '{path}': {exc}")
        return {}
    if not isinstance(payload, dict):
        print(f"[MPF] Invalid registry format in '{path}' (expected an object).")
        return {}
    return payload


def _merge_required_baseline_agents(profiles: Dict[str, MPFProfile]) -> Dict[str, MPFProfile]:
    missing = [name for name in REQUIRED_BASELINE_AGENTS if name not in profiles]
    if not missing:
        return profiles

    if not CANONICAL_RUNTIME_REGISTRY.exists():
        print(
            "[MPF] Missing required baseline agents "
            f"{missing}, and canonical registry not found at '{CANONICAL_RUNTIME_REGISTRY}'."
        )
        return profiles

    canonical_raw = _read_registry_file(str(CANONICAL_RUNTIME_REGISTRY))
    canonical_profiles = _build_profiles(canonical_raw)
    for name in missing:
        profile = canonical_profiles.get(name)
        if profile is None:
            print(f"[MPF] Required baseline agent '{name}' missing from canonical runtime registry.")
            continue
        profiles[name] = profile
    return profiles


def load_mpf_registry(registry_path: str) -> Dict[str, MPFProfile]:
    """
    Load an MPF registry JSON file.

    Args:
        registry_path: Path to the registry JSON file (relative or absolute).

    Returns:
        A dict mapping display name -> MPFProfile.
    """
    if not registry_path:
        print("[MPF] No registry path provided.")
        return {}

    resolved_path = _resolve_registry_path(registry_path)

    if not os.path.exists(resolved_path):
        print(f"[MPF] Registry file not found at '{resolved_path}', using canonical runtime registry.")
        raw_registry = _read_registry_file(str(CANONICAL_RUNTIME_REGISTRY))
    else:
        raw_registry = _read_registry_file(resolved_path)

    profiles = _build_profiles(raw_registry)
    profiles = _merge_required_baseline_agents(profiles)

    print(f"[MPF] Loaded {len(profiles)} jl-agent profiles from '{resolved_path}'")
    return profiles
