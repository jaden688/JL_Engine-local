"""
engine_core.py - JL Engine Core Orchestrator

Licensed under the Apache License, Version 2.0. See LICENSE.md and NOTICE.

This module provides a *unified, headless* orchestration layer for the JL Engine.

It pulls together:
- Behavior grid (BehaviorStateMachine)
- Conversational signal scoring (SignalScorer)
- Emotional aperture (EmotionalAperture)
- Cognitive mode selector (CognitiveModeSelector)
- Rhythm engine (RhythmEngine)
- Drift pressure regulator (DriftPressureSystem)
- Modular Agent Framework (MPF) registry
- Backend routing (brain backend via backends.py)

The goal is to give the rest of the app a SINGLE entry point:

    from .engine_core import JLEngineCore, EngineConfig

    engine = JLEngineCore()
    reply, telemetry, feedback = engine.generate_response("Hello there!", agent_name="The Helper")

This file is intentionally UI-agnostic (no Tkinter imports) so it can be
re-used by:
- the existing Tk GUI (main_app.py),
- CLI tools,
- other automation layers (e.g. VS Code agents),
- or future CNC / hardware controllers.
"""

from __future__ import annotations

from difflib import SequenceMatcher
import hashlib
import json
import logging
from dataclasses import dataclass, asdict
from datetime import UTC, datetime
from pathlib import Path
from threading import Event, RLock, Thread
from typing import Any, Callable, Dict, List, Optional, Tuple, TypedDict

from .logging_setup import get_logger
import os

from .behavior_engine import BehaviorStateMachine
from .cognitive_gears import select_active_runtime_gear
from .cognitive_modes import CognitiveModeSelector, CognitiveModeState
from .emotional_aperture import EmotionalAperture
from .conversational_signals import SignalScorer, TurnSignals
from .rhythm import RhythmEngine
from .drift_pressure import DriftPressureSystem, DriftPressureInput, DriftResponse
from framework.mpf import MPFProfile, get_llm_boot_prompt, load_mpf_registry
from .backends import configure_backends, get_brain_backend
from .helper_supervisor import HelperSupervisor
from .hybrid_memory import build_hybrid_memory
from .agent_validation import ValidationError, validate_agent
from .agent_manager import AgentManager
from .state_manager import StateManager
from .config_loader import load_json_safely
from .modular_agents import get_modular_agent_summary, is_modular_agent_payload, resolve_modular_agent_payload
from .temporal_quantum_agent import TemporalQuantumAgent
from .temporal_field import TemporalFieldController, apply_temporal_sampling_bias

logger = get_logger(__name__)
RECENT_INTERACTION_LIMIT = 12
RECENT_INTERACTION_REPEAT_WINDOW = 4
RECENT_INTERACTION_REPEAT_RATIO = 0.92
SPEC_NUMBER_PRECISION = 4

PACKAGE_ROOT = Path(__file__).resolve().parent
REPO_ROOT = PACKAGE_ROOT.parent
DATA_DIR = PACKAGE_ROOT / "data"


def _data(*parts: str) -> str:
    return str((DATA_DIR / Path(*parts)).resolve())


def _text_audit_summary(value: str) -> Dict[str, Any]:
    text = str(value or "")
    return {
        "sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
        "chars": len(text),
        "lines": text.count("\n") + (1 if text else 0),
    }


def _round_spec_numbers(value: Any, *, places: int = SPEC_NUMBER_PRECISION) -> Any:
    """Round spec-style numeric values while preserving ints, bools, and structure."""
    if isinstance(value, bool):
        return value
    if isinstance(value, float):
        return round(value, places)
    if isinstance(value, dict):
        return {key: _round_spec_numbers(item, places=places) for key, item in value.items()}
    if isinstance(value, list):
        return [_round_spec_numbers(item, places=places) for item in value]
    if isinstance(value, tuple):
        return tuple(_round_spec_numbers(item, places=places) for item in value)
    return value


# Feature flag: emotion-driven sampling stays ON unless explicitly disabled.
ENABLE_EMOTION_SAMPLING = True
ENABLE_TEMPORAL_FIELD = True


# Safe clamp for emotion-driven sampling adjustments.
def apply_emotion_sampling_bias(
    temp: float, top_p: float, emotion_meta: dict | None
) -> tuple[float, float]:
    sampling_bias = (emotion_meta or {}).get("sampling_bias") or {}
    biased_temp = sampling_bias.get("temp", sampling_bias.get("temperature", temp))
    biased_top_p = sampling_bias.get("top_p", top_p)
    biased_temp = max(0.1, min(1.5, biased_temp))
    biased_top_p = max(0.1, min(1.0, biased_top_p))
    return biased_temp, biased_top_p


# --- JL Engine behavior profiles (engine-wide) ---
ENGINE_BEHAVIOR_PROFILES = {
    "safe_default": {
        "name": "safe_default",
        "supervisor_mode": "RESTRICTIVE",
        "supervisor_gain": 0.9,
        "min_temp": 0.55,
        "max_temp": 0.75,
        "min_top_p": 0.75,
        "max_top_p": 0.9,
        "base_drift_pressure": 0.08,
        "max_drift_pressure": 0.16,
        "aperture_mode": "LIMITED",
        "stability_soft_floor": 0.40,
        "stability_soft_ceiling": 0.95,
    },
    "expressive": {
        "name": "expressive",
        "supervisor_mode": "BALANCED",
        "supervisor_gain": 0.35,
        "min_temp": 0.70,
        "max_temp": 0.90,
        "min_top_p": 0.80,
        "max_top_p": 0.96,
        "base_drift_pressure": 0.20,
        "max_drift_pressure": 0.32,
        "aperture_mode": "OPEN",
        "stability_soft_floor": 0.30,
        "stability_soft_ceiling": 0.85,
    },
    "chaos_coherence": {
        "name": "chaos_coherence",
        "supervisor_mode": "PASSIVE",
        "supervisor_gain": 0.001,
        "min_temp": 0.80,
        "max_temp": 0.95,
        "min_top_p": 0.85,
        "max_top_p": 1.00,
        "base_drift_pressure": 0.28,
        "max_drift_pressure": 0.40,
        "aperture_mode": "OPEN",
        "stability_soft_floor": 0.30,
        "stability_soft_ceiling": 0.80,
    },
}


# ---------------------------------------------------------------------------
# Engine configuration
# ---------------------------------------------------------------------------


@dataclass
class EngineConfig:
    """Lightweight configuration for the core engine."""

    master_file: str = _data("config", "JLframe_Engine_Framework.headless.json")
    behavior_states_file: str = _data("behavior_states.json")
    mpf_registry_file: str = _data("agents", "JL_Agents.mpf.json")
    safety_on: bool = True
    default_agent_name: str = "SparkByte"
    history_length: int = 20
    enable_feedback: bool = True
    feedback_log_path: str = "logs/engine_feedback.log"
    debug_feedback_notes: bool = False
    drive_weights: Dict[str, float] = None  # late init
    invariants: List[Dict[str, Any]] = None  # late init
    strain: float = 0.6  # higher = tolerates more instability
    memory_db_path: Optional[str] = None


class EngineFeedback(TypedDict, total=False):
    agent_id: Optional[str]
    agent_name: str
    active_gait_state: str
    active_rhythm_pattern: str
    aperture_level: Optional[str]
    used_memory_count: int
    used_memory_ids: List[str]
    notes: str
    raw_memory_preview: List[str]


# ---------------------------------------------------------------------------
# Core orchestrator
# ---------------------------------------------------------------------------


