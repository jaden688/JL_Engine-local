from __future__ import annotations

import json
from typing import Any, Dict, List, Optional
from pathlib import Path
import sys

# Repo-local import shim: allow running from repo root without installation.
try:  # pragma: no cover - defensive path shim
    from jl_engine_core.engine_core import EngineConfig, JLEngineCore
except ModuleNotFoundError:
    _root = Path(__file__).resolve().parents[3]
    _src = _root / "src"
    for _p in (_root, _src):
        if _p.exists() and str(_p) not in sys.path:
            sys.path.insert(0, str(_p))
    from jl_engine_core.engine_core import EngineConfig, JLEngineCore

from jl_platform.core.models import CoreInput, CoreOutput, HostContext
from jl_platform.core.tools.registry import ToolRegistry
from jl_platform.core.util.logging import get_logger, new_trace_id
from jl_platform.core.util.validation import ensure_json_dict
from jl_platform.core.safety import ALLOW_NETWORK

logger = get_logger(__name__)


class CoreEngine:
    """
    Host-agnostic wrapper around the JL Engine Core orchestrator.

    This adapter keeps JL internals in one place while exposing a stable API for
    host adapters and the SDK.
    """

    def __init__(self, engine_config: Optional[EngineConfig] = None):
        self.engine_config = engine_config or EngineConfig()
        self._engines: Dict[str, JLEngineCore] = {}
        self._agent_states: Dict[str, Dict[str, Any]] = {}

    # ------------------------------------------------------------------ #
    # Agent lifecycle
    # ------------------------------------------------------------------ #
    def register_agent(
        self,
        agent_id: str,
        agent_ref_or_blob: Any,
        initial_state: Optional[Dict[str, Any]] = None,
    ):
        engine = self._create_engine()
        if isinstance(agent_ref_or_blob, str):
            try:
                engine.set_agent(agent_ref_or_blob)
            except Exception as exc:
                logger.warning("Unable to set agent %s: %s", agent_ref_or_blob, exc)
        elif isinstance(agent_ref_or_blob, dict):
            # Minimal adapter for inline agent definitions
            engine.current_agent_name = agent_ref_or_blob.get("name", agent_id)
            engine.current_agent_data = agent_ref_or_blob
        self._engines[agent_id] = engine
        if initial_state:
            self.set_state(agent_id, initial_state)

    def _create_engine(self) -> JLEngineCore:
        engine = JLEngineCore(config=self.engine_config)
        return engine

    # ------------------------------------------------------------------ #
    # Processing
    # ------------------------------------------------------------------ #
    def process(self, input: CoreInput, host: HostContext, tools: ToolRegistry) -> CoreOutput:
        engine = self._engines.get(input.agent_id) or self._create_engine()
        self._engines[input.agent_id] = engine
        message = self._compose_message(input)
        context = (input.context or {}) | {
            "host_type": host.host_type,
            "privacy_mode": host.privacy_mode,
        }

        reply_text, telemetry, _feedback = engine.generate_response(
            user_message=message, context=context
        )
        payload = {
            "text": reply_text,
            "telemetry": telemetry,
            "tools_used": [spec.name for spec in tools.list_specs()],
            "host": host.host_type,
            "agent_id": input.agent_id,
        }
        trace = (
            telemetry.get("engine_status", {}).get("trace_id")
            if isinstance(telemetry, dict)
            else None
        )
        trace_id = trace or new_trace_id()
        memory_notes = []
        if isinstance(telemetry, dict):
            raw_notes = telemetry.get("feedback", {}).get("raw_memory_preview", [])
            memory_notes = [{"note": n} for n in raw_notes] if isinstance(raw_notes, list) else []
        return CoreOutput(
            agent_id=input.agent_id,
            type="reply",
            payload=ensure_json_dict(payload),
            memory_writes=memory_notes,
            state_delta=(
                {"engine_status": telemetry.get("engine_status")}
                if isinstance(telemetry, dict)
                else {}
            ),
            trace_id=trace_id,
            warnings=[] if ALLOW_NETWORK else ["network_disabled"],
        )

    def tick(self, dt: float, host: HostContext, tools: ToolRegistry) -> List[CoreOutput]:
        outputs: List[CoreOutput] = []
        for agent_id, engine in self._engines.items():
            # For now, a tick emits a heartbeat state snapshot
            status = engine.get_engine_status() if hasattr(engine, "get_engine_status") else {}
            outputs.append(
                CoreOutput(
                    agent_id=agent_id,
                    type="tick",
                    payload={"dt": dt, "host": host.host_type, "status": status},
                    state_delta={"tick": dt},
                    trace_id=new_trace_id(),
                    warnings=[] if ALLOW_NETWORK else ["network_disabled"],
                )
            )
        return outputs

    # ------------------------------------------------------------------ #
    # State management
    # ------------------------------------------------------------------ #
    def get_state(self, agent_id: str) -> Dict[str, Any]:
        engine_state = self._agent_states.get(agent_id, {})
        return dict(engine_state)

    def set_state(self, agent_id: str, state: Dict[str, Any]) -> None:
        self._agent_states[agent_id] = dict(state)

    # ------------------------------------------------------------------ #
    # Helpers
    # ------------------------------------------------------------------ #
    def _compose_message(self, input: CoreInput) -> str:
        parts: List[str] = []
        if input.text:
            parts.append(str(input.text))
        if input.events:
            parts.append("Events:\n" + json.dumps(input.events, ensure_ascii=False))
        if input.context:
            ctx_preview = {k: v for k, v in input.context.items() if k != "host_type"}
            if ctx_preview:
                parts.append("Context:\n" + json.dumps(ctx_preview, ensure_ascii=False))
        if input.media_refs:
            parts.append("Media:\n" + json.dumps(input.media_refs, ensure_ascii=False))
        return "\n\n".join(parts).strip() or "(silence)"
