"""
hybrid_memory.py - JL Engine Hybrid Memory System

Provides shared and agent-specific memory for the JL Engine, including
an abstract backend interface and a SQLite-backed implementation.
"""

from __future__ import annotations

import json
import os
import sqlite3
from difflib import SequenceMatcher
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any, Dict

from .logging_setup import get_logger

logger = get_logger(__name__)

PACKAGE_ROOT = Path(__file__).resolve().parent
REPO_ROOT = PACKAGE_ROOT.parent
RECENT_INTERACTION_LIMIT = 12
RECENT_INTERACTION_REPEAT_WINDOW = 4
RECENT_INTERACTION_REPEAT_RATIO = 0.9
DEFAULT_MEMORY_DB_PATH = Path(
    os.getenv("JL_ENGINE_MEMORY_DB_PATH") or (REPO_ROOT / "data" / "jl_engine_memory.sqlite3")
)


def _normalize_interaction_text(text: Any) -> str:
    if not isinstance(text, str):
        return ""
    return " ".join(text.lower().split())


def _lead_sentence(text: Any) -> str:
    normalized = _normalize_interaction_text(text)
    if not normalized:
        return ""
    for marker in (".", "!", "?"):
        if marker in normalized:
            head = normalized.split(marker, 1)[0].strip()
            if head:
                return head
    return normalized


def _looks_like_synthetic_interaction(text: Any) -> bool:
    normalized = _normalize_interaction_text(text)
    if not normalized:
        return False
    synthetic_prefixes = (
        "continue assisting the user.",
        "reply with your agent name only.",
        "reply briefly and keep the conversation moving.",
        "tool_result for ",
    )
    if normalized.startswith(synthetic_prefixes):
        return True
    return (
        "return only json." in normalized
        and "available tools:" in normalized
        and "you are a local interpreter." in normalized
    )


def _generic_capability_signature(text: Any) -> str:
    normalized = _normalize_interaction_text(text)
    if not normalized:
        return ""
    has_jl_self_frame = "jl engine" in normalized and ("i'm " in normalized or "i am " in normalized)
    if not has_jl_self_frame:
        return ""
    markers = (
        "i can interpret your commands",
        "i can help with tasks",
        "i can assist with tasks",
        "i can provide information",
        "i can call tools",
        "i'm here to help",
        "let's see what you have in mind",
        "what's your goal",
        "what's on your mind",
        "what can i do for you today",
        "what can i help you with",
    )
    if any(marker in normalized for marker in markers):
        return "generic_capability_loop"
    return ""


def compact_recent_interactions(interactions: Any) -> list[dict[str, Any]]:
    if not isinstance(interactions, list):
        return []

    cleaned_reversed: list[dict[str, Any]] = []
    for item in reversed(interactions):
        if not isinstance(item, dict):
            continue

        user_message = str(item.get("user_message") or "").strip()[:16000]
        output = str(item.get("output") or "").strip()[:16000]
        if not user_message and not output:
            continue
        if _looks_like_synthetic_interaction(user_message):
            continue

        user_norm = _normalize_interaction_text(user_message)
        output_norm = _normalize_interaction_text(output)
        output_signature = _generic_capability_signature(output) or _lead_sentence(output)
        if output_signature == "generic_capability_loop":
            continue

        duplicate = False
        for prior in cleaned_reversed[-RECENT_INTERACTION_REPEAT_WINDOW:]:
            prior_user_norm = str(prior.get("_user_norm") or "")
            prior_output = str(prior.get("output") or "")
            prior_norm = _normalize_interaction_text(prior_output)
            prior_signature = str(prior.get("_signature") or "")
            if user_norm and prior_user_norm and user_norm == prior_user_norm:
                duplicate = True
                break
            if output_norm and prior_norm and output_norm == prior_norm:
                duplicate = True
                break
            if (
                output_signature
                and prior_signature
                and output_signature == prior_signature
                and len(output_norm) >= 40
                and len(prior_norm) >= 40
            ):
                duplicate = True
                break
            if (
                len(output_norm) >= 80
                and len(prior_norm) >= 80
                and SequenceMatcher(a=prior_norm, b=output_norm).ratio()
                >= RECENT_INTERACTION_REPEAT_RATIO
            ):
                duplicate = True
                break
        if duplicate:
            continue

        cleaned_reversed.append(
            {
                "user_message": user_message,
                "output": output,
                "engine_snapshot": (
                    item.get("engine_snapshot")
                    if isinstance(item.get("engine_snapshot"), dict)
                    else {}
                ),
                "_user_norm": user_norm,
                "_signature": output_signature,
            }
        )

    cleaned = list(reversed(cleaned_reversed[:RECENT_INTERACTION_LIMIT]))
    for item in cleaned:
        item.pop("_user_norm", None)
        item.pop("_signature", None)
    return cleaned


