"""
hybrid_memory.py - JL Engine Hybrid Memory System

Provides shared and persona-specific memory for the JL Engine.
"""

from typing import Dict, Any


class HybridMemorySystem:
    def __init__(self):
        # Memory visible to all personas
        self.shared = {
            "last_active_persona": None,
            "recent_events": [],     # list of {persona, event_type, payload}
            "engine_flags": {},      # e.g. {"serial_error": True, "stressed": False}
            "user_profile": {},      # stable facts about the user if desired
        }
        # Private per-persona memory
        self.persona_store = {}      # persona_id -> dict

    def _ensure_persona(self, persona_id: str):
        if persona_id not in self.persona_store:
            self.persona_store[persona_id] = {
                "recent_interactions": [],
                "mood": "neutral",
                "notes": {},
                "dynamic_state": {},
            }

    def get_context(self, persona_id: str) -> dict:
        """
        Return the hybrid context for a given persona:
        {
          "shared_memory": { ... },
          "persona_memory": { ... }
        }
        """
        self._ensure_persona(persona_id)
        return {
            "shared_memory": self.shared,
            "persona_memory": self.persona_store[persona_id],
        }

    def note_event(self, persona_id: str, event_type: str, payload: dict | None = None):
        """
        Record a shared event that other personas can see later.
        """
        self._ensure_persona(persona_id)
        event = {
            "persona": persona_id,
            "event_type": event_type,
            "payload": payload or {},
        }
        self.shared["recent_events"].append(event)
        # keep last ~32 events
        self.shared["recent_events"] = self.shared["recent_events"][-32:]

    def update_after_turn(
        self,
        persona_id: str,
        user_message: str,
        output: str,
        engine_state: dict,
    ):
        """
        Update persona-local memory and shared quick flags after a completed turn.
        engine_state may contain:
          - "gait"
          - "rhythm"
          - "aperture_mode"
          - "flags" (dict of booleans or small values)
        """
        self._ensure_persona(persona_id)

        entry = {
            "user_message": user_message[-400:],   # trimmed for brevity
            "output": output[-400:],
            "engine_snapshot": {
                "gait": engine_state.get("gait"),
                "rhythm": engine_state.get("rhythm"),
                "aperture": engine_state.get("aperture_mode"),
                "dynamic": engine_state.get("dynamic"),
            },
        }
        self.persona_store[persona_id]["recent_interactions"].append(entry)
        # keep last ~20 interactions per persona
        self.persona_store[persona_id]["recent_interactions"] = \
            self.persona_store[persona_id]["recent_interactions"][-20:]

        self.shared["last_active_persona"] = persona_id

        flags = engine_state.get("flags", {})
        if flags:
            self.shared["engine_flags"].update(flags)

        # Persist lightweight dynamic modulation for this persona/session
        dynamic_state = engine_state.get("dynamic")
        if dynamic_state:
            self.persona_store[persona_id]["dynamic_state"] = dynamic_state
