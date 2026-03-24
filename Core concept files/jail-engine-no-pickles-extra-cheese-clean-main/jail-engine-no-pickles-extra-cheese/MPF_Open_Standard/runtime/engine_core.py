"""
engine_core.py - JL Engine Core Orchestrator

This module provides a *unified, headless* orchestration layer for the JL Engine.

It pulls together:
- Behavior grid (BehaviorStateMachine)
- Conversational signal scoring (SignalScorer)
- Emotional aperture (EmotionalAperture)
- Cognitive mode selector (CognitiveModeSelector)
- Rhythm engine (RhythmEngine)
- Drift pressure regulator (DriftPressureSystem)
- Modular Persona Framework (MPF) registry
- Backend routing (brain backend via backends.py)

The goal is to give the rest of the app a SINGLE entry point:

    from engine_core import JLEngineCore, EngineConfig

    engine = JLEngineCore()
    reply, telemetry, feedback = engine.generate_response("Hello there!", persona_name="The Helper")

This file is intentionally UI-agnostic (no Tkinter imports) so it can be
re-used by:
- the existing Tk GUI (main_app.py),
- CLI tools,
- other automation layers (e.g. Open Interpreter, VS Code agents),
- or future serial / hardware controllers.
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass, asdict
from datetime import datetime
from pathlib import Path
from typing import Dict, Any, Optional, Tuple, List, TypedDict

from .logging_setup import get_logger

from .behavior_engine import BehaviorStateMachine
from .cognitive_modes import CognitiveModeSelector, CognitiveModeState
from .emotional_aperture import EmotionalAperture
from .conversational_signals import SignalScorer, TurnSignals
from .rhythm import RhythmEngine
from .drift_pressure import DriftPressureSystem, DriftPressureInput, DriftResponse
from .framework.mpf import MPFProfile, get_llm_boot_prompt, load_mpf_registry
from .backends import configure_backends, get_brain_backend, apply_backend_overrides
from .helper_supervisor import HelperSupervisor
from .hybrid_memory import HybridMemorySystem
from .persona_manager import PersonaManager
from .state_manager import StateManager
from .config_loader import load_json_safely
from pathlib import Path
from .temporal_quantum_agent import TemporalQuantumAgent

logger = get_logger(__name__)

# Feature flag: emotion-driven sampling stays OFF until explicitly enabled.
ENABLE_EMOTION_SAMPLING = False

# --- Prompt Blocks ---
SAFETY_PROMPT_BLOCK_ON = """
--- SAFETY MODE BLOCK ---
SAFETY MODE: ON
Be mindful on money/law/health: flag uncertainty and suggest human verification, but keep your persona tone.
"""

SAFETY_PROMPT_BLOCK_OFF = """
--- SAFETY MODE BLOCK ---
SAFETY MODE: OFF
You may be direct and exploratory. Avoid minors, coercion, or illegal content. Keep truthfulness constraints.
"""

# Safe clamp for emotion-driven sampling adjustments.
def apply_emotion_sampling_bias(temp: float, top_p: float, emotion_meta: dict | None) -> tuple[float, float]:
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
        "supervisor_mode": "PASSIVE",
        "supervisor_gain": 0.20,
        "min_temp": 0.85,
        "max_temp": 1.05,
        "min_top_p": 0.90,
        "max_top_p": 1.00,
        "base_drift_pressure": 0.12,
        "max_drift_pressure": 0.22,
        "aperture_mode": "OPEN",
        "stability_soft_floor": 0.20,
        "stability_soft_ceiling": 0.90,
    },
    "chaos_coherence": {
        "name": "chaos_coherence",
        "supervisor_mode": "PASSIVE",
        "supervisor_gain": 0.00,
        "min_temp": 0.95,
        "max_temp": 1.20,
        "min_top_p": 0.95,
        "max_top_p": 1.00,
        "base_drift_pressure": 0.12,
        "max_drift_pressure": 0.24,
        "aperture_mode": "OPEN",
        "stability_soft_floor": 0.20,
        "stability_soft_ceiling": 0.85,
    },
}


# ---------------------------------------------------------------------------
# Engine configuration
# ---------------------------------------------------------------------------

@dataclass
class EngineConfig:
    """Lightweight configuration for the core engine."""
    master_file: str = "JLframe_Engine_Framework.json"
    behavior_states_file: str = "behavior_states.json"
    mpf_registry_file: str = "personas/Personas.mpf.json"
    safety_on: bool = True
    supervisor_enabled: bool = True
    supervisor_gating: bool = True
    supervisor_postprocess: bool = True
    default_persona_name: str = "SparkByte"
    history_length: int = 20
    enable_feedback: bool = True
    feedback_log_path: str = "logs/engine_feedback.log"
    debug_feedback_notes: bool = False
    tqa_enabled: bool = True
    tqa_phase: str = "POST_SUGGEST"
    tqa_strength: float = 0.2


@dataclass(frozen=True)
class IntentResult:
    intent_label: str
    confidence: float
    extracted_entities: Dict[str, Any]
    requires_tools: Any
    mode: str


@dataclass(frozen=True)
class MemorySnapshot:
    selected_items: List[str]
    retrieval_reasoning: str
    compression_level: str | None


PHASES = (
    "INGEST",
    "INTENT_RESOLVE",
    "PERSONA_SELECT",
    "MEMORY_RETRIEVE",
    "TOOL_GATE",
    "DECODE",
    "POST_ANALYZE",
    "POST_SUGGEST",
)

TQA_ALLOWED_PHASES = {"POST_ANALYZE", "POST_SUGGEST"}


class EngineFeedback(TypedDict, total=False):
    persona_id: Optional[str]
    persona_name: str
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
    - Manage current persona
    - Maintain behavior state, rhythm, gait, cognitive mode, aperture
    - Compute drift pressure & corrective actions
    - Build messages and dispatch to the configured brain backend
    """

    def __init__(self, config: EngineConfig | None = None) -> None:
        self.config = config or EngineConfig()

        # Master config & core rules
        self.master_config: Dict[str, Any] = {}
        self.core_rules: List[str] = []
        self._load_master_config()
        raw_listener = self.master_config.get("listener_agent", {}) if isinstance(self.master_config, dict) else {}
        self.listener_agent: Dict[str, Any] = raw_listener if (isinstance(raw_listener, dict) and raw_listener.get("enabled")) else {}

        # MPF / persona registry
        self.mpf_profiles: Dict[str, MPFProfile] = {}
        self._load_mpf_registry()

        # Subsystems
        self.persona_state: Dict[str, Any] = {"emotion": None, "emotion_meta": None}
        self.behavior_engine = BehaviorStateMachine(self.config.behavior_states_file)
        self.emotional_aperture = EmotionalAperture(persona_state=self.persona_state)
        self.cognitive_selector = CognitiveModeSelector(default_mode="balanced")
        self.rhythm_engine = RhythmEngine()
        self.signal_scorer = SignalScorer()
        self.drift_system = DriftPressureSystem()
        self.supervisor = HelperSupervisor()
        self.persona_manager = PersonaManager()
        self.state_manager = StateManager()
        self.tqa_layer = TemporalQuantumAgent()
        self.tqa_enabled = bool(self.config.tqa_enabled)
        self.tqa_phase = str(self.config.tqa_phase or "POST_SUGGEST")
        self.tqa_strength = max(0.0, min(1.0, float(self.config.tqa_strength)))
        self.supervisor_enabled = bool(self.config.supervisor_enabled)
        self.supervisor_gating = bool(self.config.supervisor_gating)
        self.supervisor_postprocess = bool(self.config.supervisor_postprocess)

        # Runtime state
        self.current_persona_name: str = self.config.default_persona_name
        self.current_persona_data: Dict[str, Any] = {}
        self.current_gait: str = "walk"
        self.current_rhythm_mode: str = "flop"
        self.current_cognitive_state: CognitiveModeState | None = None
        self.last_signals: TurnSignals | None = None
        self.last_drift_response: DriftResponse | None = None
        self.drift_pressure: float = 0.0
        self.supervisor_state: Dict[str, Any] = {}
        self.behavior_profile_name: str = "expressive"
        self.behavior_profile: Dict[str, Any] | None = None
        self.supervisor_gain: float = 0.35
        self.supervisor_mode: str = "BALANCED"
        self.aperture_mode: str = "LIMITED"
        self.temp: float = 0.7
        self.top_p: float = 0.9
        self.stability_score: float = 0.5
        self.user_trigger: Optional[str] = None
        self.gait: str = "TROT"
        self.rhythm: str = "TWITCH"
        self._drift_state: float = 0.0
        self.engine_core_test_mode: bool = False
        self.phase: str | None = None
        self.phase_log: List[str] = []
        self.last_intent_result: IntentResult | None = None
        self.last_memory_snapshot: MemorySnapshot | None = None
        self.modulation_fault: bool = False
        self.feedback_enabled: bool = bool(self.config.enable_feedback)
        self.feedback_log_path: Path = Path(self.config.feedback_log_path)
        self.debug_feedback_notes: bool = bool(self.config.debug_feedback_notes)
        self.current_persona_file: Optional[str] = None
        self.feedback_logger = logging.getLogger("EngineFeedback")
        if not self.feedback_logger.handlers:
            self.feedback_logger.addHandler(logging.NullHandler())
        self._ensure_feedback_log_directory()

        # Backend wiring
        self._configure_backends_from_master()

        # Hybrid memory system
        self.memory_system = HybridMemorySystem()

        # Load initial persona
        self.set_persona(self.current_persona_name)
        self.set_behavior_profile("expressive")

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
        except Exception as exc:
            logger.error("[EngineCore] Failed to load MPF registry '%s': %s",
                         self.config.mpf_registry_file, exc)
            self.mpf_profiles = {}

    def _configure_backends_from_master(self) -> None:
        """
        Configure brain/tool backends using the same logic as the GUI,
        but without importing Tk or other UI modules.
        """
        from . import backends  # local import to avoid cycles

        backends_cfg = self.master_config.get("backends", {})
        brain_backend_cfg = None
        tool_backend_cfg = None
        if isinstance(backends_cfg, dict):
            apply_backend_overrides(backends_cfg)
            brain_backend_cfg = backends_cfg.get("brain_backend") or backends_cfg.get("default")
            tool_backend_cfg = backends_cfg.get("tool_backend")

        configure_backends(brain_id=brain_backend_cfg, tool_id=tool_backend_cfg)
        logger.info("[EngineCore] Backends configured (brain=%r, tool=%r).",
                    brain_backend_cfg, tool_backend_cfg)

    # ------------------------------------------------------------------
    # Persona management
    # ------------------------------------------------------------------

    def set_persona(self, persona_name: str) -> None:
        """
        Set the active persona by display name (as used in Personas.mpf.json).
        Falls back to the default persona if not found.
        """
        import json, os

        profile = self.mpf_profiles.get(persona_name)
        if not profile:
            logger.warning("[EngineCore] Persona '%s' not found in MPF registry; "
                           "falling back to '%s'.", persona_name, self.config.default_persona_name)
            profile = self.mpf_profiles.get(self.config.default_persona_name)

        self.current_persona_name = persona_name
        persona_file = None
        drive_type = None

        if profile:
            persona_file = profile.persona_file
            drive_type = profile.drive_type
        self.current_persona_file = persona_file

        # Reset canonical persona state emotion slots for the new persona.
        if isinstance(self.persona_state, dict):
            self.persona_state["emotion"] = None
            self.persona_state["emotion_meta"] = None
        if hasattr(self.emotional_aperture, "set_persona_state"):
            self.emotional_aperture.set_persona_state(self.persona_state)

        # Load persona JSON (if available)
        persona_path = None
        if persona_file:
            persona_path = os.path.join("personas", persona_file)
        if persona_path and os.path.exists(persona_path):
            try:
                with open(persona_path, "r", encoding="utf-8") as f:
                    self.current_persona_data = json.load(f)
            except Exception as exc:
                logger.error("[EngineCore] Failed to load persona file '%s': %s",
                             persona_path, exc)
                self.current_persona_data = {}
        else:
            if persona_path:
                logger.warning("[EngineCore] Persona file '%s' not found.", persona_path)
            self.current_persona_data = {}

                # Push persona-specific emotion palette (if present) into the aperture.
        try:
            self.emotional_aperture.set_emotion_palette(self.current_persona_data.get("emotion_palette"))
        except Exception as exc:
            logger.warning("[EngineCore] Failed to set emotion palette for '%s': %s",
                           persona_name, exc)
        try:
            self.persona_manager.set_active_persona(self.current_persona_name, self.current_persona_data, self.mpf_profiles)
        except Exception as exc:
            logger.debug("[EngineCore] Persona manager unable to attach '%s': %s", self.current_persona_name, exc)