class HybridMemoryBackend(ABC):
    """Abstract interface for hybrid memory backends."""

    @abstractmethod
    def get_context(self, agent_id: str) -> dict:
        """Return a hybrid context for a given agent."""

    @abstractmethod
    def note_event(self, agent_id: str, event_type: str, payload: dict | None = None) -> None:
        """Record a shared event that other agents can see later."""

    @abstractmethod
    def update_after_turn(
        self,
        agent_id: str,
        user_message: str,
        output: str,
        engine_state: dict,
    ) -> None:
        """Update memory after a completed turn."""


class InMemoryHybridMemory(HybridMemoryBackend):
    """In-memory hybrid memory store for testing or fallback use."""

    def __init__(self) -> None:
        self.shared = {
            "last_active_agent": None,
            "recent_events": [],
            "engine_flags": {},
            "user_profile": {},
        }
        self.agent_store: Dict[str, dict] = {}

    def _ensure_agent(self, agent_id: str) -> None:
        if agent_id not in self.agent_store:
            self.agent_store[agent_id] = {
                "recent_interactions": [],
                "mood": "neutral",
                "notes": {},
                "dynamic_state": {},
            }

    def get_context(self, agent_id: str) -> dict:
        self._ensure_agent(agent_id)
        agent_memory = self.agent_store[agent_id]
        agent_memory["recent_interactions"] = compact_recent_interactions(
            agent_memory.get("recent_interactions")
        )
        return {
            "shared_memory": self.shared,
            "agent_memory": agent_memory,
        }

    def note_event(self, agent_id: str, event_type: str, payload: dict | None = None) -> None:
        self._ensure_agent(agent_id)
        event = {
            "agent": agent_id,
            "event_type": event_type,
            "payload": payload or {},
        }
        self.shared["recent_events"].append(event)
        self.shared["recent_events"] = self.shared["recent_events"][-32:]

    def update_after_turn(
        self,
        agent_id: str,
        user_message: str,
        output: str,
        engine_state: dict,
    ) -> None:
        self._ensure_agent(agent_id)
        entry = {
            "user_message": (user_message or "")[-16000:],
            "output": (output or "")[-16000:],
            "engine_snapshot": {
                "gait": engine_state.get("gait"),
                "rhythm": engine_state.get("rhythm"),
                "aperture": engine_state.get("aperture_mode"),
                "dynamic": engine_state.get("dynamic"),
            },
        }
        self.agent_store[agent_id]["recent_interactions"].append(entry)
        self.agent_store[agent_id]["recent_interactions"] = compact_recent_interactions(
            self.agent_store[agent_id]["recent_interactions"]
        )
        self.shared["last_active_agent"] = agent_id

        flags = engine_state.get("flags", {})
        if flags:
            self.shared["engine_flags"].update(flags)

        dynamic_state = engine_state.get("dynamic")
        if dynamic_state:
            self.agent_store[agent_id]["dynamic_state"] = dynamic_state


