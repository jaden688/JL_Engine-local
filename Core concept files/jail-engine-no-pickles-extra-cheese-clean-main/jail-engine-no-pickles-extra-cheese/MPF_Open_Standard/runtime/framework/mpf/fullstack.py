"""
MPF registry loader.

Provides a minimal reader for the Modular Persona Framework registry file
(`Personas.mpf.json`). The loader returns a mapping of display names to
MPFProfile objects so the UI can build its persona menu without scanning
the folder directly.
"""

from dataclasses import dataclass, field
import json
import os
from typing import Dict, List, Optional


@dataclass
class MPFProfile:
    """Represents a single entry from the MPF registry."""

    persona_file: str
    default_memory_mode: Optional[str] = None
    default_backend_id: Optional[str] = None
    drive_type: Optional[str] = None
    tags: List[str] = field(default_factory=list)


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

    resolved_path = (
        registry_path
        if os.path.isabs(registry_path)
        else os.path.join(os.getcwd(), registry_path)
    )

    if not os.path.exists(resolved_path):
        print(f"[MPF] Registry file not found at '{resolved_path}'")
        return {}

    try:
        with open(resolved_path, "r", encoding="utf-8") as f:
            raw_registry = json.load(f)
    except Exception as exc:
        print(f"[MPF] Failed to read registry '{resolved_path}': {exc}")
        return {}

    if not isinstance(raw_registry, dict):
        print(f"[MPF] Invalid registry format in '{resolved_path}' (expected an object).")
        return {}

    profiles: Dict[str, MPFProfile] = {}
    for display_name, entry in raw_registry.items():
        if not isinstance(entry, dict):
            print(f"[MPF] Skipping '{display_name}' - entry must be an object.")
            continue

        persona_file = entry.get("persona_file")
        if not persona_file:
            print(f"[MPF] Skipping '{display_name}' - missing 'persona_file'.")
            continue

        profiles[display_name] = MPFProfile(
            persona_file=persona_file,
            default_memory_mode=entry.get("default_memory_mode"),
            default_backend_id=entry.get("default_backend_id"),
            drive_type=entry.get("drive_type"),
            tags=entry.get("tags") or [],
        )

    print(f"[MPF] Loaded {len(profiles)} persona profiles from '{resolved_path}'")
    return profiles