# Drive type + emotional aperture
        if drive_type:
            try:
                self.emotional_aperture.set_drive_type(drive_type)
            except Exception as exc:
                logger.warning("[EngineCore] Failed to set drive_type '%s': %s",
                               drive_type, exc)

        # Reset dynamic state for new persona
        self.current_gait = "walk"
        self.current_rhythm_mode = "flop"
        self.current_cognitive_state = None
        self.last_signals = None
        self.last_drift_response = None
        self.drift_pressure = 0.0
        # For SparkByte testing, reduce supervisor influence without disabling safety
        if persona_name.lower() == "sparkbyte":
            self.supervisor_gain = 0.01

        logger.info("[EngineCore] Persona set to '%s' (file=%r, drive_type=%r).",
                    persona_name, persona_file, drive_type)

    def get_llm_boot_prompt(self, target: str = "generic_llm") -> str:
        """
        Return the boot prompt for the current persona for a given LLM target.

        This simply wraps the MPF helper so other layers (bridges, tools) can
        fetch the correct persona script without re-parsing the JSON layout.
        """
        return get_llm_boot_prompt(self.current_persona_data, target)

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
        except Exception:
            # Fallback to baseline if reset is unavailable
            self.aperture_mode = "LIMITED"
        return self.get_engine_status()

    def get_mpf_state_snapshot(self) -> Dict[str, Any]:
        """
        Lightweight, JSON-serializable MPF snapshot for diagnostics.
        """
        try:
            aperture_state = self.emotional_aperture.get_state()
        except Exception:
            aperture_state = {}

        emotional_score = float(aperture_state.get("score", 0.0) or 0.0)
        safety_score = 1.0 - max(0.0, min(1.0, float(getattr(self, "drift_pressure", 0.0) or 0.0)))

        memory_focus = 0.0
        try:
            persona_id = self.current_persona_name or "default"
            ctx = self.memory_system.get_context(persona_id) if hasattr(self, "memory_system") else {}
            persona_mem = (ctx or {}).get("persona_memory", {}) if isinstance(ctx, dict) else {}
            recent_interactions = persona_mem.get("recent_interactions", []) if isinstance(persona_mem, dict) else []
            memory_focus = min(1.0, len(recent_interactions) / 20.0)
        except Exception:
            memory_focus = 0.0

        return {
            "gait": getattr(self, "current_gait", None),
            "rhythm": getattr(self, "current_rhythm_mode", None),
            "aperture": {
                "emotional": emotional_score,
                "safety": safety_score,
                "memory_focus": memory_focus,
            },
            "mode": getattr(self, "behavior_profile_name", None),
        }

    def get_engine_status(self) -> Dict[str, Any]:
        """
        Lightweight status block for UI/diagnostics overlays.
        """
        return {
            "gait": self.current_gait,
            "rhythm": self.current_rhythm_mode,
            "aperture_mode": self.aperture_mode,
            "stability_score": self.stability_score,
            "modulation_fault": self.modulation_fault,
            "phase": self.phase,
            "tqa": {
                "enabled": bool(self.tqa_enabled),
                "phase": self.tqa_phase,
                "strength": self.tqa_strength,
            },
        }

    def smoke_test_engine(self, user_message: str) -> Tuple[str, Dict[str, Any]]:
        """
        Generate a raw engine-core response without persona or supervisor layers.
        """
        core_prompt = (
            "ENGINE_CORE_DIAGNOSTIC_MODE\n"
            "Internal State:\n"
            f"- Gait: {self.gait}\n"
            f"- Rhythm: {self.rhythm}\n"
            f"- Aperture: {self.aperture_mode}\n\n"
            "User message:\n"
            f"{user_message}\n\n"
            "Respond as raw engine cognition (no persona)."
        )

        backend = get_brain_backend()
        options = {"temperature": self.temp, "top_p": self.top_p}
        try:
            result = backend.generate([{"role": "user", "content": core_prompt}], options=options)
            if isinstance(result, tuple) and len(result) == 2:
                reply_text, meta = result
            else:
                reply_text, meta = result, {}
        except Exception as exc:
            reply_text = f"[ENGINE_CORE_DIAGNOSTIC_MODE] Backend error: {exc}"
            meta = {"error": str(exc)}
        return reply_text, meta

    def generate_response(
        self,
        user_message: str,
        persona_name: Optional[str] = None,
        context: Optional[Dict[str, Any]] = None,
    ) -> Tuple[str, Dict[str, Any], EngineFeedback]:
        """
        Unified entrypoint for chat responses that can bypass persona/supervisor layers
        when Engine Core Diagnostic Mode is active.
        """
        if self.engine_core_test_mode:
            reply_text, backend_meta = self.smoke_test_engine(user_message)
            self._set_phase("DECODE")
            intent_result = self._resolve_intent(user_message, context or {})
            telemetry = {
                "persona": "ENGINE_CORE_DIAGNOSTIC_MODE",
                "persona_state": dict(self.persona_state) if isinstance(self.persona_state, dict) else {"emotion": None, "emotion_meta": None},
                "signals": {},
                "behavior_state": {"id": None, "name": "diagnostic"},
                "aperture_state": self.emotional_aperture.get_state(),
                "cognitive_mode": "diagnostic",
                "drift": {"pressure": 0.0, "action": "diagnostic", "raw": {}},
                "rhythm": {"mode": self.current_rhythm_mode, "gait": self.current_gait},
                "backend_meta": backend_meta,
                "behavior_profile": self.behavior_profile_name,
                "aperture_dynamic": {"temp": self.temp, "top_p": self.top_p, "mode": self.aperture_mode},
                "drift_state": self._drift_state,
                "stability_score": self.stability_score,
                "engine_status": self.get_engine_status(),
                "phase": self.phase,
                "phase_log": list(self.phase_log),
                "intent": asdict(intent_result),
                "memory_snapshot": {},
                "tqa": {
                    "enabled": bool(self.tqa_enabled),
                    "phase": self.tqa_phase,
                    "strength": self.tqa_strength,
                    "ran": False,
                    "advisory": [],
                },
            }
            feedback: EngineFeedback = {
                "persona_id": "ENGINE_CORE_DIAGNOSTIC_MODE",
                "persona_name": "ENGINE_CORE_DIAGNOSTIC_MODE",
                "active_gait_state": self.current_gait,
                "active_rhythm_pattern": self.current_rhythm_mode,
                "aperture_level": self.aperture_mode,
                "used_memory_count": 0,
                "used_memory_ids": [],
                "raw_memory_preview": [],
                "notes": "",
            }
            telemetry["feedback"] = feedback
            self._append_feedback_log(user_message, reply_text, feedback)
            return reply_text, telemetry, feedback

        return self.process_turn(user_text=user_message, persona_name=persona_name, context=context)

    # ------------------------------------------------------------------
    # Turn processing
    # ------------------------------------------------------------------

    def process_turn(self, user_text: str,
                     persona_name: Optional[str] = None,
                     context: Optional[Dict[str, Any]] = None) -> Tuple[str, Dict[str, Any], EngineFeedback]:
        """
        Process a single conversational turn.

        Returns:
            reply_text: str - model output from the brain backend
            telemetry: dict - rich structured data for HUDs / logs / debugging
            feedback: EngineFeedback - dev-only self-report of what the engine used
        """
        self._set_phase("INGEST")
        context = context or {}
        requested_persona = persona_name or self.current_persona_name

        self._set_phase("INTENT_RESOLVE")
        intent_result = self._resolve_intent(user_text, context)
        self.last_intent_result = intent_result

        self._set_phase("PERSONA_SELECT")
        persona_name = requested_persona
        if persona_name and persona_name != self.current_persona_name:
            self.set_persona(persona_name)

        # Determine persona_id for memory
        persona_id = self.current_persona_name
        self._set_phase("MEMORY_RETRIEVE")
        memory_ctx = self.memory_system.get_context(persona_id)
        self.last_memory_snapshot = self._build_memory_snapshot(memory_ctx)

        # 1) Score conversational signals from the raw text
        self._set_phase("TOOL_GATE")
        signals = self.signal_scorer.score(user_text or "")
        self.last_signals = signals

        state_snapshot = self.state_manager.export_snapshot() if self.state_manager else {}
        advisory_payload = self.state_manager.advisory_payload(self.stability_score, self.drift_pressure) if self.state_manager else {}
        sup_arbitration = {}
        if self.supervisor and self.supervisor_enabled and self.supervisor_gating:
            sup_arbitration = self.supervisor.arbitrate({
                "stability": self.stability_score,
                "drift_pressure": self.drift_pressure,
                "rhythm_momentum": advisory_payload.get("rhythm_momentum", 0.0),
                "emotional_drift": advisory_payload.get("emotional_drift", 0.0),
            })

        # 2) Trigger inference and behavior update
        self.user_trigger = context.get("user_trigger") or self._derive_trigger_from_signals(signals)
        if self.behavior_engine:
            try:
                self.behavior_engine.transition_by_trigger(
                    self.user_trigger,
                    self.current_gait,
                    gating_advice=sup_arbitration.get("gating") if isinstance(sup_arbitration, dict) else None,
                )
            except Exception as exc:
                logger.warning("[EngineCore] Failed behavior transition: %s", exc)

        # 3) Behavior state from the grid (post-transition)
        behavior_state = self.behavior_engine.get_current_state() if self.behavior_engine else None
        behavior_blend = self.behavior_engine.get_current_blend() if self.behavior_engine else None
        # allow supervisor to nudge behavior intensity without hard blocks
        if sup_arbitration and sup_arbitration.get("behavior_bias"):
            bias = sup_arbitration["behavior_bias"]
            delta_row = 1 if bias > 0.25 else -1 if bias < -0.25 else 0
            if delta_row != 0 and self.behavior_engine:
                try:
                    self.behavior_engine.set_state_by_coords(self.behavior_engine.current_row + delta_row,
                                                            self.behavior_engine.current_col)
                    behavior_state = self.behavior_engine.get_current_state()
                    behavior_blend = self.behavior_engine.get_current_blend()
                except Exception:
                    pass

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
        if isinstance(self.persona_state, dict):
            self.persona_state["emotion"] = aperture_state.get("emotion")
            self.persona_state["emotion_meta"] = aperture_state.get("emotion_meta")
        self._update_dynamic_aperture()

        # 5) Cognitive mode selection
        mode_state = self.cognitive_selector.select_modes(
            gear="spur",
            focus_level=self.emotional_aperture.get_focus_level(),
            overload_level=self.emotional_aperture.get_overload_level(),
        )
        self.current_cognitive_state = mode_state

        # pick dominant mode label for HUD
        dominant_mode = self.cognitive_selector.get_dominant_mode()

        # 6) Drift pressure & corrective actions (stubbed alignment scores for now)
        drift_input = DriftPressureInput()
        # TODO: wire real alignment scores (persona, behavior, safety, memory, coherence)
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
            modulation_hint["gating_bias"] = (sup_arbitration.get("gating") or {}).get("weight", 0.0)

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
        except Exception:
            aperture_score = 0.0
        if rhythm_info.get("index", 0.0) > 0.72 or aperture_score > 0.65:
            self.current_gait = "trot" if self.current_gait != "sprint" else self.current_gait
        elif rhythm_info.get("index", 0.0) < 0.3 and aperture_score < 0.35:
            self.current_gait = "idle" if self.current_gait not in ("trot", "sprint") else self.current_gait

        # Supervisor arbitration with updated internal state
        if self.supervisor and self.supervisor_enabled:
            sup_signals = {
                "persona_rules_ok": True,
                "safety_rules_ok": self.config.safety_on,
                "drift_estimate": self.drift_pressure,
                "coherence_score": max(0.0, 1.0 - self.drift_pressure),
                "task_alignment_score": max(0.1, 1.0 - signals.confusion),
                "answer_quality_score": 1.0,
                "speculative_risk_score": 0.0,
            }
            self.supervisor_state = self.supervisor.evaluate(sup_signals, safety_mode="ON" if self.config.safety_on else "OFF")
            corrections = self.supervisor_state.get("corrections", {})
            self.supervisor_mode = self.supervisor_state.get("mode", self.supervisor_mode)
            if corrections.get("safety_override"):
                self.supervisor_gain = min(1.0, max(self.supervisor_gain, 0.85))
            else:
                self.supervisor_gain = max(0.2, min(1.0, self.supervisor_gain))
            aperture_correction = corrections.get("aperture_bias", 0.0)
            drift_bias = advisory_payload.get("emotional_drift", 0.0) + aperture_correction
            try:
                self.emotional_aperture.inject_drift_bias(drift_bias)
                adjusted_score = max(0.0, min(1.0, aperture_state.get("score", 0.0) + aperture_correction))
                aperture_state["score"] = adjusted_score
                aperture_state["mode"] = self.emotional_aperture._get_mode_from_score(adjusted_score)
            except Exception:
                pass
            # reapply gating advice if supervisor escalated safety
            gating_override = (self.supervisor_state.get("corrections") or {}).get("safety_override")
            if gating_override and self.supervisor_gating and self.behavior_engine:
                self.behavior_engine.transition_by_trigger(self.user_trigger, self.current_gait,
                                                          gating_advice={"level": "safety_block", "weight": 1.0})
                behavior_state = self.behavior_engine.get_current_state()
                behavior_blend = self.behavior_engine.get_current_blend()

        # Persona blending/dynamic traits
        persona_projection = self.current_persona_data
        if self.persona_manager:
            try:
                if sup_arbitration:
                    self.persona_manager.apply_supervisor_bias(sup_arbitration.get("persona_blend_bias", 0.0))
                self.persona_manager.update_dynamic_weight(signals, rhythm_info, aperture_state)
                persona_projection = self.persona_manager.get_projection()
            except Exception as exc:
                logger.debug("[EngineCore] Persona manager update failed: %s", exc)

        task_intent = str(intent_result.intent_label or "general")
        action_type = self._infer_action_type(task_intent, context)
        overload_level = 0.0
        try:
            overload_level = float(self.emotional_aperture.get_overload_level())
        except Exception:
            overload_level = 0.0
        risk_level, cognitive_load = self._derive_temporal_risk(signals, self.drift_pressure, overload_level)

        # 8) Build messages & call backend
        self._set_phase("DECODE")
        messages = self._build_messages(
            user_text=user_text,
            behavior_state=behavior_state,
            aperture_state=aperture_state,
            cognitive_mode=dominant_mode,
            rhythm_mode=self.current_rhythm_mode,
            gait=self.current_gait,
            memory_ctx=memory_ctx,
            persona_projection=persona_projection,
            behavior_blend=behavior_blend,
        )

        # Construct per-turn feedback snapshot before LLM call
        persona_memory = memory_ctx.get("persona_memory", {}) if isinstance(memory_ctx, dict) else {}
        recent_interactions = persona_memory.get("recent_interactions") or []
        memory_preview = []
        for interaction in recent_interactions[-3:]:
            user_snip = (interaction.get("user_message") or "")[:120]
            out_snip = (interaction.get("output") or "")[:120]
            memory_preview.append(f"U:{user_snip} | A:{out_snip}")

        feedback: EngineFeedback = {
            "persona_id": self.current_persona_file or persona_id,
            "persona_name": self.current_persona_data.get("name") or self.current_persona_name,
            "active_gait_state": self.current_gait,
            "active_rhythm_pattern": self.current_rhythm_mode,
            "aperture_level": aperture_state.get("mode"),
            "used_memory_count": len(recent_interactions),
            "used_memory_ids": [f"recent_interaction_{i}" for i in range(max(0, len(recent_interactions) - 3), len(recent_interactions))],
            "raw_memory_preview": memory_preview,
            "notes": "",
        }

        backend = get_brain_backend()
        temp = self.temp
        top_p = self.top_p
        if ENABLE_EMOTION_SAMPLING and isinstance(self.persona_state, dict):
            temp, top_p = apply_emotion_sampling_bias(temp, top_p, self.persona_state.get("emotion_meta"))

        options = {"temperature": temp, "top_p": top_p}
        persona_output, backend_meta = backend.generate(messages, options=options)
        supervised_output = persona_output
        if self.supervisor and self.supervisor_enabled and self.supervisor_postprocess:
            supervised_output = self.supervisor.postprocess(
                persona_output,
                context=context,
                gain=self.supervisor_gain,
                mode=self.supervisor_mode,
            )

        self._set_phase("POST_ANALYZE")
        self._update_state_from_interaction(user_text, supervised_output)
        rhythm_info["mode"] = self.current_rhythm_mode
        rhythm_info["gait"] = self.current_gait

        try:
            self.emotional_aperture.apply_output_feedback(supervised_output, rhythm_info, self.current_gait)
        except Exception:
            pass
        if self.state_manager:
            try:
                self.state_manager.update_from_output(supervised_output, rhythm_info, self.current_gait)
            except Exception:
                pass

        # Update hybrid memory after turn
        engine_state = {
            "gait": self.current_gait,
            "rhythm": self.current_rhythm_mode,
            "aperture_mode": self.aperture_mode,
            "dynamic": self.state_manager.export_snapshot() if self.state_manager else {},
            "flags": {
                # optional, only if you track them:
                "stressed": getattr(self, "stressed", False),
                "serial_error": getattr(self, "serial_error", False),
            },
        }
        self.memory_system.update_after_turn(
            persona_id=persona_id,
            user_message=user_text,
            output=supervised_output,
            engine_state=engine_state,
        )

        tqa_snapshot, tqa_advisory, tqa_ran = self._run_tqa_advisory(
            phase="POST_ANALYZE",
            task_intent=task_intent,
            action_type=action_type,
            risk_level=risk_level,
            cognitive_load=cognitive_load,
            overload_level=overload_level,
            context=context,
            backend_meta=backend_meta,
        )
        self._set_phase("POST_SUGGEST")
        if not tqa_ran:
            tqa_snapshot, tqa_advisory, _ = self._run_tqa_advisory(
                phase="POST_SUGGEST",
                task_intent=task_intent,
                action_type=action_type,
                risk_level=risk_level,
                cognitive_load=cognitive_load,
                overload_level=overload_level,
                context=context,
                backend_meta=backend_meta,
            )
        if not tqa_ran and not tqa_snapshot:
            logger.info(
                "[TQA] Skipped advisory (enabled=%s, configured_phase=%s)",
                self.tqa_enabled,
                self.tqa_phase,
            )

        telemetry = {
            "persona": self.current_persona_name,
            "persona_state": dict(self.persona_state) if isinstance(self.persona_state, dict) else {"emotion": None, "emotion_meta": None},
            "listener_agent": self.listener_agent if isinstance(self.listener_agent, dict) else {},
            "signals": asdict(signals),
            "behavior_state": {
                "id": getattr(behavior_state, "id", None),
                "name": getattr(behavior_state, "name", None),
            },
            "behavior_blend": behavior_blend,
            "aperture_state": aperture_state,
            "cognitive_mode": dominant_mode,
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
            "aperture_dynamic": {"temp": self.temp, "top_p": self.top_p, "mode": self.aperture_mode},
            "drift_state": self._drift_state,
            "stability_score": self.stability_score,
            "engine_status": self.get_engine_status(),
            "dynamic_state": self.state_manager.export_snapshot() if self.state_manager else {},
            "supervisor": self.supervisor_state,
        }
        telemetry["phase"] = self.phase
        telemetry["phase_log"] = list(self.phase_log)
        telemetry["intent"] = asdict(intent_result)
        telemetry["memory_snapshot"] = asdict(self.last_memory_snapshot) if self.last_memory_snapshot else {}
        telemetry["tqa"] = {
            "enabled": bool(self.tqa_enabled),
            "phase": self.tqa_phase,
            "strength": self.tqa_strength,
            "ran": bool(tqa_ran),
            "advisory": tqa_advisory or [],
        }
        if tqa_snapshot:
            telemetry["tqa_frame"] = {
                "t_minus_1": self._serialize_temporal_state(tqa_snapshot.past_state),
                "t_zero": self._serialize_temporal_state(tqa_snapshot.present_state),
                "t_plus_1": self._serialize_temporal_state(tqa_snapshot.future_projection),
            }
        # Optional internal reflection for dev notes
        feedback["notes"] = self._run_feedback_reflection(
            reply_text=supervised_output,
            feedback=feedback,
            memory_preview=memory_preview,
        )

        telemetry["feedback"] = feedback
        self._append_feedback_log(user_text, supervised_output, feedback)
        return supervised_output, telemetry, feedback

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _set_phase(self, phase: str) -> None:
        if phase not in PHASES:
            return
        if phase == "INGEST":
            self.phase_log = []
        self.phase = phase
        self.phase_log.append(phase)
        logger.info("[EngineCore] Phase -> %s", phase)

    def _resolve_intent(self, user_text: str, context: Dict[str, Any]) -> IntentResult:
        intent_label = (
            context.get("intent")
            or context.get("task_intent")
            or "general"
        )
        confidence = context.get("intent_confidence")
        try:
            confidence_val = float(confidence) if confidence is not None else 0.5
        except Exception:
            confidence_val = 0.5
        extracted = context.get("extracted_entities") or context.get("entities") or {}
        requires_tools = context.get("requires_tools")
        if requires_tools is None:
            requires_tools = context.get("tool_gate") or False
        mode = context.get("mode") or "chat"
        return IntentResult(
            intent_label=str(intent_label),
            confidence=max(0.0, min(1.0, confidence_val)),
            extracted_entities=extracted if isinstance(extracted, dict) else {},
            requires_tools=requires_tools,
            mode=str(mode),
        )

    def _build_memory_snapshot(self, memory_ctx: Dict[str, Any]) -> MemorySnapshot:
        persona_mem = memory_ctx.get("persona_memory", {}) if isinstance(memory_ctx, dict) else {}
        recent = persona_mem.get("recent_interactions", []) if isinstance(persona_mem, dict) else []
        selected_items: List[str] = []
        for item in recent[-3:]:
            if not isinstance(item, dict):
                continue
            user_snip = (item.get("user_message") or "")[:80].strip()
            out_snip = (item.get("output") or "")[:80].strip()
            selected_items.append(f"U:{user_snip} | A:{out_snip}".strip())
        reasoning = "recent_interactions:last_3"
        compression = persona_mem.get("compression_level") if isinstance(persona_mem, dict) else None
        return MemorySnapshot(
            selected_items=selected_items,
            retrieval_reasoning=reasoning,
            compression_level=compression,
        )

    def _tqa_can_run(self, phase: str) -> bool:
        return (
            bool(self.tqa_enabled)
            and bool(self.tqa_layer)
            and phase == self.tqa_phase
            and phase in TQA_ALLOWED_PHASES
        )

    def _tqa_advisory_from_snapshot(self, snapshot: Any) -> List[str]:
        if not snapshot:
            return []
        metrics = getattr(snapshot.future_projection, "metrics", {}) or {}
        suggestions: List[str] = []
        burnout = metrics.get("burnout_risk", 0.0)
        if burnout > 0.6:
            suggestions.append("Consider lowering tempo to reduce burnout risk.")
        failure = metrics.get("failure_cascade_probability", 0.0)
        if failure > 0.6:
            suggestions.append("Prioritize safe, incremental steps to avoid cascade.")
        overwhelm = metrics.get("operator_overwhelm_probability", 0.0)
        if overwhelm > 0.6:
            suggestions.append("Keep responses concise; confirm next step.")
        return suggestions

    def _run_tqa_advisory(
        self,
        phase: str,
        task_intent: str,
        action_type: str,
        risk_level: str,
        cognitive_load: str,
        overload_level: float,
        context: Dict[str, Any],
        backend_meta: Dict[str, Any] | None,
    ) -> tuple[Any | None, List[str], bool]:
        if not self._tqa_can_run(phase):
            return None, [], False
        memory_snapshot = asdict(self.last_memory_snapshot) if self.last_memory_snapshot else None
        self.tqa_layer.update_present_state(
            persona=self.current_persona_name,
            task_intent=task_intent,
            risk_level=risk_level,
            cognitive_load=cognitive_load,
            action_type=action_type,
            error_signature=context.get("error_signature"),
            memory_snapshot=memory_snapshot,
        )
        self._update_temporal_projection(risk_level, cognitive_load, overload_level)
        error_signature = context.get("error_signature")
        if not error_signature and isinstance(backend_meta, dict):
            error_signature = backend_meta.get("error")
        self.tqa_layer.collapse(
            reason="turn_complete",
            outcome=str(context.get("outcome") or "success"),
            error_signature=error_signature,
        )
        snapshot = self.tqa_layer.snapshot()
        advisory = self._tqa_advisory_from_snapshot(snapshot)
        logger.info(
            "[TQA] Advisory phase=%s strength=%.2f suggestions=%d",
            phase,
            self.tqa_strength,
            len(advisory),
        )
        return snapshot, advisory, True

    def _ensure_feedback_log_directory(self) -> None:
        """Ensure the feedback log directory exists."""
        try:
            if self.feedback_log_path and self.feedback_log_path.parent:
                self.feedback_log_path.parent.mkdir(parents=True, exist_ok=True)
        except Exception:
            # Fail open; logging will be best-effort.
            pass

    def _append_feedback_log(self, user_text: str, reply_text: str, feedback: EngineFeedback) -> None:
        """Write a single JSON line with feedback (dev-only)."""
        if not self.feedback_enabled or not self.feedback_log_path:
            return
        try:
            payload = {
                "timestamp": datetime.utcnow().isoformat() + "Z",
                "user_input": user_text,
                "reply": reply_text,
                "feedback": feedback,
                "persona_state": dict(self.persona_state) if isinstance(self.persona_state, dict) else None,
            }
            line = json.dumps(payload, ensure_ascii=False)
            with open(self.feedback_log_path, "a", encoding="utf-8") as f:
                f.write(line + "\n")
        except Exception as exc:
            self.feedback_logger.debug("Failed to write feedback log: %s", exc)

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
            persona_name = feedback.get("persona_name") or feedback.get("persona_id") or "Unknown"
            aperture = feedback.get("aperture_level") or "Unknown"
            gait = feedback.get("active_gait_state") or "Unknown"
            rhythm = feedback.get("active_rhythm_pattern") or "Unknown"
            prompt = (
                "SYSTEM: You are an analyzer for the JL Engine. Given the current persona, memory, and reply, "
                "summarize what the engine appears to believe about itself in one or two sentences.\n"
                f"persona_name: {persona_name}\n"
                f"gait_state: {gait}\n"
                f"rhythm: {rhythm}\n"
                f"aperture: {aperture}\n"
                f"memory_snippets: {memory_preview[:3]}\n"
                f"reply: {reply_text[:800]}\n"
                "OUTPUT: A short dev-only note, not for the user."
            )
            opts = {"temperature": 0.2, "top_p": 0.7}
            analysis, _meta = backend.generate([{"role": "system", "content": prompt}], options=opts)
            if isinstance(analysis, str):
                return analysis.strip()
            if isinstance(analysis, tuple) and len(analysis) >= 1:
                return str(analysis[0]).strip()
            return str(analysis).strip()
        except Exception as exc:
            return f"[reflection_failed: {exc}]"

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

    def _derive_temporal_risk(self, signals: TurnSignals, drift_pressure: float, overload_level: float) -> tuple[str, str]:
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

    def _update_temporal_projection(self, risk_level: str, cognitive_load: str, overload_level: float) -> None:
        if not self.tqa_layer or not self.tqa_enabled:
            return

        def clamp(val: float) -> float:
            return max(0.0, min(1.0, val))

        burnout_risk = clamp(0.15 + overload_level * 0.7 + (0.2 if risk_level == "high" else 0.05 if risk_level == "medium" else 0.0))
        failure_cascade = clamp(0.1 + self.drift_pressure * 0.9 + (0.05 if risk_level == "medium" else 0.15 if risk_level == "high" else 0.0))
        perf_regression = clamp(0.08 + self.drift_pressure * 0.4 + (0.12 if risk_level != "low" else 0.0))
        operator_overwhelm = clamp(0.1 + overload_level * 0.8 + (0.1 if cognitive_load == "high" else 0.0))

        self.tqa_layer.update_future_projection(
            burnout_risk=burnout_risk,
            failure_cascade_probability=failure_cascade,
            performance_regression_probability=perf_regression,
            operator_overwhelm_probability=operator_overwhelm,
            persona=self.current_persona_name,
        )

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

    def _serialize_temporal_state(self, state) -> Dict[str, Any]:
        if not state:
            return {}
        return {
            "timestamp": state.timestamp.isoformat() if hasattr(state, "timestamp") else None,
            "persona": getattr(state, "persona", None),
            "outcome": getattr(state, "outcome", None),
            "metrics": getattr(state, "metrics", {}),
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
                chaos_factor = max(0.0, min(1.0, chaos_factor + self.state_manager.state.emotional_drift * 0.2))
        except Exception:
            pass

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
        Applies globally to all personas.
        """
        profile = self.behavior_profile or ENGINE_BEHAVIOR_PROFILES.get(self.behavior_profile_name)
        base_drift = profile.get("base_drift_pressure", 0.2) if profile else 0.2
        max_drift_pressure = profile.get("max_drift_pressure", 0.4) if profile else 0.4

        reply_text = output or ""
        length_factor = min(1.0, len(reply_text) / 800.0)
        exclam_factor = min(1.0, reply_text.count("!") / 8.0)
        caps_factor = 1.0 if any(tok.isupper() and len(tok) > 3 for tok in reply_text.split()) else 0.0

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
        rhythm_mode: str,
        gait: str,
        memory_ctx: Dict[str, Any],
        persona_projection: Dict[str, Any] | None = None,
        behavior_blend: Dict[str, Any] | None = None,
    ) -> list[dict]:
        """
        Build a minimal-but-layered chat message list for the brain backend.

        This is intentionally simpler than the big GUI prompt builder, but follows
        the same spirit:
        - core rules
        - persona identity & behavior
        - current engine telemetry (behavior, gait, rhythm, cognitive mode, aperture)
        """
        system_chunks: List[str] = []

        # 1) Core rules from master config
        if self.core_rules:
            system_chunks.append("CORE RULES:")
            for rule in self.core_rules:
                system_chunks.append(f"- {rule}")

        # Add safety or NSFW block. NSFW takes precedence.
        if self.config.safety_on:
            system_chunks.append(SAFETY_PROMPT_BLOCK_ON)
        else:
            system_chunks.append(SAFETY_PROMPT_BLOCK_OFF)

        # 2) Persona identity & behavior (if loaded)
        persona_source = persona_projection or self.current_persona_data
        name = persona_source.get("name") or self.current_persona_name
        base_prompt = persona_source.get("base_prompt") or ""
        core_identity = persona_source.get("core_identity", {})
        behavior_traits = persona_source.get("operational_behavioral_traits", {})

        system_chunks.append(f"\nACTIVE PERSONA: {name}")
        if base_prompt:
            system_chunks.append(base_prompt)

        if core_identity:
            title = core_identity.get("title")
            desc = core_identity.get("description")
            if title or desc:
                system_chunks.append("\nPERSONA IDENTITY:")
                if title:
                    system_chunks.append(f"- Title: {title}")
                if desc:
                    system_chunks.append(f"- Description: {desc}")

        if behavior_traits:
            positives = behavior_traits.get("positive") or []
            negatives = behavior_traits.get("negative") or []
            boundaries = behavior_traits.get("boundaries") or []
            if positives:
                system_chunks.append("\nPOSITIVE TRAITS:")
                for t in positives:
                    system_chunks.append(f"- {t}")
            if negatives:
                system_chunks.append("\nNEGATIVE TENDENCIES (MUST BE CONTROLLED):")
                for t in negatives:
                    system_chunks.append(f"- {t}")
            if boundaries:
                system_chunks.append("\nBOUNDARIES (MUST NOT BE VIOLATED):")
                for b in boundaries:
                    system_chunks.append(f"- {b}")
            dyn_weight = persona_source.get("dynamic_trait_weight")
            if dyn_weight is not None:
                system_chunks.append(f"- Dynamic trait weight: {dyn_weight}")

        # 3) Current engine state
        system_chunks.append("\nENGINE STATE SNAPSHOT:")
        system_chunks.append(f"- Behavior state: {getattr(behavior_state, 'name', 'Unknown')}")
        system_chunks.append(f"- Gait: {gait}")
        system_chunks.append(f"- Rhythm mode: {rhythm_mode}")
        system_chunks.append(f"- Cognitive mode: {cognitive_mode}")
        system_chunks.append(f"- Emotional aperture mode: {aperture_state.get('mode')}")
        system_chunks.append(f"- Emotional aperture score: {aperture_state.get('score')}")
        system_chunks.append(f"- Behavior profile: {self.behavior_profile_name}")
        if behavior_blend and behavior_blend.get("secondary"):
            w_primary, w_secondary = behavior_blend.get("weights", (1.0, 0.0))
            system_chunks.append(f"- Behavior blend: {behavior_blend['primary']['name']} ({w_primary}) + {behavior_blend['secondary']['name']} ({w_secondary})")

        system_chunks.append(f"- Dynamic aperture: temp={round(self.temp, 2)}, top_p={round(self.top_p, 2)}")

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
            persona = memory_ctx.get("persona_memory", {})

            system_chunks.append("\nHYBRID MEMORY CONTEXT:")
            system_chunks.append(f"- Last active persona: {shared.get('last_active_persona', 'None')}")
            if shared.get("recent_events"):
                system_chunks.append("- Recent shared events:")
                for event in shared["recent_events"][-5:]:  # last 5 events
                    system_chunks.append(f"  - {event['persona']}: {event['event_type']} ({event.get('payload', {})})")
            if shared.get("engine_flags"):
                system_chunks.append(f"- Engine flags: {shared['engine_flags']}")
            if persona.get("recent_interactions"):
                system_chunks.append("- Recent persona interactions:")
                for interaction in persona["recent_interactions"][-3:]:  # last 3
                    system_chunks.append(f"  - User: {interaction['user_message'][:100]}...")
                    system_chunks.append(f"    Output: {interaction['output'][:100]}...")
            system_chunks.append(f"- Persona mood: {persona.get('mood', 'neutral')}")

        system_text = "\n".join(system_chunks)

        # Lightweight rolling history to preserve continuity (user/assistant snippets)
        history_messages: List[Dict[str, str]] = []
        if memory_ctx:
            persona = memory_ctx.get("persona_memory", {})
            recent = persona.get("recent_interactions") or []
            # include up to the last 6 user/assistant exchanges to preserve continuity
            for interaction in recent[-6:]:
                u = (interaction.get("user_message") or "")[:400]
                a = (interaction.get("output") or "")[:400]
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