class SQLiteHybridMemory(HybridMemoryBackend):
    """SQLite-backed hybrid memory for persistent sessions."""

    def __init__(self, db_path: str | Path | None = None) -> None:
        raw_path = Path(db_path) if db_path else DEFAULT_MEMORY_DB_PATH
        raw_path = raw_path.expanduser()
        if not raw_path.is_absolute():
            raw_path = (REPO_ROOT / raw_path).resolve()
        self.db_path = raw_path
        self._ensure_schema()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _ensure_schema(self) -> None:
        try:
            self.db_path.parent.mkdir(parents=True, exist_ok=True)
            with self._connect() as conn:
                conn.execute(
                    """
                    CREATE TABLE IF NOT EXISTS shared_memory (
                        id TEXT PRIMARY KEY,
                        payload TEXT NOT NULL
                    )
                    """
                )
                conn.execute(
                    """
                    CREATE TABLE IF NOT EXISTS agent_memory (
                        agent_id TEXT PRIMARY KEY,
                        payload TEXT NOT NULL
                    )
                    """
                )
                conn.execute(
                    "INSERT OR IGNORE INTO shared_memory (id, payload) VALUES (?, ?)",
                    ("default", json.dumps(self._default_shared())),
                )
        except sqlite3.Error:
            logger.exception(
                "[HybridMemory] Failed to initialize SQLite schema at %s", self.db_path
            )

    def _default_shared(self) -> dict:
        return {
            "last_active_agent": None,
            "recent_events": [],
            "engine_flags": {},
            "user_profile": {},
        }

    def _default_agent(self) -> dict:
        return {
            "recent_interactions": [],
            "mood": "neutral",
            "notes": {},
            "dynamic_state": {},
        }

    def _load_shared(self) -> dict:
        try:
            with self._connect() as conn:
                row = conn.execute(
                    "SELECT payload FROM shared_memory WHERE id = ?", ("default",)
                ).fetchone()
                if row and row["payload"]:
                    return json.loads(row["payload"])
        except (sqlite3.Error, json.JSONDecodeError, TypeError):
            logger.exception("[HybridMemory] Failed to load shared memory.")
        return self._default_shared()

    def _save_shared(self, payload: dict) -> None:
        try:
            with self._connect() as conn:
                conn.execute(
                    "INSERT OR REPLACE INTO shared_memory (id, payload) VALUES (?, ?)",
                    ("default", json.dumps(payload)),
                )
        except sqlite3.Error:
            logger.exception("[HybridMemory] Failed to save shared memory.")

    def _load_agent(self, agent_id: str) -> dict:
        try:
            with self._connect() as conn:
                row = conn.execute(
                    "SELECT payload FROM agent_memory WHERE agent_id = ?",
                    (agent_id,),
                ).fetchone()
                if row and row["payload"]:
                    return json.loads(row["payload"])
        except (sqlite3.Error, json.JSONDecodeError, TypeError):
            logger.exception("[HybridMemory] Failed to load agent memory for %s", agent_id)
        return self._default_agent()

    def _save_agent(self, agent_id: str, payload: dict) -> None:
        try:
            with self._connect() as conn:
                conn.execute(
                    "INSERT OR REPLACE INTO agent_memory (agent_id, payload) VALUES (?, ?)",
                    (agent_id, json.dumps(payload)),
                )
        except sqlite3.Error:
            logger.exception("[HybridMemory] Failed to save agent memory for %s", agent_id)

    def get_context(self, agent_id: str) -> dict:
        shared = self._load_shared()
        agent_memory = self._load_agent(agent_id)
        compacted_recent = compact_recent_interactions(agent_memory.get("recent_interactions"))
        if compacted_recent != agent_memory.get("recent_interactions"):
            agent_memory["recent_interactions"] = compacted_recent
            self._save_agent(agent_id, agent_memory)
        return {
            "shared_memory": shared,
            "agent_memory": agent_memory,
        }

    def note_event(self, agent_id: str, event_type: str, payload: dict | None = None) -> None:
        shared = self._load_shared()
        event = {
            "agent": agent_id,
            "event_type": event_type,
            "payload": payload or {},
        }
        shared["recent_events"].append(event)
        shared["recent_events"] = shared["recent_events"][-32:]
        self._save_shared(shared)

    def update_after_turn(
        self,
        agent_id: str,
        user_message: str,
        output: str,
        engine_state: dict,
    ) -> None:
        shared = self._load_shared()
        agent_memory = self._load_agent(agent_id)

        entry = {
            "user_message": (user_message or "")[-16000:],
            "output": (output or "")[-16000:],
            "engine_snapshot": {
                "gait": engine_state.get("gait"),
                "rhythm": engine_state.get("rhythm"),
                "aperture": engine_state.get("aperture_mode"),
                "dynamic": engine_state.get("dynamic"),
            },
        }
        agent_memory["recent_interactions"].append(entry)
        agent_memory["recent_interactions"] = compact_recent_interactions(
            agent_memory["recent_interactions"]
        )
        agent_memory["dynamic_state"] = engine_state.get("dynamic") or agent_memory.get(
            "dynamic_state", {}
        )

        shared["last_active_agent"] = agent_id
        flags = engine_state.get("flags", {})
        if flags:
            shared["engine_flags"].update(flags)

        self._save_agent(agent_id, agent_memory)
        self._save_shared(shared)


def build_hybrid_memory(db_path: str | Path | None = None) -> HybridMemoryBackend:
    """Build a persistent hybrid memory backend with a safe fallback."""
    try:
        return SQLiteHybridMemory(db_path=db_path)
    except (sqlite3.Error, OSError, ValueError):
        logger.exception("[HybridMemory] Falling back to in-memory backend.")
        return InMemoryHybridMemory()


HybridMemorySystem = SQLiteHybridMemory
