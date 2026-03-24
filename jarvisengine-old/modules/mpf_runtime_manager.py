"""
MPF Runtime Manager

Bridges MPF profiles into the live JL Engine subsystems without altering their APIs.
Heuristics are lightweight and safe: missing fields fall back to current behavior.
"""

from __future__ import annotations

from typing import Dict, Optional

from framework.mpf.fullstack import MPFProfile
import backends


class MPFRuntimeManager:
    """
    Applies MPF profile settings to runtime components (aperture, behavior, gears, memory, backends).
    """

    def __init__(self, mpf_profiles: Optional[Dict[str, MPFProfile]] = None):
        self.mpf_profiles: Dict[str, MPFProfile] = mpf_profiles or {}
        self.current_profile: Optional[MPFProfile] = None
        self.current_profile_name: Optional[str] = None

    def set_profiles(self, mpf_profiles: Dict[str, MPFProfile]) -> None:
        self.mpf_profiles = mpf_profiles or {}

    def set_current_persona(self, persona_name: str) -> None:
        """Lookup by display name (case-insensitive) and cache the profile."""
        if not persona_name or not self.mpf_profiles:
            return
        match = None
        for name, profile in self.mpf_profiles.items():
            if name.lower() == persona_name.lower():
                match = (name, profile)
                break
        if match:
            self.current_profile_name, self.current_profile = match
            print(f"[MPF] Current profile set to '{self.current_profile_name}'")
        else:
            print(f"[MPF] WARN: No MPF profile found for persona '{persona_name}'.")

    def get_current_profile(self) -> Optional[MPFProfile]:
        return self.current_profile

    # --- Apply helpers ---

    def apply_to_emotional_aperture(self, emo) -> None:
        """Set drive_type from MPF profile; leave other behavior intact."""
        profile = self.get_current_profile()
        if not profile or emo is None:
            return
        if profile.drive_type and hasattr(emo, "set_drive_type"):
            try:
                emo.set_drive_type(profile.drive_type)
                print(f"[MPF] Applied profile '{self.current_profile_name}' to emotional_aperture (drive_type={profile.drive_type})")
            except Exception as exc:
                print(f"[MPF] WARN: Failed to apply drive_type to emotional_aperture: {exc}")

    def apply_to_drift_pressure(self, drift_system) -> None:
        """Placeholder hook: drift system currently has no tunable state; log only."""
        profile = self.get_current_profile()
        if profile and drift_system:
            print(f"[MPF] Applied profile '{self.current_profile_name}' to drift_pressure (no-op)")

    def apply_to_behavior_engine(self, behavior_machine) -> None:
        """Optionally bias behavior starting state based on tags."""
        profile = self.get_current_profile()
        if not profile or behavior_machine is None:
            return
        tags = [t.lower() for t in (profile.tags or [])]
        target_label = None
        if "chaotic" in tags:
            target_label = "Volatile-Erratic"
        elif "helper" in tags or "safe" in tags:
            target_label = "Supportive-Calm"
        if target_label and hasattr(behavior_machine, "set_state_by_label"):
            behavior_machine.set_state_by_label(target_label)
            print(f"[MPF] Applied profile '{self.current_profile_name}' to behavior_engine (state={target_label})")

    def apply_to_cognitive_gears(self, gears_selector) -> None:
        """Bias cognitive default mode/gear based on tags."""
        profile = self.get_current_profile()
        if not profile or gears_selector is None:
            return
        tags = [t.lower() for t in (profile.tags or [])]
        if hasattr(gears_selector, "default_mode"):
            if "builder" in tags or "chaotic" in tags:
                gears_selector.default_mode = "expansion"
            elif "helper" in tags or "safe" in tags:
                gears_selector.default_mode = "high_fidelity"
            print(f"[MPF] Applied profile '{self.current_profile_name}' to cognitive gears (default_mode={gears_selector.default_mode})")

    def apply_to_memory(self, memory_manager_or_config) -> None:
        """Hook to adjust memory mode; actual UI binding handled in main_app."""
        profile = self.get_current_profile()
        if profile and memory_manager_or_config is not None:
            print(f"[MPF] Applied profile '{self.current_profile_name}' to memory (default_mode={profile.default_memory_mode})")

    def apply_to_backends(self, backends_module) -> None:
        """Set brain backend from MPF default if provided."""
        profile = self.get_current_profile()
        if not profile or not backends_module:
            return
        backend_id = profile.default_backend_id
        if backend_id and backend_id in backends_module.BACKEND_REGISTRY:
            try:
                backends_module.set_brain_backend_id(backend_id)
                print(f"[MPF] Applied profile '{self.current_profile_name}' to backends (brain_backend={backend_id})")
            except Exception as exc:
                print(f"[MPF] WARN: Failed to set brain backend '{backend_id}': {exc}")