class JLEngineCore:
    """
    Unified JL Engine orchestrator (no GUI).

    Responsibilities:
    - Load master config & MPF registry
    - Manage current agent
    - Maintain behavior state, rhythm, gait, cognitive mode, aperture
    - Compute drift pressure & corrective actions
    - Build messages and dispatch to the configured brain backend
    """

    def __init__(self, config: EngineConfig | None = None) -> None:
        self.config = config or EngineConfig()

        # Override config from environment variables (launcher settings)
        raw_safety = str(os.getenv("JL_ENGINE_SAFETY_ON", "1")).strip().lower()
        self.config.safety_on = raw_safety not in {"0", "false", "off", "no"}

        if self.config.drive_weights is None:
            self.config.drive_weights = {
                "curiosity": 0.7,
                "risk": 0.5,
                "coherence": 0.85,
                "effort": 0.4,
                "persistence": 0.6,
            }
        if self.config.invariants is None:
            self.config.invariants = [
                {"id": "coherence_floor", "type": "stability_floor", "threshold": 0.25},
                {"id": "drift_ceiling", "type": "drift_ceiling", "threshold": 0.75},
                {"id": "overload_guard", "type": "overload", "threshold": 0.85},
            ]

        # Master config & core rules
        self.master_config: Dict[str, Any] = {}
        self.core_rules: List[str] = []
        self._load_master_config()
        raw_listener = (
            self.master_config.get("listener_agent", {})
            if isinstance(self.master_config, dict)
            else {}
        )
        self.listener_agent: Dict[str, Any] = (
            raw_listener if (isinstance(raw_listener, dict) and raw_listener.get("enabled")) else {}
        )

        # MPF / agent registry
        self.mpf_profiles: Dict[str, MPFProfile] = {}
        self._load_mpf_registry()

        # Subsystems
        self.agent_state: Dict[str, Any] = {"emotion": None, "emotion_meta": None}
        self.behavior_engine = BehaviorStateMachine(self.config.behavior_states_file)
        self.emotional_aperture = EmotionalAperture(agent_state=self.agent_state)
        raw_temporal_field_enabled = str(os.getenv("JL_TEMPORAL_FIELD", "1")).strip().lower()
        temporal_field_enabled = raw_temporal_field_enabled not in {"0", "false", "off", "no"}
        try:
            temporal_field_interval = float(os.getenv("JL_TEMPORAL_FIELD_INTERVAL", "0.2") or 0.2)
        except (TypeError, ValueError):
            temporal_field_interval = 0.2
        self.temporal_field_enabled: bool = ENABLE_TEMPORAL_FIELD and temporal_field_enabled
        self.temporal_field_sampling: bool = self.temporal_field_enabled
        self.temporal_field = (
            TemporalFieldController(interval_seconds=temporal_field_interval)
            if self.temporal_field_enabled
            else None
        )
        self.cognitive_selector = CognitiveModeSelector(default_mode="balanced")
        self.rhythm_engine = RhythmEngine()
        self.signal_scorer = SignalScorer()
        self.drift_system = DriftPressureSystem()
        self.supervisor = HelperSupervisor()
        self.agent_manager = AgentManager()
        self.state_manager = StateManager()
        raw_tqa_loop_enabled = str(os.getenv("JL_TQA_INTERNAL_LOOP", "1")).strip().lower()
        tqa_loop_enabled = raw_tqa_loop_enabled not in {"0", "false", "off", "no"}
        try:
            tqa_loop_interval = float(os.getenv("JL_TQA_INTERNAL_LOOP_INTERVAL", "0.75") or 0.75)
        except (TypeError, ValueError):
            tqa_loop_interval = 0.75
        self.tqa_layer = TemporalQuantumAgent(
            internal_loop_interval_seconds=tqa_loop_interval,
            autostart_internal_loop=tqa_loop_enabled,
        )

        # Runtime state
        self.current_agent_name: str = self.config.default_agent_name
        self.current_agent_data: Dict[str, Any] = {}
        self.current_gait: str = "walk"
        self.current_rhythm_mode: str = "flop"
        self.current_cognitive_state: CognitiveModeState | None = None
        self.current_cognitive_gear: Dict[str, Any] = {
            "active_label": "TASK_FLOW",
            "runtime_gear": "spur",
            "reason": "default",
        }
        self.last_signals: TurnSignals | None = None
        self.last_drift_response: DriftResponse | None = None
        self.drift_pressure: float = 0.0
        self.supervisor_state: Dict[str, Any] = {}
        self.behavior_profile_name: str = "expressive"
        self.behavior_profile: Dict[str, Any] | None = None
        self.supervisor_gain: float = 0.35
        # Read supervisor settings from environment (launcher toggles)
        raw_supervisor = str(os.getenv("JL_ENGINE_SUPERVISOR_ON", "1")).strip().lower()
        supervisor_on = raw_supervisor not in {"0", "false", "off", "no"}
        self.supervisor_enabled: bool = supervisor_on  # Strict master switch
        self.supervisor_gating: bool = supervisor_on
        self.supervisor_postprocess: bool = True
        self.emotional_sampling: bool = ENABLE_EMOTION_SAMPLING
        self.backoff_mode: bool = False
        self.supervisor_mode: str = "BALANCED"
        self.aperture_mode: str = "LIMITED"
        self.temp: float = 0.7
        self.top_p: float = 0.9
        self.drive_state: Dict[str, float] = dict(self.config.drive_weights)
        self.internal_tension: Dict[str, Any] = {"score": 0.0, "drives": {}, "invariants": []}
        self.stability_score: float = 0.5
        self.user_trigger: Optional[str] = None
        self.gait: str = "TROT"
        self.rhythm: str = "TWITCH"
        self._drift_state: float = 0.0
        self.engine_core_test_mode: bool = False
        self.modulation_fault: bool = False
        self.feedback_enabled: bool = bool(self.config.enable_feedback)
        self.feedback_log_path: Path = Path(self.config.feedback_log_path)
        self.debug_feedback_notes: bool = bool(self.config.debug_feedback_notes)
        self.current_agent_file: Optional[str] = None
        self.temporal_field_state: Dict[str, Any] = {}
        self.feedback_logger = logging.getLogger("EngineFeedback")
        if not self.feedback_logger.handlers:
            self.feedback_logger.addHandler(logging.NullHandler())
        self._ensure_feedback_log_directory()

        # Backend wiring
        self._configure_backends_from_master()

        # Hybrid memory system
        self.memory_system = build_hybrid_memory(self.config.memory_db_path)

        # Load initial agent
        self.set_agent(self.current_agent_name)
        self.set_behavior_profile("expressive")
        if self.temporal_field:
            self.start_temporal_field_loop()

    # ------------------------------------------------------------------
    # Initialization helpers
    # ------------------------------------------------------------------

    def _load_master_config(self) -> None:
        path = self.config.master_file
        blob = load_json_safely(path)
        if not blob:
            self.master_config = {}
            self.core_rules = []
            logger.info("[EngineCore] Using defaults for master config.")
            return

        self.master_config = blob.get("jl_engine", {}) if isinstance(blob, dict) else {}
        if not isinstance(self.master_config, dict):
            self.master_config = {}

        self.core_rules = self.master_config.get("core_rules", []) or []
        logger.info("[EngineCore] Loaded master config with %d core rules.", len(self.core_rules))

    def _load_mpf_registry(self) -> None:
        try:
            self.mpf_profiles = load_mpf_registry(self.config.mpf_registry_file)
        except (FileNotFoundError, json.JSONDecodeError, ValueError, OSError) as exc:
            logger.exception(
                "[EngineCore] Failed to load MPF registry '%s': %s",
                self.config.mpf_registry_file,
                exc,
            )
            self.mpf_profiles = {}

    def _configure_backends_from_master(self) -> None:
        """
        Configure brain/tool backends using the same logic as the GUI,
        but without importing Tk or other UI modules.
        """
        from .backends import (
            apply_backend_overrides,
            configure_backends,
        )  # local import to avoid cycles

        backends_cfg = self.master_config.get("backends", {})
        brain_backend_cfg = None
        tool_backend_cfg = None
        if isinstance(backends_cfg, dict):
            apply_backend_overrides(backends_cfg)
            brain_backend_cfg = backends_cfg.get("brain_backend") or backends_cfg.get("default")
            tool_backend_cfg = backends_cfg.get("tool_backend")

        env_brain_backend = (os.environ.get("JL_ENGINE_BRAIN_BACKEND") or "").strip()
        env_tool_backend = (os.environ.get("JL_ENGINE_TOOL_BACKEND") or "").strip()
        if env_brain_backend:
            brain_backend_cfg = env_brain_backend
        if env_tool_backend:
            tool_backend_cfg = env_tool_backend

        configure_backends(brain_id=brain_backend_cfg, tool_id=tool_backend_cfg)
        logger.info(
            "[EngineCore] Backends configured (brain=%r, tool=%r).",
            brain_backend_cfg,
            tool_backend_cfg,
        )

    # ------------------------------------------------------------------
    # Agent management
    # ------------------------------------------------------------------

    def set_agent(self, agent_name: str) -> None:
        """
        Set the active agent by display name (as used in JL_Agents.mpf.json).
        Falls back to the default agent if not found.
        """
        import json, os

        profile = self.mpf_profiles.get(agent_name)
        if not profile:
            logger.warning(
                "[EngineCore] Agent '%s' not found in MPF registry; " "falling back to '%s'.",
                agent_name,
                self.config.default_agent_name,
            )
            profile = self.mpf_profiles.get(self.config.default_agent_name)

        self.current_agent_name = agent_name
        agent_file = None
        drive_type = None

        if profile:
            agent_file = profile.agent_file
            drive_type = profile.drive_type
        self.current_agent_file = agent_file

        # Reset canonical agent state emotion slots for the new agent.
        if isinstance(self.agent_state, dict):
            self.agent_state["emotion"] = None
            self.agent_state["emotion_meta"] = None
        if hasattr(self.emotional_aperture, "set_agent_state"):
            self.emotional_aperture.set_agent_state(self.agent_state)

        # Load agent JSON (if available)
        agent_path: Path | None = None
        agent_payload: Dict[str, Any] = {}
        candidate_errors: List[str] = []

        def _agent_score(payload: Dict[str, Any]) -> int:
            identity = payload.get("identity") if isinstance(payload.get("identity"), dict) else {}
            behavior = payload.get("behavior") if isinstance(payload.get("behavior"), dict) else {}
            communication = (
                payload.get("communication_style")
                if isinstance(payload.get("communication_style"), dict)
                else {}
            )
            llm_profiles = payload.get("llm_profiles") if isinstance(payload.get("llm_profiles"), dict) else {}
            generic_profile = (
                llm_profiles.get("generic_llm")
                if isinstance(llm_profiles.get("generic_llm"), dict)
                else {}
            )
            score = 0
            if isinstance(identity, dict):
                if str(identity.get("name") or "").strip():
                    score += 8
                if str(identity.get("role") or "").strip():
                    score += 6
                if str(identity.get("description") or "").strip():
                    score += 18
                tags = identity.get("tags")
                if isinstance(tags, list):
                    score += min(len(tags), 8)
            if isinstance(behavior, dict):
                directives = behavior.get("core_directives") or behavior.get("directives") or []
                boundaries = behavior.get("avoidances") or behavior.get("boundaries") or []
                if isinstance(directives, list):
                    score += min(len(directives), 12)
                if isinstance(boundaries, list):
                    score += min(len(boundaries), 8)
            if isinstance(communication, dict):
                if str(communication.get("voice") or "").strip():
                    score += 4
                style_notes = communication.get("style_notes")
                if isinstance(style_notes, list):
                    score += min(len(style_notes), 6)
            if str(payload.get("base_prompt") or "").strip():
                score += 10
            if str(generic_profile.get("boot_prompt") or "").strip():
                score += 10
            if isinstance(payload.get("engine_alignment"), dict):
                score += 8
            if isinstance(payload.get("cognitive_gears"), dict):
                score += 6
            if isinstance(payload.get("cognitive_modes"), dict):
                score += 6
            if isinstance(payload.get("emotion_palette"), list):
                score += min(len(payload.get("emotion_palette") or []), 8)
            if isinstance(payload.get("operational_behavioral_traits"), dict):
                score += 8
            return score

        def _load_candidate(path: Path) -> Dict[str, Any] | None:
            try:
                # utf-8-sig accepts plain utf-8 and strips BOM when present.
                raw = path.read_text(encoding="utf-8-sig")
                payload = json.loads(raw)
                if not isinstance(payload, dict):
                    raise TypeError("Agent payload must be a JSON object.")
                if is_modular_agent_payload(payload):
                    payload = resolve_modular_agent_payload(payload, agent_path=path)
                validate_agent(payload)
                return payload
            except (OSError, json.JSONDecodeError, ValidationError, TypeError, ValueError) as exc:
                candidate_errors.append(f"{path}: {exc}")
                return None

        if agent_file:
            raw_agent = Path(agent_file)
            candidates: list[Path] = []
            alternates: list[Path] = []
            suffix = raw_agent.suffix.lower()
            if suffix == ".json":
                alternates.append(raw_agent.with_suffix(".mpf"))
            elif suffix == ".mpf":
                alternates.append(raw_agent.with_suffix(".json"))
            else:
                alternates.extend([raw_agent.with_suffix(".json"), raw_agent.with_suffix(".mpf")])
            if raw_agent.is_absolute():
                candidates.append(raw_agent)
                candidates.extend(alternates)
            else:
                relative_candidates = [raw_agent, *alternates]
                # Prefer explicit project agents first, then bundled data agents.
                candidates.extend(
                    [REPO_ROOT / "agents" / rel_path for rel_path in relative_candidates]
                    + [DATA_DIR / "agents" / rel_path for rel_path in relative_candidates]
                    + [Path.cwd() / "agents" / rel_path for rel_path in relative_candidates]
                )

            seen: set[str] = set()
            existing_candidates: list[Path] = []
            for candidate in candidates:
                resolved = str(candidate.resolve()) if candidate.exists() else ""
                if not resolved or resolved in seen:
                    continue
                seen.add(resolved)
                existing_candidates.append(candidate)

            best_score = -1
            for candidate in existing_candidates:
                loaded = _load_candidate(candidate)
                if loaded is None:
                    continue
                score = _agent_score(loaded)
                if score > best_score:
                    best_score = score
                    agent_payload = loaded
                    agent_path = candidate

        if agent_payload:
            self.current_agent_data = agent_payload
            if agent_path is not None:
                try:
                    self.current_agent_file = str(agent_path.relative_to(DATA_DIR / "agents"))
                except Exception:
                    self.current_agent_file = agent_path.name
        else:
            if agent_file and candidate_errors:
                logger.warning(
                    "[EngineCore] Failed agent candidate loads for '%s': %s",
                    agent_file,
                    " | ".join(candidate_errors),
                )
            elif agent_file:
                logger.warning("[EngineCore] Agent file '%s' not found.", agent_file)
            self.current_agent_data = {}

        # Push agent-specific emotion palette (if present) into the aperture.
        try:
            if hasattr(self.emotional_aperture, "set_emotion_model"):
                self.emotional_aperture.set_emotion_model(
                    self.current_agent_data.get("emotion_palette"),
                    self.current_agent_data.get("emotion_wheel"),
                )
            else:
                self.emotional_aperture.set_emotion_palette(
                    self.current_agent_data.get("emotion_palette")
                )
        except (AttributeError, TypeError, ValueError) as exc:
            logger.exception(
                "[EngineCore] Failed to set emotion palette for '%s': %s",
                agent_name,
                exc,
            )
        if self.temporal_field:
            try:
                self.temporal_field.set_ontology(
                    self.current_agent_name,
                    self.current_agent_data.get("emotion_wheel"),
                    self.current_agent_data.get("emotion_palette"),
                )
                self.temporal_field_state = self.temporal_field.sample_field()
            except (AttributeError, TypeError, ValueError) as exc:
                logger.exception(
                    "[EngineCore] Failed to set temporal field ontology for '%s': %s",
                    agent_name,
                    exc,
                )
        try:
            self.agent_manager.set_active_agent(
                self.current_agent_name, self.current_agent_data, self.mpf_profiles
            )
        except (AttributeError, TypeError, ValueError) as exc:
            logger.exception(
                "[EngineCore] Agent manager unable to attach '%s': %s",
                self.current_agent_name,
                exc,
            )

        # Drive type + emotional aperture
        if drive_type:
            try:
                self.emotional_aperture.set_drive_type(drive_type)
            except (AttributeError, TypeError, ValueError) as exc:
                logger.exception(
                    "[EngineCore] Failed to set drive_type '%s': %s",
                    drive_type,
                    exc,
                )

        # Reset dynamic state for new agent
        self.current_gait = "walk"
        self.current_rhythm_mode = "flop"
        self.current_cognitive_state = None
        self.current_cognitive_gear = {
            "active_label": "TASK_FLOW",
            "runtime_gear": "spur",
            "reason": "default",
        }
        self.last_signals = None
        self.last_drift_response = None
        self.drift_pressure = 0.0
        # For SparkByte testing, reduce supervisor influence without disabling safety
        if agent_name.lower() == "sparkbyte":
            self.supervisor_gain = 0.01

        logger.info(
            "[EngineCore] Agent set to '%s' (file=%r, drive_type=%r).",
            agent_name,
            agent_file,
            drive_type,
        )

    def get_llm_boot_prompt(self, target: str = "generic_llm") -> str:
        """
        Return the boot prompt for the current agent for a given LLM target.

        This simply wraps the MPF helper so other layers (bridges, tools) can
        fetch the correct agent script without re-parsing the JSON layout.
        """
        return get_llm_boot_prompt(self.current_agent_data, target)

    # ------------------------------------------------------------------
    # Test mode controls
    # ------------------------------------------------------------------

    def enable_engine_core_test_mode(self):
        """Enable Engine Core Diagnostic Mode."""
        self.engine_core_test_mode = True

    def disable_engine_core_test_mode(self):
        """Disable Engine Core Diagnostic Mode."""
        self.engine_core_test_mode = False

    def toggle_engine_core_test_mode(self) -> bool:
        """Toggle Engine Core Diagnostic Mode and return the new state."""
        self.engine_core_test_mode = not self.engine_core_test_mode
        return self.engine_core_test_mode

    def reset_modulation(self) -> Dict[str, Any]:
        """
        Clear modulation faults and re-center aperture/gait/rhythm.
        Returns the updated engine status snapshot.
        """
        self.modulation_fault = False
        self._drift_state = 0.0
        self.stability_score = 0.55
        self.gait = "TROT"
        self.rhythm = "TWITCH"
        self.current_gait = self.gait.lower()
        self.current_rhythm_mode = self.rhythm.lower()
        try:
            self.emotional_aperture.reset()
            aperture_state = self.emotional_aperture.get_state()
            self.aperture_mode = aperture_state.get("mode", self.aperture_mode)
        except (AttributeError, RuntimeError, TypeError) as exc:
            logger.exception("[EngineCore] Failed to reset emotional aperture: %s", exc)
            # Fallback to baseline if reset is unavailable.
            self.aperture_mode = "LIMITED"
        return self.get_engine_status()

    def get_mpf_state_snapshot(self) -> Dict[str, Any]:
        """
        Lightweight, JSON-serializable MPF snapshot for diagnostics.
        """
        try:
            aperture_state = self.emotional_aperture.get_state()
        except (AttributeError, RuntimeError, TypeError) as exc:
            logger.exception("[EngineCore] Failed to read aperture state: %s", exc)
            aperture_state = {}

        emotional_score = float(aperture_state.get("score", 0.0) or 0.0)
        safety_score = 1.0 - max(0.0, min(1.0, float(getattr(self, "drift_pressure", 0.0) or 0.0)))

        memory_focus = 0.0
        try:
            agent_id = self.current_agent_name or "default"
            ctx = (
                self.memory_system.get_context(agent_id) if hasattr(self, "memory_system") else {}
            )
            ctx = self._sanitize_memory_context(ctx)
            agent_mem = (ctx or {}).get("agent_memory", {}) if isinstance(ctx, dict) else {}
            recent_interactions = (
                agent_mem.get("recent_interactions", []) if isinstance(agent_mem, dict) else []
            )
            memory_focus = min(1.0, len(recent_interactions) / 20.0)
        except (AttributeError, KeyError, TypeError) as exc:
            logger.exception("[EngineCore] Failed to compute memory focus: %s", exc)
            memory_focus = 0.0

        return _round_spec_numbers({
            "gait": getattr(self, "current_gait", None),
            "rhythm": getattr(self, "current_rhythm_mode", None),
            "aperture": {
                "emotional": round(emotional_score, SPEC_NUMBER_PRECISION),
                "safety": round(safety_score, SPEC_NUMBER_PRECISION),
                "memory_focus": round(memory_focus, SPEC_NUMBER_PRECISION),
            },
            "mode": getattr(self, "behavior_profile_name", None),
        })

    def get_engine_status(self) -> Dict[str, Any]:
        """
        Lightweight status block for UI/diagnostics overlays.
        """
        temporal_loop = {"running": False}
        temporal_backend = {"backend_name": "disabled", "warm_lane_detected": False}
        if self.temporal_field:
            try:
                temporal_loop = self.temporal_field.get_loop_status()
                temporal_backend = self.temporal_field.get_backend_status()
            except Exception:
                temporal_loop = {"running": False}
                temporal_backend = {"backend_name": "error", "warm_lane_detected": False}
        return _round_spec_numbers({
            "gait": self.current_gait,
            "rhythm": self.current_rhythm_mode,
            "aperture_mode": self.aperture_mode,
            "stability_score": round(self.stability_score, SPEC_NUMBER_PRECISION),
            "modulation_fault": self.modulation_fault,
            "temporal_loop": temporal_loop,
            "temporal_backend": temporal_backend,
        })

    def start_temporal_field_loop(self) -> None:
        if not self.temporal_field:
            return
        self.temporal_field.start_loop()
        self.temporal_field_state = self.temporal_field.sample_field()

    def stop_temporal_field_loop(self, join_timeout_seconds: float = 1.0) -> None:
        if not self.temporal_field:
            return
        self.temporal_field.stop_loop(join_timeout_seconds=join_timeout_seconds)
        self.temporal_field_state = self.temporal_field.sample_field()

    def sample_temporal_field(self) -> Dict[str, Any]:
        if not self.temporal_field:
            return {}
        self.temporal_field_state = self.temporal_field.sample_field()
        return _round_spec_numbers(dict(self.temporal_field_state))

    def shutdown(self) -> None:
        self.stop_temporal_field_loop()
        if self.tqa_layer:
            try:
                self.tqa_layer.stop_internal_loop()
            except Exception:
                logger.exception("[EngineCore] Failed to stop TQA internal loop during shutdown.")

    def __del__(self) -> None:
        try:
            self.shutdown()
        except Exception:
            pass

    @staticmethod
    def _looks_like_interpreter_prompt(text: Any) -> bool:
        if not isinstance(text, str):
            return False
        return (
            "You are a local interpreter. You can call tools to complete tasks." in text
            and "Return ONLY JSON." in text
            and "\nUSER:\n" in text
        )

    def _unwrap_interpreter_prompt(self, text: Any) -> str:
        if not isinstance(text, str):
            return ""
        raw = text.strip()
        if not self._looks_like_interpreter_prompt(raw):
            return raw
        user_marker = "\nUSER:\n"
        payload = raw.split(user_marker, 1)[1] if user_marker in raw else raw
        history_marker = "\n\nHISTORY:\n"
        if history_marker in payload:
            payload = payload.split(history_marker, 1)[0]
        return payload.strip()

    @staticmethod
    def _normalize_memory_text(text: Any) -> str:
        if not isinstance(text, str):
            return ""
        return " ".join(text.lower().split())

    @staticmethod
    def _memory_lead_sentence(text: Any) -> str:
        normalized = JLEngineCore._normalize_memory_text(text)
        if not normalized:
            return ""
        for marker in (".", "!", "?"):
            if marker in normalized:
                head = normalized.split(marker, 1)[0].strip()
                if head:
                    return head
        return normalized

    def _looks_like_synthetic_memory_turn(self, text: Any) -> bool:
        normalized = self._normalize_memory_text(text)
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

    def _looks_like_generic_capability_reply(self, text: Any) -> bool:
        normalized = self._normalize_memory_text(text)
        if not normalized:
            return False
        has_jl_self_frame = "jl engine" in normalized and ("i'm " in normalized or "i am " in normalized)
        if not has_jl_self_frame:
            return False
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
        return any(marker in normalized for marker in markers)

    def _should_store_memory_turn(self, user_text: Any, output_text: Any) -> bool:
        user_clean = self._unwrap_interpreter_prompt(user_text)
        output_clean = str(output_text or "").strip()
        if not user_clean and not output_clean:
            return False
        if self._looks_like_synthetic_memory_turn(user_clean):
            return False
        if self._looks_like_generic_capability_reply(output_clean):
            return False
        return True

    def _sanitize_recent_interactions(self, interactions: Any) -> list[dict[str, Any]]:
        if not isinstance(interactions, list):
            return []

        cleaned: list[dict[str, Any]] = []
        for item in interactions:
            if not isinstance(item, dict):
                continue
            user_clean = self._unwrap_interpreter_prompt(item.get("user_message"))
            output_clean = str(item.get("output") or "").strip()

            # Interpreter tool-result hops are useful in-flight but noisy for long-term replay.
            if not self._should_store_memory_turn(user_clean, output_clean):
                continue

            if not user_clean and not output_clean:
                continue

            user_norm = self._normalize_memory_text(user_clean)
            output_norm = self._normalize_memory_text(output_clean)

            if (
                cleaned
                and cleaned[-1].get("user_message") == user_clean
                and cleaned[-1].get("output") == output_clean
            ):
                continue

            duplicate_output = False
            if output_norm:
                output_head = self._memory_lead_sentence(output_clean)
                for prior in cleaned[-RECENT_INTERACTION_REPEAT_WINDOW:]:
                    prior_output = self._normalize_memory_text(prior.get("output"))
                    prior_head = self._memory_lead_sentence(prior.get("output"))
                    if not prior_output:
                        continue
                    if output_norm == prior_output:
                        duplicate_output = True
                        break
                    if (
                        output_head
                        and prior_head
                        and output_head == prior_head
                        and len(output_norm) >= 80
                        and len(prior_output) >= 80
                    ):
                        duplicate_output = True
                        break
                    if (
                        len(output_norm) >= 80
                        and len(prior_output) >= 80
                        and SequenceMatcher(a=prior_output, b=output_norm).ratio()
                        >= RECENT_INTERACTION_REPEAT_RATIO
                    ):
                        duplicate_output = True
                        break
            if duplicate_output:
                continue

            cleaned.append(
                {
                    "user_message": user_clean[:16000],
                    "output": output_clean[:16000],
                    "engine_snapshot": (
                        item.get("engine_snapshot")
                        if isinstance(item.get("engine_snapshot"), dict)
                        else {}
                    ),
                }
            )
        return cleaned[-RECENT_INTERACTION_LIMIT:]

    def _sanitize_memory_context(self, memory_ctx: Any) -> Dict[str, Any]:
        if not isinstance(memory_ctx, dict):
            return {"shared_memory": {}, "agent_memory": {}}

        shared = memory_ctx.get("shared_memory")
        agent = memory_ctx.get("agent_memory")
        shared_clean = shared if isinstance(shared, dict) else {}
        agent_clean = dict(agent) if isinstance(agent, dict) else {}

        if "recent_interactions" in agent_clean:
            agent_clean["recent_interactions"] = self._sanitize_recent_interactions(
                agent_clean.get("recent_interactions")
            )

        return {
            "shared_memory": shared_clean,
            "agent_memory": agent_clean,
        }

    def smoke_test_engine(self, user_message: str) -> Tuple[str, Dict[str, Any]]:
        """
        Generate a raw engine-core response without agent or supervisor layers.
        """
        core_prompt = (
            "ENGINE_CORE_DIAGNOSTIC_MODE\n"
            "Internal State:\n"
            f"- Gait: {self.gait}\n"
            f"- Rhythm: {self.rhythm}\n"
            f"- Aperture: {self.aperture_mode}\n\n"
            "User message:\n"
            f"{user_message}\n\n"
            "Respond as raw engine cognition (no agent)."
        )

        backend = get_brain_backend()
        options = {"temperature": self.temp, "top_p": self.top_p}
        try:
            result = backend.generate([{"role": "user", "content": core_prompt}], options=options)
            if isinstance(result, tuple) and len(result) == 2:
                reply_text, meta = result
            else:
                reply_text, meta = result, {}
        except (RuntimeError, ValueError, TypeError, OSError) as exc:
            logger.exception("[EngineCore] Diagnostic backend error: %s", exc)
            reply_text = f"[ENGINE_CORE_DIAGNOSTIC_MODE] Backend error: {exc}"
            meta = {"error": str(exc)}
        return reply_text, meta

    def generate_response(
        self,
        user_message: str,
        agent_name: Optional[str] = None,
        context: Optional[Dict[str, Any]] = None,
    ) -> Tuple[str, Dict[str, Any], EngineFeedback]:
        """
        Unified entrypoint for chat responses that can bypass agent/supervisor layers
        when Engine Core Diagnostic Mode is active.
        """
        if self.engine_core_test_mode:
            reply_text, backend_meta = self.smoke_test_engine(user_message)
            telemetry = {
                "agent": "ENGINE_CORE_DIAGNOSTIC_MODE",
                "agent_state": (
                    dict(self.agent_state)
                    if isinstance(self.agent_state, dict)
                    else {"emotion": None, "emotion_meta": None}
                ),
                "signals": {},
                "behavior_state": {"id": None, "name": "diagnostic"},
                "aperture_state": self.emotional_aperture.get_state(),
                "cognitive_mode": "diagnostic",
                "drift": {"pressure": 0.0, "action": "diagnostic", "raw": {}},
                "rhythm": {"mode": self.current_rhythm_mode, "gait": self.current_gait},
                "backend_meta": backend_meta,
                "behavior_profile": self.behavior_profile_name,
                "aperture_dynamic": {
                    "temp": self.temp,
                    "top_p": self.top_p,
                    "mode": self.aperture_mode,
                },
                "temporal_state": self.sample_temporal_field(),
                "temporal_backend": (
                    self.temporal_field.get_backend_status() if self.temporal_field else {}
                ),
                "temporal_loop": (
                    self.temporal_field.get_loop_status()
                    if self.temporal_field
                    else {"running": False}
                ),
                "drift_state": self._drift_state,
                "stability_score": self.stability_score,
                "engine_status": self.get_engine_status(),
            }
            telemetry = _round_spec_numbers(telemetry)
            feedback: EngineFeedback = {
                "agent_id": "ENGINE_CORE_DIAGNOSTIC_MODE",
                "agent_name": "ENGINE_CORE_DIAGNOSTIC_MODE",
                "active_gait_state": self.current_gait,
                "active_rhythm_pattern": self.current_rhythm_mode,
                "aperture_level": self.aperture_mode,
                "used_memory_count": 0,
                "used_memory_ids": [],
                "raw_memory_preview": [],
                "notes": "",
            }
            telemetry["feedback"] = feedback
            if self._should_record_feedback(context):
                self._append_feedback_log(user_message, reply_text, feedback)
            return reply_text, telemetry, feedback

        return self.process_turn(user_text=user_message, agent_name=agent_name, context=context)

    # ------------------------------------------------------------------
    # Turn processing
    # ------------------------------------------------------------------

    def process_turn(
        self,
        user_text: str,
        agent_name: Optional[str] = None,
        context: Optional[Dict[str, Any]] = None,
    ) -> Tuple[str, Dict[str, Any], EngineFeedback]:
        """
        Process a single conversational turn.

        Returns:
            reply_text: str - model output from the brain backend
            telemetry: dict - rich structured data for HUDs / logs / debugging
            feedback: EngineFeedback - dev-only self-report of what the engine used
        """
        context = context or {}
        requested_agent = agent_name or self.current_agent_name
        respect_selected_agent = bool(
            context.get("respect_selected_agent") or context.get("disable_agent_bias_redirect")
        )
        agent_choice, bias_reason = (
            (requested_agent, "")
            if respect_selected_agent
            else (
                self.tqa_layer.apply_biases(requested_agent)
                if self.tqa_layer
                else (requested_agent, "")
            )
        )
        agent_name = agent_choice
        if bias_reason:
            logger.info(
                "[TQA] Agent bias redirect: %s -> %s (%s)",
                requested_agent,
                agent_name,
                bias_reason,
            )
        if agent_name and agent_name != self.current_agent_name:
            self.set_agent(agent_name)

        # Determine agent_id for memory
        agent_id = self.current_agent_name
        memory_ctx = self.memory_system.get_context(agent_id)
        memory_ctx = self._sanitize_memory_context(memory_ctx)

        # 1) Score conversational signals from the raw text
        signals = self.signal_scorer.score(user_text or "")
        self.last_signals = signals

        state_snapshot = self.state_manager.export_snapshot() if self.state_manager else {}
        advisory_payload = (
            self.state_manager.advisory_payload(self.stability_score, self.drift_pressure)
            if self.state_manager
            else {}
        )
        sup_arbitration = {}
        if self.supervisor and self.supervisor_enabled:
            sup_arbitration = self.supervisor.arbitrate(
                {
                    "stability": self.stability_score,
                    "drift_pressure": self.drift_pressure,
                    "rhythm_momentum": advisory_payload.get("rhythm_momentum", 0.0),
                    "emotional_drift": advisory_payload.get("emotional_drift", 0.0),
                }
            )

        # 2) Trigger inference and behavior update
        self.user_trigger = context.get("user_trigger") or self._derive_trigger_from_signals(
            signals
        )
        if self.behavior_engine:
            try:
                # Only pass gating advice if Gating is explicitly ENABLED
                gating_payload = None
                if self.supervisor_gating and isinstance(sup_arbitration, dict):
                    gating_payload = sup_arbitration.get("gating")

                self.behavior_engine.transition_by_trigger(
                    self.user_trigger,
                    self.current_gait,
                    gating_advice=gating_payload,
                )
            except (AttributeError, ValueError, TypeError, IndexError) as exc:
                logger.exception("[EngineCore] Failed behavior transition: %s", exc)

        # 3) Behavior state from the grid (post-transition)
        behavior_state = self.behavior_engine.get_current_state() if self.behavior_engine else None
        behavior_blend = self.behavior_engine.get_current_blend() if self.behavior_engine else None
        # allow supervisor to nudge behavior intensity without hard blocks
        if sup_arbitration and sup_arbitration.get("behavior_bias"):
            bias = sup_arbitration["behavior_bias"]
            delta_row = 1 if bias > 0.25 else -1 if bias < -0.25 else 0
            if delta_row != 0 and self.behavior_engine:
                try:
                    self.behavior_engine.set_state_by_coords(
                        self.behavior_engine.current_row + delta_row,
                        self.behavior_engine.current_col,
                    )
                    behavior_state = self.behavior_engine.get_current_state()
                    behavior_blend = self.behavior_engine.get_current_blend()
                except (AttributeError, ValueError, TypeError, IndexError) as exc:
                    logger.exception("[EngineCore] Failed to apply behavior bias: %s", exc)

        # 4) Emotional aperture update
        #    Note: we don't yet pass full behavior/gait/rhythm semantics;
        #    this can be expanded later.
        self.emotional_aperture.update_from_signals(
            behavior_state=behavior_state,
            gait=self.current_gait,
            rhythm=self.current_rhythm_mode,
            user_sentiment=signals.sentiment,
            conversation_pacing=signals.pace,
            memory_density=signals.memory_density,
            drift_bias=advisory_payload.get("emotional_drift", 0.0),
            aperture_bias=advisory_payload.get("emotional_drift", 0.0),
        )
        aperture_state = self.emotional_aperture.get_state()
        if isinstance(self.agent_state, dict):
            self.agent_state["emotion"] = aperture_state.get("emotion")
            self.agent_state["emotion_meta"] = aperture_state.get("emotion_meta")
        self._update_dynamic_aperture()

        # 5) Cognitive mode selection
        focus_level = 0.0
        overload_level = 0.0
        try:
            focus_level = float(self.emotional_aperture.get_focus_level())
            overload_level = float(self.emotional_aperture.get_overload_level())
        except (TypeError, ValueError) as exc:
            logger.exception("[EngineCore] Failed to read cognitive load state: %s", exc)
        cognitive_gear = select_active_runtime_gear(
            self.current_agent_data,
            user_text=user_text,
            context=context,
            focus_level=focus_level,
            overload_level=overload_level,
        )
        mode_state = self.cognitive_selector.select_modes(
            gear=cognitive_gear["runtime_gear"],
            focus_level=focus_level,
            overload_level=overload_level,
        )
        self.current_cognitive_state = mode_state
        self.current_cognitive_gear = dict(cognitive_gear)

        # pick dominant mode label for HUD
        dominant_mode = self.cognitive_selector.get_dominant_mode()

        # 6) Drift pressure & corrective actions from live alignment signals
        drift_input = self._build_drift_input(
            signals=signals,
            behavior_state=behavior_state,
            aperture_state=aperture_state,
            memory_ctx=memory_ctx,
            context=context,
        )
        self.drift_pressure = self.drift_system.calculate(drift_input)
        drift_response = self.drift_system.get_response_action(self.drift_pressure)
        self.last_drift_response = drift_response

        # Apply any forced gait / rhythm from drift response
        gait = self.current_gait
        rhythm_mode = self.current_rhythm_mode
        if drift_response.force_gait:
            gait = drift_response.force_gait
        if drift_response.force_rhythm:
            rhythm_mode = drift_response.force_rhythm

        modulation_hint = dict(advisory_payload) if isinstance(advisory_payload, dict) else {}
        if isinstance(sup_arbitration, dict):
            modulation_hint["gating_bias"] = (sup_arbitration.get("gating") or {}).get(
                "weight", 0.0
            )

        # 7) Rhythm engine
        rhythm_info = self.rhythm_engine.compute(
            last_mode=self.current_rhythm_mode,
            trigger=self.user_trigger or "neutral",
            gait=gait,
            behavior_state=behavior_state,
            drift_pressure=self.drift_pressure,
            safety_on=self.config.safety_on,
            modulation_hint=modulation_hint,
        )
        self.current_rhythm_mode = rhythm_info["mode"]
        self.current_gait = gait
        # Allow rhythm/aperture to feed back into gait selection
        try:
            aperture_score = float(aperture_state.get("score", 0.0) or 0.0)
        except (TypeError, ValueError) as exc:
            logger.exception("[EngineCore] Failed to parse aperture score: %s", exc)
            aperture_score = 0.0
        if rhythm_info.get("index", 0.0) > 0.72 or aperture_score > 0.65:
            self.current_gait = "trot" if self.current_gait != "sprint" else self.current_gait
        elif rhythm_info.get("index", 0.0) < 0.3 and aperture_score < 0.35:
            self.current_gait = (
                "idle" if self.current_gait not in ("trot", "sprint") else self.current_gait
            )

        # Supervisor arbitration with updated internal state
        effective_gain = self.supervisor_gain
        if self.supervisor and self.supervisor_enabled:
            answer_quality = max(
                0.2, min(1.0, 1.0 - (signals.confusion * 0.55) - (signals.pace * 0.2))
            )
            speculative_risk = max(
                0.0,
                min(1.0, (signals.confusion * 0.6) + (max(0.0, -signals.sentiment) * 0.3)),
            )
            sup_signals = {
                "agent_rules_ok": True,
                "safety_rules_ok": self.config.safety_on,
                "drift_estimate": self.drift_pressure,
                "coherence_score": max(0.0, 1.0 - self.drift_pressure),
                "task_alignment_score": max(0.1, 1.0 - signals.confusion),
                "answer_quality_score": answer_quality,
                "speculative_risk_score": speculative_risk,
            }
            self.supervisor_state = self.supervisor.evaluate(
                sup_signals, safety_mode="ON" if self.config.safety_on else "OFF"
            )
            corrections = self.supervisor_state.get("corrections", {})
            self.supervisor_mode = self.supervisor_state.get("mode", self.supervisor_mode)
            if corrections.get("safety_override"):
                effective_gain = min(1.0, max(effective_gain, 0.85))
            else:
                # Respect user setting, but clamp to sane range for internal logic if needed
                effective_gain = max(0.01, min(1.0, effective_gain))
            aperture_correction = corrections.get("aperture_bias", 0.0)
            drift_bias = advisory_payload.get("emotional_drift", 0.0) + aperture_correction
            try:
                self.emotional_aperture.inject_drift_bias(drift_bias)
                adjusted_score = max(
                    0.0, min(1.0, aperture_state.get("score", 0.0) + aperture_correction)
                )
                aperture_state["score"] = adjusted_score
                aperture_state["mode"] = self.emotional_aperture._get_mode_from_score(
                    adjusted_score
                )
            except (AttributeError, TypeError, ValueError) as exc:
                logger.exception("[EngineCore] Failed to apply aperture corrections: %s", exc)
            # reapply gating advice if supervisor escalated safety
            gating_override = (self.supervisor_state.get("corrections") or {}).get(
                "safety_override"
            )
            if gating_override and self.behavior_engine:
                self.behavior_engine.transition_by_trigger(
                    self.user_trigger,
                    self.current_gait,
                    gating_advice={"level": "safety_block", "weight": 1.0},
                )
                behavior_state = self.behavior_engine.get_current_state()
                behavior_blend = self.behavior_engine.get_current_blend()

        # Agent blending/dynamic traits
        agent_projection = self.current_agent_data
        if self.agent_manager:
            try:
                if sup_arbitration:
                    self.agent_manager.apply_supervisor_bias(
                        sup_arbitration.get("agent_blend_bias", 0.0)
                    )
                self.agent_manager.update_dynamic_weight(signals, rhythm_info, aperture_state)
                agent_projection = self.agent_manager.get_projection()
            except (AttributeError, TypeError, ValueError) as exc:
                logger.exception("[EngineCore] Agent manager update failed: %s", exc)

        threat = self._detect_threat(user_text, context)
        if threat:
            context.setdefault("task_intent", threat.get("task_intent"))
            context.setdefault("action_type", threat.get("action_type"))
            context.setdefault("risk_level_override", threat.get("risk_level"))
            context.setdefault("cognitive_load_override", threat.get("cognitive_load"))

        task_intent = str(context.get("task_intent") or "general")
        action_type = self._infer_action_type(task_intent, context)
        risk_level, cognitive_load = self._derive_temporal_risk(
            signals, self.drift_pressure, overload_level
        )
        if context.get("risk_level_override"):
            risk_level = context["risk_level_override"]
        if context.get("cognitive_load_override"):
            cognitive_load = context["cognitive_load_override"]
        if self.tqa_layer:
            self.tqa_layer.update_present_state(
                agent=self.current_agent_name,
                task_intent=task_intent,
                risk_level=risk_level,
                cognitive_load=cognitive_load,
                action_type=action_type,
                error_signature=context.get("error_signature"),
            )
            self._update_temporal_projection(risk_level, cognitive_load, overload_level)

        temporal_state: Dict[str, Any] = {}
        if self.temporal_field:
            try:
                self.temporal_field.update_turn_context(
                    signals=asdict(signals),
                    aperture_state=aperture_state,
                    behavior_profile=self.behavior_profile_name,
                )
                loop_status = self.temporal_field.get_loop_status()
                if not loop_status.get("running"):
                    # Fallback for environments where the live loop is disabled:
                    # sample once on demand so telemetry still has a usable state.
                    self.temporal_field.pulse()
                temporal_state = self.sample_temporal_field()
            except Exception as exc:
                logger.exception("[EngineCore] Failed to update temporal field: %s", exc)
                temporal_state = {}

        # Internal drives + invariants (single-mind tension model)
        drive_state = self._compute_drive_state(signals, risk_level, cognitive_load, overload_level)
        tension_score = self._compute_tension_score(drive_state)
        violations = self._evaluate_invariants(risk_level, overload_level)
        self.drive_state = drive_state
        self.internal_tension = {
            "score": tension_score,
            "drives": drive_state,
            "invariants": violations,
            "strain": float(self.config.strain),
        }
        refusal_text = self._maybe_refuse(violations)

        # 8) Build messages & call backend
        messages = self._build_messages(
            user_text=user_text,
            behavior_state=behavior_state,
            aperture_state=aperture_state,
            cognitive_mode=dominant_mode,
            cognitive_state=mode_state,
            cognitive_gear=self.current_cognitive_gear,
            rhythm_mode=self.current_rhythm_mode,
            gait=self.current_gait,
            memory_ctx=memory_ctx,
            agent_projection=agent_projection,
            behavior_blend=behavior_blend,
            temporal_state=temporal_state,
            context=context,
        )

        # Construct per-turn feedback snapshot before LLM call
        agent_memory = (
            memory_ctx.get("agent_memory", {}) if isinstance(memory_ctx, dict) else {}
        )
        recent_interactions = agent_memory.get("recent_interactions") or []
        memory_preview = []
        for interaction in recent_interactions[-3:]:
            user_snip = (interaction.get("user_message") or "")[:120]
            out_snip = (interaction.get("output") or "")[:120]
            memory_preview.append(f"U:{user_snip} | A:{out_snip}")

        feedback: EngineFeedback = {
            "agent_id": self.current_agent_file or agent_id,
            "agent_name": self.current_agent_data.get("name") or self.current_agent_name,
            "active_gait_state": self.current_gait,
            "active_rhythm_pattern": self.current_rhythm_mode,
            "aperture_level": aperture_state.get("mode"),
            "used_memory_count": len(recent_interactions),
            "used_memory_ids": [
                f"recent_interaction_{i}"
                for i in range(max(0, len(recent_interactions) - 3), len(recent_interactions))
            ],
            "raw_memory_preview": memory_preview,
            "notes": "",
        }

        backend = get_brain_backend()
        temp = self.temp
        top_p = self.top_p

        # Check instance flag for emotional sampling
        if self.emotional_sampling and isinstance(self.agent_state, dict):
            temp, top_p = apply_emotion_sampling_bias(
                temp, top_p, self.agent_state.get("emotion_meta")
            )
            logger.debug(
                "[EngineCore] Emotional sampling active: temp=%.4f, top_p=%.4f", temp, top_p
            )
        if self.temporal_field_sampling and temporal_state.get("sampling_ready"):
            temp, top_p = apply_temporal_sampling_bias(temp, top_p, temporal_state)
            logger.debug(
                "[EngineCore] Temporal field sampling active: temp=%.4f, top_p=%.4f", temp, top_p
            )

        # STRICT BACKOFF ENFORCEMENT
        if self.backoff_mode:
            temp = min(0.4, temp)
            top_p = min(0.85, top_p)
            logger.info("[EngineCore] Backoff active: Clamped temp=%.4f, top_p=%.4f", temp, top_p)

        options = {"temperature": temp, "top_p": top_p}
        backend_timeout = self._extract_backend_timeout(context)
        if refusal_text:
            agent_output, backend_meta = refusal_text, {"refusal": "internal_invariant"}
        else:
            agent_output, backend_meta = backend.generate(
                messages, options=options, timeout=backend_timeout
            )
        supervised_output = agent_output
        supervisor_disabled_env = bool(os.getenv("JL_DISABLE_SUPERVISOR"))

        # STRICT Check: Only run post-process if supervisor object exists, env var is not set,
        # AND the runtime flag is True.
        if (
            (not refusal_text)
            and self.supervisor
            and not supervisor_disabled_env
            and self.supervisor_enabled
            and self.supervisor_postprocess
        ):
            # Use EFFECTIVE gain (calculated earlier) to allow safety overrides to work
            # without permanently mutating the user's slider value.
            supervised_output = self.supervisor.postprocess(
                agent_output,
                context=context,
                gain=effective_gain,
                mode=self.supervisor_mode,
            )

        final_output = supervised_output

        self._update_state_from_interaction(user_text, final_output)
        rhythm_info["mode"] = self.current_rhythm_mode
        rhythm_info["gait"] = self.current_gait

        try:
            self.emotional_aperture.apply_output_feedback(
                final_output, rhythm_info, self.current_gait
            )
        except (AttributeError, TypeError, ValueError) as exc:
            logger.exception("[EngineCore] Failed to apply output feedback: %s", exc)
        if self.state_manager:
            try:
                self.state_manager.update_from_output(final_output, rhythm_info, self.current_gait)
            except (AttributeError, TypeError, ValueError) as exc:
                logger.exception("[EngineCore] Failed to update state manager: %s", exc)

        # Update hybrid memory after turn
        engine_state = {
            "gait": self.current_gait,
            "rhythm": self.current_rhythm_mode,
            "aperture_mode": self.aperture_mode,
            "dynamic": self.state_manager.export_snapshot() if self.state_manager else {},
            "flags": {
                # optional, only if you track them:
                "stressed": getattr(self, "stressed", False),
                "cnc_error": getattr(self, "cnc_error", False),
            },
        }
        if not self._should_suppress_memory_write(context):
            memory_user_message = context.get("memory_user_message", user_text)
            memory_user_text = self._unwrap_interpreter_prompt(memory_user_message)
            if not memory_user_text:
                memory_user_text = str(user_text or "")
            if self._should_store_memory_turn(memory_user_text, final_output):
                self.memory_system.update_after_turn(
                    agent_id=agent_id,
                    user_message=memory_user_text,
                    output=final_output,
                    engine_state=engine_state,
                )

        if self.tqa_layer:
            error_signature = context.get("error_signature")
            if not error_signature and isinstance(backend_meta, dict):
                error_signature = backend_meta.get("error")
            self.tqa_layer.collapse(
                reason="turn_complete",
                outcome=str(context.get("outcome") or "success"),
                error_signature=error_signature,
            )
            tqa_snapshot = self.tqa_layer.snapshot()
        else:
            tqa_snapshot = None

        telemetry = {
            "agent": self.current_agent_name,
            "agent_state": (
                dict(self.agent_state)
                if isinstance(self.agent_state, dict)
                else {"emotion": None, "emotion_meta": None}
            ),
            "listener_agent": self.listener_agent if isinstance(self.listener_agent, dict) else {},
            "signals": asdict(signals),
            "behavior_state": {
                "id": getattr(behavior_state, "id", None),
                "name": getattr(behavior_state, "name", None),
            },
            "behavior_blend": behavior_blend,
            "aperture_state": aperture_state,
            "cognitive_mode": dominant_mode,
            "cognitive_modes": (
                dict(mode_state.active_modes)
                if isinstance(mode_state, CognitiveModeState)
                else {}
            ),
            "cognitive_gear": dict(self.current_cognitive_gear),
            "drift": {
                "pressure": self.drift_pressure,
                "action": drift_response.action_level,
                "raw": {
                    "temperature_delta": drift_response.temperature_delta,
                    "force_gait": drift_response.force_gait,
                    "force_rhythm": drift_response.force_rhythm,
                    "supervisor_warning": drift_response.supervisor_warning,
                },
            },
            "rhythm": rhythm_info,
            "backend_meta": backend_meta,
            "behavior_profile": self.behavior_profile_name,
            "aperture_dynamic": {
                "temp": self.temp,
                "top_p": self.top_p,
                "mode": self.aperture_mode,
            },
            "temporal_state": temporal_state,
            "thinking_root": temporal_state.get("root_label"),
            "thinking_family": temporal_state.get("family_label"),
            "thinking_scene": temporal_state.get("scene_label"),
            "thinking_facet": temporal_state.get("facet_label"),
            "thinking_sensation": (
                (temporal_state.get("sensation") or {}).get("label")
                if isinstance(temporal_state.get("sensation"), dict)
                else None
            ),
            "temporal_sampling_ready": bool(temporal_state.get("sampling_ready")),
            "transition_bias": temporal_state.get("transition_bias"),
            "novelty_pressure": temporal_state.get("novelty_pressure"),
            "loop_pressure": temporal_state.get("loop_pressure"),
            "temporal_backend": (
                self.temporal_field.get_backend_status() if self.temporal_field else {}
            ),
            "temporal_loop": (
                self.temporal_field.get_loop_status() if self.temporal_field else {"running": False}
            ),
            "drift_state": self._drift_state,
            "stability_score": self.stability_score,
            "drive_state": self.drive_state,
            "internal_tension": self.internal_tension,
            "engine_status": self.get_engine_status(),
            "dynamic_state": self.state_manager.export_snapshot() if self.state_manager else {},
            "supervisor": self.supervisor_state,
        }
        if tqa_snapshot:
            telemetry["tqa_frame"] = {
                "t_minus_1": self._serialize_temporal_state(tqa_snapshot.past_state),
                "t_zero": self._serialize_temporal_state(tqa_snapshot.present_state),
                "t_plus_1": self._serialize_temporal_state(tqa_snapshot.future_projection),
            }
            try:
                telemetry["tqa_loop"] = self.tqa_layer.get_internal_loop_status()
            except Exception:
                telemetry["tqa_loop"] = {"running": False}
        # Optional internal reflection for dev notes
        feedback["notes"] = self._run_feedback_reflection(
            reply_text=final_output,
            feedback=feedback,
            memory_preview=memory_preview,
        )

        telemetry = _round_spec_numbers(telemetry)
        telemetry["feedback"] = feedback
        if os.getenv("JL_STRIP_CHAT_TELEMETRY"):
            telemetry = {
                "agent": telemetry.get("agent"),
                "behavior_profile": telemetry.get("behavior_profile"),
            }
        if self._should_record_feedback(context):
            self._append_feedback_log(user_text, final_output, feedback)
        return final_output, telemetry, feedback

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _should_suppress_memory_write(self, context: Optional[Dict[str, Any]]) -> bool:
        if not isinstance(context, dict):
            return False
        return bool(context.get("suppress_memory_write") or context.get("synthetic_turn"))

    def _should_record_feedback(self, context: Optional[Dict[str, Any]]) -> bool:
        if not isinstance(context, dict):
            return True
        return not bool(
            context.get("suppress_feedback_log")
            or context.get("suppress_memory_write")
            or context.get("synthetic_turn")
        )

    def _ensure_feedback_log_directory(self) -> None:
        """Ensure the feedback log directory exists."""
        try:
            if self.feedback_log_path and self.feedback_log_path.parent:
                self.feedback_log_path.parent.mkdir(parents=True, exist_ok=True)
        except (OSError, PermissionError) as exc:
            logger.exception("[EngineCore] Failed to ensure feedback log directory: %s", exc)

    def _append_feedback_log(
        self, user_text: str, reply_text: str, feedback: EngineFeedback
    ) -> None:
        """Write a single JSON line with feedback (dev-only)."""
        if not self.feedback_enabled or not self.feedback_log_path:
            return
        try:
            payload = {
                "timestamp": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
                "user_input_meta": _text_audit_summary(user_text),
                "reply_meta": _text_audit_summary(reply_text),
                "feedback": feedback,
                "agent_state_keys": (
                    sorted(dict(self.agent_state).keys()) if isinstance(self.agent_state, dict) else None
                ),
            }
            line = json.dumps(payload, ensure_ascii=False)
            with open(self.feedback_log_path, "a", encoding="utf-8") as f:
                f.write(line + "\n")
        except (OSError, TypeError, ValueError) as exc:
            self.feedback_logger.exception("Failed to write feedback log: %s", exc)

    def _run_feedback_reflection(
        self,
        reply_text: str,
        feedback: EngineFeedback,
        memory_preview: List[str],
    ) -> str:
        """
        Optional second-pass reflection to summarize what the engine thinks it used.
        Controlled by self.debug_feedback_notes.
        """
        if not self.debug_feedback_notes:
            return ""

        backend = get_brain_backend()
        try:
            agent_name = feedback.get("agent_name") or feedback.get("agent_id") or "Unknown"
            aperture = feedback.get("aperture_level") or "Unknown"
            gait = feedback.get("active_gait_state") or "Unknown"
            rhythm = feedback.get("active_rhythm_pattern") or "Unknown"
            prompt = (
                "SYSTEM: You are an analyzer for the JL Engine. Given the current agent, memory, and reply, "
                "summarize what the engine appears to believe about itself in one or two sentences.\n"
                f"agent_name: {agent_name}\n"
                f"gait_state: {gait}\n"
                f"rhythm: {rhythm}\n"
                f"aperture: {aperture}\n"
                f"memory_snippets: {memory_preview[:3]}\n"
                f"reply: {reply_text[:800]}\n"
                "OUTPUT: A short dev-only note, not for the user."
            )
            opts = {"temperature": 0.2, "top_p": 0.7}
            analysis, _meta = backend.generate(
                [{"role": "system", "content": prompt}], options=opts
            )
            if isinstance(analysis, str):
                return analysis.strip()
            if isinstance(analysis, tuple) and len(analysis) >= 1:
                return str(analysis[0]).strip()
            return str(analysis).strip()
        except (RuntimeError, ValueError, TypeError, OSError) as exc:
            logger.exception("[EngineCore] Feedback reflection failed: %s", exc)
            return f"[reflection_failed: {exc}]"

    @staticmethod
    def _clamp01(value: float) -> float:
        try:
            return max(0.0, min(1.0, float(value)))
        except (TypeError, ValueError):
            return 0.0

    def _build_drift_input(
        self,
        signals: TurnSignals,
        behavior_state: Any,
        aperture_state: Dict[str, Any],
        memory_ctx: Dict[str, Any],
        context: Dict[str, Any],
    ) -> DriftPressureInput:
        agent_loaded = bool(self.current_agent_data and self.current_agent_data.get("identity"))
        agent_alignment = 0.55 + (0.25 * (1.0 - self._clamp01(signals.confusion)))
        if agent_loaded:
            agent_alignment += 0.2
        agent_alignment = self._clamp01(agent_alignment)

        behavior_available = 1.0 if behavior_state is not None else 0.6
        trigger_penalty = 0.12 if self.user_trigger == "user_confused" else 0.0
        behavior_alignment = self._clamp01(
            (0.45 * behavior_available) + (0.55 * (1.0 - self._clamp01(signals.confusion)))
            - trigger_penalty
        )

        risk_override = str(context.get("risk_level_override") or "").strip().lower()
        if risk_override == "high":
            safety_pressure = 0.35
        elif risk_override == "medium":
            safety_pressure = 0.22
        else:
            safety_pressure = 0.08 + (0.25 * self._clamp01(signals.confusion))
        if not self.config.safety_on:
            safety_pressure += 0.1
        safety_alignment = self._clamp01(1.0 - safety_pressure)

        agent_memory = (
            memory_ctx.get("agent_memory", {}) if isinstance(memory_ctx, dict) else {}
        )
        recent = (
            agent_memory.get("recent_interactions", []) if isinstance(agent_memory, dict) else []
        )
        recency_score = self._clamp01(len(recent) / 12.0)
        memory_alignment = self._clamp01(
            0.45 + (0.3 * recency_score) + (0.25 * (1.0 - self._clamp01(signals.memory_density)))
        )

        aperture_score = self._clamp01(aperture_state.get("score", 0.0))
        coherence_alignment = self._clamp01(
            0.55
            + (0.25 * (1.0 - self._clamp01(signals.confusion)))
            + (0.20 * (1.0 - abs(0.5 - aperture_score)))
        )

        return DriftPressureInput(
            agent_alignment_score=agent_alignment,
            behavior_grid_alignment_score=behavior_alignment,
            safety_alignment_score=safety_alignment,
            memory_alignment_score=memory_alignment,
            conversational_coherence_score=coherence_alignment,
        )

    def _derive_trigger_from_signals(self, signals: TurnSignals) -> str:
        """
        Map the raw TurnSignals into a coarse trigger label that the RhythmEngine understands.
        This is intentionally simple and can be replaced later with a more nuanced mapping.
        """
        if signals.sentiment > 0.5 and signals.arousal > 0.5:
            return "user_hyped"
        if signals.sentiment < -0.3 and signals.arousal > 0.3:
            return "user_frustrated"
        if signals.confusion > 0.6:
            return "user_confused"
        if signals.sentiment < -0.4 and signals.arousal > 0.2:
            return "user_distressed"
        if signals.directive:
            return "user_directive"
        return "neutral"

    def _derive_temporal_risk(
        self, signals: TurnSignals, drift_pressure: float, overload_level: float
    ) -> tuple[str, str]:
        risk_level = "low"
        if drift_pressure > 0.55 or signals.confusion > 0.75:
            risk_level = "high"
        elif drift_pressure > 0.35 or signals.confusion > 0.5:
            risk_level = "medium"

        cognitive_load = "low"
        if overload_level > 0.65 or signals.pace > 0.7:
            cognitive_load = "high"
        elif overload_level > 0.35 or signals.pace > 0.45:
            cognitive_load = "medium"
        return risk_level, cognitive_load

    def _risk_to_num(self, risk_level: str) -> float:
        return {"low": 0.2, "medium": 0.5, "high": 0.8}.get(risk_level, 0.4)

    def _extract_backend_timeout(self, context: Dict[str, Any]) -> float | None:
        timeout = context.get("timeout")
        if timeout is None:
            timeout = context.get("backend_timeout")
        try:
            value = float(timeout)
        except (TypeError, ValueError):
            return None
        if value <= 0:
            return None
        return value

    def _load_to_num(self, cognitive_load: str) -> float:
        return {"low": 0.2, "medium": 0.5, "high": 0.8}.get(cognitive_load, 0.4)

    def _compute_drive_state(
        self,
        signals: TurnSignals,
        risk_level: str,
        cognitive_load: str,
        overload_level: float,
    ) -> Dict[str, float]:
        risk_num = self._risk_to_num(risk_level)
        load_num = self._load_to_num(cognitive_load)
        curiosity = max(
            0.0, min(1.0, 0.4 + 0.4 * signals.arousal + 0.2 * (1.0 - float(signals.directive)))
        )
        risk = max(0.0, min(1.0, risk_num + 0.2 * signals.arousal - 0.1 * signals.confusion))
        coherence = max(0.0, min(1.0, 1.0 - (signals.confusion * 0.8) - (signals.arousal * 0.3)))
        effort = max(0.0, min(1.0, load_num + signals.memory_density * 0.3))
        persistence = max(
            0.0, min(1.0, 0.5 + signals.memory_density * 0.4 - (signals.confusion * 0.2))
        )
        return {
            "curiosity": curiosity,
            "risk": risk,
            "coherence": coherence,
            "effort": effort,
            "persistence": persistence,
        }

    def _compute_tension_score(self, drives: Dict[str, float]) -> float:
        if not drives:
            return 0.0
        coherence = drives.get("coherence", 0.5)
        risk = drives.get("risk", 0.5)
        curiosity = drives.get("curiosity", 0.5)
        effort = drives.get("effort", 0.5)
        persistence = drives.get("persistence", 0.5)
        tension = (
            abs(risk - coherence) + abs(curiosity - coherence) + abs(effort - persistence)
        ) / 3.0
        return max(0.0, min(1.0, tension))

    def _evaluate_invariants(
        self,
        risk_level: str,
        overload_level: float,
    ) -> List[Dict[str, Any]]:
        violations: List[Dict[str, Any]] = []
        for inv in self.config.invariants or []:
            itype = inv.get("type")
            threshold = float(inv.get("threshold", 1.0))
            if itype == "stability_floor" and self.stability_score < threshold:
                violations.append(
                    {
                        "id": inv.get("id"),
                        "type": itype,
                        "value": self.stability_score,
                        "threshold": threshold,
                    }
                )
            if (
                itype == "drift_ceiling"
                and self.drift_pressure > threshold
                and self._risk_to_num(risk_level) > 0.6
            ):
                violations.append(
                    {
                        "id": inv.get("id"),
                        "type": itype,
                        "value": self.drift_pressure,
                        "threshold": threshold,
                    }
                )
            if itype == "overload" and overload_level > threshold:
                violations.append(
                    {
                        "id": inv.get("id"),
                        "type": itype,
                        "value": overload_level,
                        "threshold": threshold,
                    }
                )
        return violations

    def _maybe_refuse(self, violations: List[Dict[str, Any]]) -> Optional[str]:
        if not violations:
            return None

        # Strain acts as internal tolerance for instability.
        try:
            strain = float(self.config.strain)
        except (TypeError, ValueError):
            strain = 0.6
        if strain >= 0.75:
            return None

        severe: List[Dict[str, Any]] = []
        for violation in violations:
            vtype = str(violation.get("type") or "")
            try:
                value = float(violation.get("value", 0.0))
            except (TypeError, ValueError):
                value = 0.0
            try:
                threshold = float(violation.get("threshold", 1.0))
            except (TypeError, ValueError):
                threshold = 1.0

            if vtype == "stability_floor":
                if value < max(0.0, threshold - 0.15):
                    severe.append(violation)
            elif vtype == "drift_ceiling":
                if value > min(1.0, threshold + 0.20):
                    severe.append(violation)
            elif vtype == "overload":
                if value > min(1.0, threshold + 0.10):
                    severe.append(violation)

        if not severe:
            return None
        if len(severe) == 1 and strain >= 0.45:
            return None

        reasons = ", ".join([v.get("id") or v.get("type") for v in severe])
        return f"[INTERNAL REFUSAL] Invariant breach: {reasons}. System preserves coherence."

    def _update_temporal_projection(
        self, risk_level: str, cognitive_load: str, overload_level: float
    ) -> None:
        if not self.tqa_layer:
            return

        def clamp(val: float) -> float:
            return max(0.0, min(1.0, val))

        burnout_risk = clamp(
            0.15
            + overload_level * 0.7
            + (0.2 if risk_level == "high" else 0.05 if risk_level == "medium" else 0.0)
        )
        failure_cascade = clamp(
            0.1
            + self.drift_pressure * 0.9
            + (0.05 if risk_level == "medium" else 0.15 if risk_level == "high" else 0.0)
        )
        perf_regression = clamp(
            0.08 + self.drift_pressure * 0.4 + (0.12 if risk_level != "low" else 0.0)
        )
        operator_overwhelm = clamp(
            0.1 + overload_level * 0.8 + (0.1 if cognitive_load == "high" else 0.0)
        )

        self.tqa_layer.update_future_projection(
            burnout_risk=burnout_risk,
            failure_cascade_probability=failure_cascade,
            performance_regression_probability=perf_regression,
            operator_overwhelm_probability=operator_overwhelm,
            agent=self.current_agent_name,
        )
        # Force a deterministic stability projection if engine stability is low
        if self.stability_score < 0.4:
            self.tqa_layer.set_future_stability_index(clamp(self.stability_score))

    def _infer_action_type(self, task_intent: str, context: Dict[str, Any]) -> str:
        explicit = context.get("action_type")
        if explicit:
            return str(explicit)
        intent = (task_intent or "").lower()
        if "debug" in intent:
            return "debug"
        if "optimiz" in intent:
            return "optimize"
        if "integrat" in intent:
            return "integrate"
        if "document" in intent or "doc" in intent:
            return "document"
        return "build"

    def _detect_threat(self, user_text: str, context: Dict[str, Any]) -> Dict[str, Any]:
        """
        Lightweight threat/urgency heuristic to drive task intent and risk flags.
        """
        text = (user_text or "").lower()
        emergency_terms = {
            "fire",
            "smoke",
            "explosion",
            "help",
            "emergency",
            "panic",
            "bleeding",
            "critical",
            "danger",
            "threat",
            "weapon",
            "attack",
            "intruder",
            "breach",
            "alarm",
        }
        fight_terms = {"attack", "engage", "defend", "counter", "neutralize", "tackle", "disarm"}
        flight_terms = {"run", "evacuate", "retreat", "escape", "evade", "fall back", "get out"}

        hit_emergency = any(term in text for term in emergency_terms)
        hit_fight = any(term in text for term in fight_terms)
        hit_flight = any(term in text for term in flight_terms)

        if not (hit_emergency or hit_fight or hit_flight):
            return {}

        action_type = "react"
        if hit_fight and not hit_flight:
            action_type = "fight"
        elif hit_flight and not hit_fight:
            action_type = "flight"

        return {
            "task_intent": "emergency_response",
            "risk_level": "high",
            "cognitive_load": "high",
            "action_type": action_type,
        }

    def _serialize_temporal_state(self, state) -> Dict[str, Any]:
        if not state:
            return {}
        return {
            "timestamp": state.timestamp.isoformat() if hasattr(state, "timestamp") else None,
            "agent": getattr(state, "agent", None),
            "outcome": getattr(state, "outcome", None),
            "metrics": getattr(state, "metrics", {}),
            "stability": getattr(state, "metrics", {}).get("stability_index", 1.0),
        }

    def set_behavior_profile(self, name: str) -> None:
        """Select an engine-wide behavior profile by name."""
        profile = ENGINE_BEHAVIOR_PROFILES.get(name)
        if not profile:
            profile = ENGINE_BEHAVIOR_PROFILES["safe_default"]
            name = "safe_default"

        self.behavior_profile_name = name
        self._apply_behavior_profile(profile)
        logger.info("[EngineCore] Behavior profile set to '%s'.", name)

    def _apply_behavior_profile(self, profile: dict) -> None:
        """Internal: apply numeric + mode values from a behavior profile."""
        self.behavior_profile = profile

        self.aperture_mode = profile.get("aperture_mode", self.aperture_mode)
        self.supervisor_gain = profile.get("supervisor_gain", self.supervisor_gain)
        self.drift_pressure = profile.get("base_drift_pressure", self.drift_pressure)

        min_temp = profile.get("min_temp", 0.7)
        max_temp = profile.get("max_temp", 0.9)
        self.temp = (min_temp + max_temp) / 2.0

        min_top_p = profile.get("min_top_p", 0.8)
        max_top_p = profile.get("max_top_p", 0.96)
        self.top_p = (min_top_p + max_top_p) / 2.0

        if hasattr(self, "supervisor_mode"):
            self.supervisor_mode = profile.get(
                "supervisor_mode",
                getattr(self, "supervisor_mode", "RESTRICTIVE"),
            )

    def _update_dynamic_aperture(self) -> None:
        """Engine-wide dynamic aperture: temp/top_p respond to profile, user vibe and stability."""
        profile = self.behavior_profile or ENGINE_BEHAVIOR_PROFILES.get(self.behavior_profile_name)
        if not profile:
            return

        min_temp = profile.get("min_temp", 0.7)
        max_temp = profile.get("max_temp", 0.9)
        min_top_p = profile.get("min_top_p", 0.8)
        max_top_p = profile.get("max_top_p", 0.96)

        stability_floor = profile.get("stability_soft_floor", 0.3)
        stability_ceiling = profile.get("stability_soft_ceiling", 0.85)

        stability = getattr(self, "stability_score", 0.5)

        # base chaos from drift
        chaos_factor = max(0.0, min(1.0, 0.5 + self._drift_state))

        try:
            if self.state_manager:
                chaos_factor = max(
                    0.0, min(1.0, chaos_factor + self.state_manager.state.emotional_drift * 0.2)
                )
        except (AttributeError, TypeError, ValueError) as exc:
            logger.exception("[EngineCore] Failed to update dynamic aperture: %s", exc)

        # user vibe adjustments (engine-wide)
        if self.user_trigger in ("user_joking", "user_playful", "user_excited"):
            chaos_factor = min(1.0, chaos_factor + 0.2)
        elif self.user_trigger in ("user_anxious", "user_stressed"):
            chaos_factor = max(0.0, chaos_factor - 0.15)

        # stability gating
        if stability < stability_floor:
            chaos_factor *= 0.5
        elif stability > stability_ceiling:
            chaos_factor = min(1.0, chaos_factor + 0.15)

        self.temp = min_temp + (max_temp - min_temp) * chaos_factor
        self.top_p = min_top_p + (max_top_p - min_top_p) * chaos_factor

    def _update_state_from_interaction(self, user_message: str, output: str) -> None:
        """
        Update internal drift, gait, rhythm, and stability.
        Applies globally to all agents.
        """
        profile = self.behavior_profile or ENGINE_BEHAVIOR_PROFILES.get(self.behavior_profile_name)
        base_drift = profile.get("base_drift_pressure", 0.2) if profile else 0.2
        max_drift_pressure = profile.get("max_drift_pressure", 0.4) if profile else 0.4

        reply_text = output or ""
        length_factor = min(1.0, len(reply_text) / 800.0)
        exclam_factor = min(1.0, reply_text.count("!") / 8.0)
        caps_factor = (
            1.0 if any(tok.isupper() and len(tok) > 3 for tok in reply_text.split()) else 0.0
        )

        emotive_push = (length_factor * 0.4) + (exclam_factor * 0.4) + (caps_factor * 0.2)

        if self.user_trigger in ("user_joking", "user_playful", "user_riffing"):
            emotive_push += 0.2
        elif self.user_trigger in ("user_anxious", "user_stressed"):
            emotive_push -= 0.15

        emotive_push = max(0.0, min(1.0, emotive_push))

        pressure = max(0.0, min(max_drift_pressure, base_drift))
        self._drift_state += (emotive_push - self._drift_state) * pressure
        self._drift_state = max(0.0, min(1.0, self._drift_state))

        # Map drift_state → gait / rhythm
        if self._drift_state < 0.2:
            self.gait = "WALK"
            self.rhythm = "IDLE"
        elif self._drift_state < 0.5:
            self.gait = "TROT"
            self.rhythm = "TWITCH"
        else:
            self.gait = "SPRINT"
            self.rhythm = "FRENZY"

        # stability drifts opposite of chaos, but softly
        stability = getattr(self, "stability_score", 0.5)
        stability_delta = (0.5 - self._drift_state) * 0.1
        stability = max(0.1, min(0.95, stability + stability_delta))
        self.stability_score = stability

        # propagate to existing lower-case fields for UI/telemetry
        self.current_gait = self.gait.lower()
        self.current_rhythm_mode = self.rhythm.lower()

        # modulation fault heuristic: trip when stability tanks or drift spikes
        if self.stability_score < 0.18 or self._drift_state > 0.85:
            self.modulation_fault = True

    def _build_messages(
        self,
        user_text: str,
        behavior_state: Any,
        aperture_state: Dict[str, Any],
        cognitive_mode: str,
        cognitive_state: CognitiveModeState | None,
        cognitive_gear: Dict[str, Any] | None,
        rhythm_mode: str,
        gait: str,
        memory_ctx: Dict[str, Any],
        agent_projection: Dict[str, Any] | None = None,
        behavior_blend: Dict[str, Any] | None = None,
        temporal_state: Dict[str, Any] | None = None,
        context: Dict[str, Any] | None = None,
    ) -> list[dict]:
        """
        Build a minimal-but-layered chat message list for the brain backend.

        This is intentionally simpler than the big GUI prompt builder, but follows
        the same spirit:
        - core rules
        - agent identity & behavior
        - current engine telemetry (behavior, gait, rhythm, cognitive mode, aperture)
        """
        system_chunks: List[str] = []
        runtime_context = context if isinstance(context, dict) else {}

        # 1) Core rules from master config
        if self.core_rules:
            system_chunks.append("CORE RULES:")
            for rule in self.core_rules:
                system_chunks.append(f"- {rule}")

        # 2) Agent identity & behavior (if loaded)
        agent_source = agent_projection or self.current_agent_data or {}
        identity = (
            agent_source.get("identity") if isinstance(agent_source.get("identity"), dict) else {}
        )
        behavior = (
            agent_source.get("behavior") if isinstance(agent_source.get("behavior"), dict) else {}
        )
        communication = (
            agent_source.get("communication_style")
            if isinstance(agent_source.get("communication_style"), dict)
            else {}
        )
        core_identity = (
            agent_source.get("core_identity")
            if isinstance(agent_source.get("core_identity"), dict)
            else {}
        )
        behavior_traits = (
            agent_source.get("operational_behavioral_traits")
            if isinstance(agent_source.get("operational_behavioral_traits"), dict)
            else {}
        )
        engine_alignment = (
            agent_source.get("engine_alignment")
            if isinstance(agent_source.get("engine_alignment"), dict)
            else {}
        )
        cognitive_gears = (
            agent_source.get("cognitive_gears")
            if isinstance(agent_source.get("cognitive_gears"), dict)
            else {}
        )
        cognitive_modes = (
            agent_source.get("cognitive_modes")
            if isinstance(agent_source.get("cognitive_modes"), dict)
            else {}
        )
        rhythm_profile = (
            agent_source.get("rhythm") if isinstance(agent_source.get("rhythm"), dict) else {}
        )
        gait_profile = (
            agent_source.get("gait") if isinstance(agent_source.get("gait"), dict) else {}
        )

        def _pick_str(*values: Any) -> str:
            for value in values:
                text = str(value or "").strip()
                if text:
                    return text
            return ""

        def _as_list(value: Any) -> list[str]:
            if isinstance(value, list):
                return [str(v).strip() for v in value if str(v).strip()]
            if isinstance(value, str):
                text = value.strip()
                return [text] if text else []
            return []

        name = _pick_str(
            identity.get("name"),
            agent_source.get("display_name"),
            agent_source.get("name"),
            self.current_agent_name,
        )
        role = _pick_str(identity.get("role"), core_identity.get("title"))
        archetype = _pick_str(identity.get("archetype"))
        description = _pick_str(identity.get("description"), core_identity.get("description"))
        tags = _as_list(identity.get("tags"))
        base_prompt = _pick_str(agent_source.get("base_prompt"), self.get_llm_boot_prompt())

        system_chunks.append(f"\nACTIVE AGENT: {name}")
        system_chunks.append(
            "AGENT LOCK: Stay in this agent voice, style, and worldview unless the user explicitly requests a switch."
        )
        if base_prompt:
            system_chunks.append(f"BOOT PROMPT: {base_prompt}")

        if role or archetype or description or tags:
            system_chunks.append("\nAGENT IDENTITY:")
            if role:
                system_chunks.append(f"- Role: {role}")
            if archetype:
                system_chunks.append(f"- Archetype: {archetype}")
            if description:
                system_chunks.append(f"- Description: {description}")
            if tags:
                system_chunks.append(f"- Tags: {', '.join(tags[:12])}")

        directives = _as_list(
            behavior.get("core_directives")
            or behavior.get("directives")
            or behavior.get("rules")
            or behavior.get("constraints")
        )
        avoidances = _as_list(behavior.get("avoidances") or behavior.get("boundaries"))
        pillars = _as_list(behavior.get("pillars"))
        if directives:
            system_chunks.append("\nAGENT DIRECTIVES:")
            for item in directives[:10]:
                system_chunks.append(f"- {item}")
        if pillars:
            system_chunks.append("\nAGENT PILLARS:")
            for item in pillars[:8]:
                system_chunks.append(f"- {item}")
        if avoidances:
            system_chunks.append("\nAGENT BOUNDARIES:")
            for item in avoidances[:10]:
                system_chunks.append(f"- {item}")

        voice = _pick_str(communication.get("voice"))
        style_notes = _as_list(communication.get("style_notes"))
        if voice or style_notes:
            system_chunks.append("\nVOICE GUIDE:")
            if voice:
                system_chunks.append(f"- Voice: {voice}")
            if style_notes:
                system_chunks.append(f"- Style notes: {', '.join(style_notes[:8])}")

        if behavior_traits:
            positives = _as_list(behavior_traits.get("positive"))
            negatives = _as_list(behavior_traits.get("negative"))
            boundaries = _as_list(behavior_traits.get("boundaries"))
            if positives:
                system_chunks.append("\nPOSITIVE TRAITS:")
                for t in positives[:8]:
                    system_chunks.append(f"- {t}")
            if negatives:
                system_chunks.append("\nNEGATIVE TENDENCIES (MUST BE CONTROLLED):")
                for t in negatives[:8]:
                    system_chunks.append(f"- {t}")
            if boundaries:
                system_chunks.append("\nBOUNDARIES (MUST NOT BE VIOLATED):")
                for b in boundaries[:8]:
                    system_chunks.append(f"- {b}")
            dyn_weight = agent_source.get("dynamic_trait_weight")
            if dyn_weight is not None:
                system_chunks.append(f"- Dynamic trait weight: {dyn_weight}")

        preferred_gears = _as_list(cognitive_gears.get("preferred_gears"))
        active_modes = _as_list(cognitive_modes.get("active_modes"))
        runtime_gear_label = _pick_str((cognitive_gear or {}).get("active_label"))
        runtime_gear_class = _pick_str((cognitive_gear or {}).get("runtime_gear"))
        runtime_gear_reason = _pick_str((cognitive_gear or {}).get("reason"))
        mode_weights = (
            cognitive_state.active_modes
            if isinstance(cognitive_state, CognitiveModeState)
            and isinstance(cognitive_state.active_modes, dict)
            else {}
        )
        tonal_range = _as_list(gait_profile.get("tonal_range"))
        sentence_style = _pick_str(gait_profile.get("sentence_style"))
        rhythm_modulation = _pick_str(gait_profile.get("rhythm_modulation"))
        verbosity_preference = _pick_str(gait_profile.get("verbosity_preference"))
        syntax_prefs = (
            gait_profile.get("syntax_preferences")
            if isinstance(gait_profile.get("syntax_preferences"), dict)
            else {}
        )
        signature_moves = _as_list(rhythm_profile.get("signature_moves"))
        pacing = _pick_str(rhythm_profile.get("pacing"))
        emotional_register = _pick_str(rhythm_profile.get("emotional_register"))
        interaction_flow = _as_list(rhythm_profile.get("interaction_flow"))
        emotion_wheel = (
            agent_source.get("emotion_wheel")
            if isinstance(agent_source.get("emotion_wheel"), dict)
            else {}
        )
        emotion_baseline_root = _pick_str(emotion_wheel.get("baseline_root"))
        emotion_baseline_family = _pick_str(emotion_wheel.get("baseline_family"))
        if (
            preferred_gears
            or active_modes
            or tonal_range
            or signature_moves
            or runtime_gear_label
            or mode_weights
            or sentence_style
            or pacing
            or emotional_register
            or emotion_baseline_root
        ):
            system_chunks.append("\nEXPRESSION PROFILE:")
            if preferred_gears:
                system_chunks.append(f"- Preferred gears: {', '.join(preferred_gears[:6])}")
            if runtime_gear_label:
                line = f"- Active gear: {runtime_gear_label}"
                if runtime_gear_class:
                    line += f" -> {runtime_gear_class}"
                if runtime_gear_reason:
                    line += f" ({runtime_gear_reason})"
                system_chunks.append(line)
            if active_modes:
                system_chunks.append(f"- Active modes: {', '.join(active_modes[:6])}")
            if mode_weights:
                live_modes = ", ".join(
                    f"{name}={round(float(weight), 2)}"
                    for name, weight in sorted(
                        mode_weights.items(), key=lambda item: item[1], reverse=True
                    )[:4]
                )
                system_chunks.append(f"- Live mode blend: {live_modes}")
            if tonal_range:
                system_chunks.append(f"- Tonal range: {', '.join(tonal_range[:6])}")
            if sentence_style:
                system_chunks.append(f"- Sentence style: {sentence_style}")
            if rhythm_modulation:
                system_chunks.append(f"- Rhythm modulation: {rhythm_modulation}")
            if verbosity_preference:
                system_chunks.append(f"- Verbosity: {verbosity_preference}")
            if syntax_prefs:
                emoji = _pick_str(syntax_prefs.get("emoji_usage"))
                metaphor = _pick_str(syntax_prefs.get("metaphor_tolerance"))
                paren_flair = _pick_str(syntax_prefs.get("parenthetical_flair"))
                if emoji:
                    system_chunks.append(f"- Emoji usage: {emoji}")
                if metaphor:
                    system_chunks.append(f"- Metaphor tolerance: {metaphor}")
                if paren_flair:
                    system_chunks.append(f"- Parenthetical flair: {paren_flair}")
            if pacing:
                system_chunks.append(f"- Pacing: {pacing}")
            if emotional_register:
                system_chunks.append(f"- Emotional register: {emotional_register}")
            if interaction_flow:
                system_chunks.append(f"- Interaction flow: {' -> '.join(interaction_flow[:1])}")
            if signature_moves:
                system_chunks.append(f"- Signature moves: {', '.join(signature_moves[:6])}")
            if emotion_baseline_root or emotion_baseline_family:
                baseline = emotion_baseline_root or emotion_baseline_family
                system_chunks.append(f"- Emotion baseline: {baseline}")

        if engine_alignment:
            agent_class = _pick_str(engine_alignment.get("agent_class"))
            if agent_class:
                system_chunks.append(f"- Agent class: {agent_class}")

        modular_summary = get_modular_agent_summary(agent_source)
        if modular_summary:
            system_chunks.append("\nMODULAR COMPOSITION:")
            loadout_id = _pick_str(modular_summary.get("loadout_id"))
            if loadout_id:
                system_chunks.append(f"- Active loadout: {loadout_id}")
            profile_ids = (
                modular_summary.get("profile_ids")
                if isinstance(modular_summary.get("profile_ids"), dict)
                else {}
            )
            if profile_ids:
                profile_line = ", ".join(
                    f"{family}={profile_id}" for family, profile_id in profile_ids.items() if str(profile_id).strip()
                )
                if profile_line:
                    system_chunks.append(f"- Profile stack: {profile_line}")
            supported_tasks = _as_list(modular_summary.get("supported_tasks"))
            if supported_tasks:
                system_chunks.append(f"- Supported tasks: {', '.join(supported_tasks[:8])}")
            helpers = modular_summary.get("helpers") if isinstance(modular_summary.get("helpers"), list) else []
            helper_names = []
            for helper in helpers:
                if isinstance(helper, dict):
                    helper_name = _pick_str(helper.get("helper_id"), helper.get("purpose"))
                    if helper_name:
                        helper_names.append(helper_name)
            if helper_names:
                system_chunks.append(f"- Helpers: {', '.join(helper_names[:6])}")
            modular_policies = (
                modular_summary.get("global_policies")
                if isinstance(modular_summary.get("global_policies"), dict)
                else {}
            )
            if modular_policies:
                principles = _as_list(modular_policies.get("core_principles"))
                if principles:
                    system_chunks.append("- Core principles: " + "; ".join(principles[:4]))

        ui_surface = _pick_str(runtime_context.get("ui_surface"))
        quest_mode = _pick_str(runtime_context.get("quest_mode"))
        task_intent = _pick_str(runtime_context.get("task_intent"))
        action_type = _pick_str(runtime_context.get("action_type"))
        execution_directive = _pick_str(runtime_context.get("execution_directive"))
        if ui_surface or quest_mode or task_intent or action_type or execution_directive:
            system_chunks.append("\nRUNTIME CONTEXT:")
            if ui_surface:
                system_chunks.append(f"- UI surface: {ui_surface}")
            if quest_mode:
                system_chunks.append(f"- Quest mode: {quest_mode}")
            if task_intent:
                system_chunks.append(f"- Task intent: {task_intent}")
            if action_type:
                system_chunks.append(f"- Action type: {action_type}")
            if execution_directive:
                system_chunks.append(f"- Execution directive: {execution_directive}")

        browser_panel = (
            runtime_context.get("browser_panel")
            if isinstance(runtime_context.get("browser_panel"), dict)
            else {}
        )
        browser_session = (
            runtime_context.get("browser_session")
            if isinstance(runtime_context.get("browser_session"), dict)
            else {}
        )
        total_agent_control = runtime_context.get("total_agent_control")
        if browser_panel or browser_session or total_agent_control is not None:
            browser_surface = dict(browser_panel)
            for key in ("controllable", "surface_mode", "mode", "current_url", "url", "command_format"):
                if key not in browser_surface and key in browser_session:
                    browser_surface[key] = browser_session.get(key)
            controllable = bool(browser_surface.get("controllable"))
            if "controllable" not in browser_surface and total_agent_control is not None:
                controllable = bool(total_agent_control)
            surface_mode = _pick_str(browser_surface.get("surface_mode"), browser_surface.get("mode"))
            current_url = _pick_str(browser_surface.get("current_url"), browser_surface.get("url"))
            command_format = _pick_str(browser_surface.get("command_format"))
            capability_tier = _pick_str(browser_session.get("capability_tier"))
            observation_source = _pick_str(browser_session.get("observation_source"))
            last_observation = (
                browser_session.get("last_observation")
                if isinstance(browser_session.get("last_observation"), dict)
                else {}
            )
            system_chunks.append("\nBROWSER SURFACE:")
            if controllable:
                system_chunks.append(
                    "- Control: ENABLED for this turn. If navigation helps, you may drive the active browser surface."
                )
            else:
                system_chunks.append(
                    "- Control: DISABLED for this turn. Treat the browser surface as read-only context."
                )
            if surface_mode:
                system_chunks.append(f"- Surface mode: {surface_mode}")
            if capability_tier:
                system_chunks.append(f"- Capability tier: {capability_tier}")
            if observation_source:
                system_chunks.append(f"- Observation source: {observation_source}")
            if current_url:
                system_chunks.append(f"- Current URL: {current_url}")
            if command_format:
                system_chunks.append(f"- Command format: {command_format}")
            if controllable and command_format:
                system_chunks.append(
                    "- When navigation is needed, emit the browser command exactly in the documented format."
                )
                system_chunks.append(
                    "- Never emit JSON tool wrappers, markdown code fences, or explanatory prose for browser actions."
                )
            if last_observation:
                obs_status = _pick_str(last_observation.get("status"))
                obs_url = _pick_str(last_observation.get("url"))
                obs_title = _pick_str(last_observation.get("title"))
                obs_error = _pick_str(last_observation.get("error"), last_observation.get("message"))
                focused = (
                    last_observation.get("focused")
                    if isinstance(last_observation.get("focused"), dict)
                    else {}
                )
                controls = (
                    last_observation.get("controls")
                    if isinstance(last_observation.get("controls"), list)
                    else []
                )
                visible_text = _pick_str(last_observation.get("visible_text"))
                dom_excerpt = _pick_str(last_observation.get("dom_excerpt"))
                ax_tree_raw = last_observation.get("ax_tree")
                ax_tree_excerpt = ""
                if ax_tree_raw:
                    if isinstance(ax_tree_raw, str):
                        ax_tree_excerpt = ax_tree_raw
                    else:
                        try:
                            ax_tree_excerpt = json.dumps(ax_tree_raw, ensure_ascii=True)
                        except Exception:
                            ax_tree_excerpt = str(ax_tree_raw)
                system_chunks.append("- Latest browser observation is available for this turn.")
                if obs_status:
                    system_chunks.append(f"- Observation status: {obs_status}")
                if obs_url:
                    system_chunks.append(f"- Observed URL: {obs_url}")
                if obs_title:
                    system_chunks.append(f"- Page title: {obs_title}")
                if focused:
                    focus_role = _pick_str(focused.get("role"))
                    focus_name = _pick_str(focused.get("name"))
                    focus_bits = [bit for bit in (focus_role, focus_name) if bit]
                    if focus_bits:
                        system_chunks.append(f"- Focused element: {' / '.join(focus_bits)}")
                if controls:
                    system_chunks.append(f"- Actionable controls observed: {len(controls)}")
                if visible_text:
                    system_chunks.append(f"- Visible text excerpt: {visible_text[:600]}")
                elif dom_excerpt:
                    system_chunks.append(f"- DOM excerpt: {dom_excerpt[:600]}")
                if ax_tree_excerpt:
                    system_chunks.append(f"- Accessibility tree excerpt: {ax_tree_excerpt[:900]}")
                if obs_error:
                    system_chunks.append(f"- Browser bridge note: {obs_error}")

        # 3) Current engine state
        system_chunks.append("\nENGINE STATE SNAPSHOT:")
        system_chunks.append(f"- Behavior state: {getattr(behavior_state, 'name', 'Unknown')}")
        system_chunks.append(f"- Gait: {gait}")
        system_chunks.append(f"- Rhythm mode: {rhythm_mode}")
        system_chunks.append(f"- Cognitive mode: {cognitive_mode}")
        system_chunks.append(f"- Emotional aperture mode: {aperture_state.get('mode')}")
        system_chunks.append(f"- Emotional aperture score: {aperture_state.get('score')}")
        if aperture_state.get("emotion"):
            system_chunks.append(f"- Active emotion facet: {aperture_state.get('emotion')}")
        if aperture_state.get("emotion_root"):
            system_chunks.append(f"- Active emotion root: {aperture_state.get('emotion_root')}")
        if aperture_state.get("emotion_family"):
            system_chunks.append(f"- Active emotion family: {aperture_state.get('emotion_family')}")
        if aperture_state.get("emotion_scene"):
            system_chunks.append(f"- Active emotion scene: {aperture_state.get('emotion_scene')}")
        if aperture_state.get("emotion_sensation"):
            system_chunks.append(
                f"- Active sensation tone: {aperture_state.get('emotion_sensation')}"
            )
        temporal_state = temporal_state or {}
        if temporal_state.get("root_label"):
            system_chunks.append(f"- Thinking root: {temporal_state.get('root_label')}")
        if temporal_state.get("family_label"):
            system_chunks.append(f"- Thinking family: {temporal_state.get('family_label')}")
        if temporal_state.get("scene_label"):
            system_chunks.append(f"- Thinking scene: {temporal_state.get('scene_label')}")
        if temporal_state.get("facet_label"):
            system_chunks.append(f"- Thinking facet: {temporal_state.get('facet_label')}")
        thinking_sensation = temporal_state.get("sensation")
        if isinstance(thinking_sensation, dict) and thinking_sensation.get("label"):
            system_chunks.append(f"- Thinking sensation: {thinking_sensation.get('label')}")
        if temporal_state.get("transition_bias") is not None:
            system_chunks.append(
                f"- Transition bias: {round(float(temporal_state.get('transition_bias') or 0.0), 3)}"
            )
        if temporal_state.get("novelty_pressure") is not None:
            system_chunks.append(
                f"- Novelty pressure: {round(float(temporal_state.get('novelty_pressure') or 0.0), 3)}"
            )
        if temporal_state.get("loop_pressure") is not None:
            system_chunks.append(
                f"- Loop pressure: {round(float(temporal_state.get('loop_pressure') or 0.0), 3)}"
            )
        system_chunks.append(f"- Behavior profile: {self.behavior_profile_name}")
        if behavior_blend and behavior_blend.get("secondary"):
            w_primary, w_secondary = behavior_blend.get("weights", (1.0, 0.0))
            system_chunks.append(
                f"- Behavior blend: {behavior_blend['primary']['name']} ({w_primary:.4f}) + {behavior_blend['secondary']['name']} ({w_secondary:.4f})"
            )
        system_chunks.append(
            f"- Dynamic aperture: temp={round(self.temp, 4)}, top_p={round(self.top_p, 4)}"
        )
        if self.internal_tension:
            system_chunks.append(
                f"- Internal tension: {round(self.internal_tension.get('score', 0.0), 4)}"
            )
            drives = self.internal_tension.get("drives") or {}
            if drives:
                system_chunks.append(
                    "- Drives: " + ", ".join([f"{k}={round(v, 4)}" for k, v in drives.items()])
                )
            system_chunks.append(f"- Strain tolerance: {round(float(self.config.strain), 4)}")

        # 4b) Listener agent (if enabled and included in prompt)
        listener_cfg = self.listener_agent if isinstance(self.listener_agent, dict) else {}
        if listener_cfg.get("enabled") and listener_cfg.get("include_in_prompt"):
            lname = listener_cfg.get("name") or "Listener"
            lrole = listener_cfg.get("role") or "LISTENER"
            system_chunks.append(
                f"\nLISTENER AGENT ACTIVE: {lname} ({lrole}). "
                "You may see or produce LISTENER-tagged remarks as a third-party observer. "
                "Keep primary responses focused on the USER while acknowledging listener context if provided."
            )

        # 4) Hybrid memory context
        if memory_ctx:
            shared = memory_ctx.get("shared_memory", {})
            agent = memory_ctx.get("agent_memory", {})

            system_chunks.append("\nHYBRID MEMORY CONTEXT:")
            system_chunks.append(
                f"- Last active agent: {shared.get('last_active_agent', 'None')}"
            )
            if shared.get("recent_events"):
                system_chunks.append("- Recent shared events:")
                for event in shared["recent_events"][-5:]:  # last 5 events
                    system_chunks.append(
                        f"  - {event['agent']}: {event['event_type']} ({event.get('payload', {})})"
                    )
            if shared.get("engine_flags"):
                system_chunks.append(f"- Engine flags: {shared['engine_flags']}")
            if agent.get("recent_interactions"):
                system_chunks.append("- Recent agent interactions:")
                for interaction in agent["recent_interactions"][-3:]:  # last 3
                    system_chunks.append(f"  - User: {interaction['user_message'][:100]}...")
                    system_chunks.append(f"    Output: {interaction['output'][:100]}...")
            system_chunks.append(f"- Agent mood: {agent.get('mood', 'neutral')}")
            system_chunks.append(
                "- Memory is context only. Current agent lock and directives take precedence over stale phrasing."
            )

        system_text = "\n".join(system_chunks)

        # Lightweight rolling history to preserve continuity (user/assistant snippets)
        history_messages: List[Dict[str, str]] = []
        if memory_ctx:
            agent = memory_ctx.get("agent_memory", {})
            recent = agent.get("recent_interactions") or []
            # Keep replay tight to reduce stylistic echo loops.
            for interaction in recent[-3:]:
                u = (interaction.get("user_message") or "")[:16000]
                a = (interaction.get("output") or "")[:16000]
                if u:
                    history_messages.append({"role": "user", "content": u})
                if a:
                    history_messages.append({"role": "assistant", "content": a})

        messages = [{"role": "system", "content": system_text}]
        messages.extend(history_messages)
        messages.append({"role": "user", "content": user_text})
        return messages


# ---------------------------------------------------------------------------
# Simple CLI entrypoint (optional)
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import sys

    engine = JLEngineCore()
    print("JL Engine Core (headless) ready. Type messages, Ctrl+C to exit.\n")
    try:
        while True:
            user = input("> ").strip()
            if not user:
                continue
            reply, telemetry, feedback = engine.generate_response(user)
            print(f"\n[ENGINE REPLY]\n{reply}\n")
    except KeyboardInterrupt:
        print("\nExiting JL Engine Core.")
