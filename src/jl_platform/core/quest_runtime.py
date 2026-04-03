from __future__ import annotations

import inspect
import json
import hashlib
import os
import re
import time
from queue import Queue
from difflib import SequenceMatcher
from dataclasses import dataclass, field
from pathlib import Path
from threading import Event, RLock, Thread, current_thread
from typing import Any, Callable, Dict, Iterable, List, Optional

from jl_engine_core.engine_core import JLEngineCore
from jl_engine_core.modular_agents import get_modular_agent_summary, is_modular_agent_payload, resolve_modular_agent_payload
from jl_platform.controllers import backend_controller
from jl_platform.core.interpreter import InterpreterSession
from jl_platform.core.tools.builtin import default_allow_unsafe_tools
from jl_platform.core.tools.PrivilegedMemoryForge import PrivilegedMemoryForge
from modules import card2mpf
from tools.business_mpf_generator import generate_business_mpf

JL_FAT_AGENT_ID = "jl_fat_agent"
DEFAULT_SWITCHBOARD_PATH = (
    Path(__file__).resolve().parents[3] / "jl_engine_core" / "data" / "config" / "JL_Engine_Switchboard.v1.json"
)


def _env_bool(name: str, default: bool) -> bool:
    raw = str(os.getenv(name, "1" if default else "0")).strip().lower()
    return raw not in {"0", "false", "off", "no"}


def _hash_text(value: str) -> str:
    return hashlib.sha256((value or "").encode("utf-8")).hexdigest()


def _default_loop_timeout_seconds() -> float:
    raw = str(os.getenv("JL_AGENT_LOOP_TIMEOUT_SECONDS") or "").strip()
    try:
        value = float(raw) if raw else 420.0
    except ValueError:
        value = 420.0
    return max(30.0, value)


@dataclass
class QuestAgent:
    agent_id: str
    agent: str
    session: InterpreterSession
    forge: PrivilegedMemoryForge
    parent_agent_id: Optional[str] = None
    created_at: float = field(default_factory=time.time)
    clone_generation: int = 0
    side_quests: List[str] = field(default_factory=list)
    last_reply_hashes: List[str] = field(default_factory=list)
    last_reply_texts: List[str] = field(default_factory=list)
    failures: int = 0
    loop_turns: int = 0
    loop_last_error: Optional[str] = None
    loop_last_job: Optional[str] = None
    loop_active: bool = False
    loop_persistent: bool = False
    active_lane: str = "fat_agent"
    active_child: str = "SparkByte"
    active_agent_name: str = "SparkByte"
    generated_children: Dict[str, str] = field(default_factory=dict)
    last_generated_instance_id: Optional[str] = None
    last_delegated_to: Optional[str] = None
    last_delegated_class: Optional[str] = None
    agentic_profile: Dict[str, Any] = field(default_factory=dict)


@dataclass
class AgentLoopJob:
    kind: str
    payload: Dict[str, Any]
    created_at: float = field(default_factory=time.time)
    done: Event = field(default_factory=Event)
    result: Optional[Dict[str, Any]] = None


class FatQuestRuntime:
    """
    Capability-first orchestration layer for fat questing agents.

    Features:
    - MPF agent-backed main chat
    - In-RAM tool forge for direct task execution
    - Clone-on-failure / loop continuation
    - Side-quest worker agents
    - Dynamic RAM tool lifecycle with promote/retire
    """

    def __init__(self) -> None:
        self._agents: Dict[str, QuestAgent] = {}
        self._lock = RLock()
        self._agent_loop_threads: Dict[str, Thread] = {}
        self._agent_loop_queues: Dict[str, Queue[AgentLoopJob]] = {}
        self._loop_task_timeout_seconds = _default_loop_timeout_seconds()
        self._agents_dir = Path(__file__).resolve().parents[3] / "jl_engine_core" / "data" / "agents"
        self._generated_agents_dir = self._agents_dir / "generated"
        self._registry_path = self._agents_dir / "JL_Agents.mpf.json"
        self._registry_path_alt = self._agents_dir / "JL_Agents.mpf"
        self._runtime_registry_entries: Dict[str, Dict[str, Any]] = {}
        self._switchboard_path = DEFAULT_SWITCHBOARD_PATH
        self._switchboard = self._load_switchboard()

    def _default_switchboard(self) -> dict[str, Any]:
        return {
            "version": "1",
            "default_lane": "fat_agent",
            "lanes": {
                "fat_agent": {
                    "label": "Mothership Agents",
                    "default_child": "SparkByte",
                    "children": {
                        "SparkByte": {
                            "agent_name": "SparkByte",
                            "classification": "fat_agent",
                            "label": "SparkByte",
                        },
                        "Slappy": {
                            "agent_name": "Slappy",
                            "classification": "fat_agent",
                            "label": "Slappy",
                        },
                        "The Gremlin": {
                            "agent_name": "The Gremlin",
                            "classification": "fat_agent",
                            "label": "The Gremlin",
                        },
                    },
                },
                "jl_agent": {
                    "label": "JL Specialist Agents",
                    "default_child": "Forgebinder",
                    "children": {
                        "Forgebinder": {
                            "agent_name": "Forgebinder",
                            "classification": "jl_agent",
                            "label": "Forgebinder",
                        },
                        "SaaS Copywriter": {
                            "agent_name": "SaaS Copywriter",
                            "classification": "jl_agent",
                            "label": "SaaS Copywriter",
                        },
                        "YouTube Scriptwriter": {
                            "agent_name": "YouTube Scriptwriter",
                            "classification": "jl_agent",
                            "label": "YouTube Scriptwriter",
                        },
                    },
                },
                "generated": {
                    "label": "Generated Agent Templates",
                    "default_child": "Task Helper",
                    "children": {
                        "Task Helper": {
                            "classification": "generated",
                            "label": "Task Helper",
                            "role": "Task Helper",
                            "description": "A practical generated helper for decomposing work and keeping task state tidy.",
                            "style": "focused",
                            "tags": ["generated", "task", "helper"],
                            "directives": [
                                "Break work into clear steps before acting.",
                                "Keep outputs structured and easy for the parent agent to merge.",
                            ],
                        },
                        "Specialist Builder": {
                            "classification": "generated",
                            "label": "Specialist Builder",
                            "role": "Specialist Builder",
                            "description": "A generated specialist for narrow domain work that should come back with a clear summary.",
                            "style": "technical",
                            "tags": ["generated", "specialist", "builder"],
                            "directives": [
                                "Adopt a narrow specialty that matches the task.",
                                "Return concise findings the parent agent can present.",
                            ],
                        },
                        "Support Wing": {
                            "classification": "generated",
                            "label": "Support Wing",
                            "role": "Support Wing",
                            "description": "A generated support agent for debugging, triage, cleanup, and execution follow-through.",
                            "style": "supportive",
                            "tags": ["generated", "support", "triage"],
                            "directives": [
                                "Stabilize the task before expanding it.",
                                "Surface blockers and mitigation clearly.",
                            ],
                        },
                    },
                },
            },
        }

    def _load_switchboard(self) -> dict[str, Any]:
        default = self._default_switchboard()
        path = Path(self._switchboard_path)
        if not path.exists():
            return default
        try:
            loaded = json.loads(path.read_text(encoding="utf-8-sig"))
        except Exception:
            return default
        if not isinstance(loaded, dict):
            return default
        lanes = loaded.get("lanes")
        if not isinstance(lanes, dict):
            return default
        loaded.setdefault("version", default["version"])
        loaded.setdefault("default_lane", default["default_lane"])
        return loaded

    def _switchboard_default_lane(self) -> str:
        lane = str((self._switchboard or {}).get("default_lane") or "fat_agent").strip()
        return lane or "fat_agent"

    def _switchboard_lane_entry(self, lane: str | None) -> dict[str, Any]:
        lanes = (self._switchboard or {}).get("lanes")
        if not isinstance(lanes, dict):
            return {}
        resolved = str(lane or self._switchboard_default_lane()).strip() or self._switchboard_default_lane()
        entry = lanes.get(resolved)
        return entry if isinstance(entry, dict) else {}

    def _switchboard_child_entry(self, lane: str, child: str | None = None) -> tuple[str, dict[str, Any]]:
        lane_entry = self._switchboard_lane_entry(lane)
        children = lane_entry.get("children")
        if not isinstance(children, dict):
            return "", {}
        resolved_child = str(child or lane_entry.get("default_child") or "").strip()
        if not resolved_child:
            return "", {}
        entry = children.get(resolved_child)
        if isinstance(entry, dict):
            return resolved_child, entry
        for key, value in children.items():
            if str(key).strip().lower() == resolved_child.lower() and isinstance(value, dict):
                return str(key), value
        return "", {}

    def _selection_defaults(self) -> dict[str, Any]:
        lane = self._switchboard_default_lane()
        child, entry = self._switchboard_child_entry(lane)
        agent_name = str(entry.get("agent_name") or child or "SparkByte").strip() or "SparkByte"
        return {
            "lane": lane,
            "child": child or "SparkByte",
            "agent_name": agent_name,
            "classification": str(entry.get("classification") or lane).strip() or lane,
            "generated_instance_id": None,
        }

    def _current_selection(self, agent: QuestAgent | None = None) -> dict[str, Any]:
        if agent is None:
            return self._selection_defaults()
        lane = str(agent.active_lane or "").strip() or self._switchboard_default_lane()
        child = str(agent.active_child or "").strip()
        agent_name = str(agent.active_agent_name or agent.agent or "").strip()
        if child and agent_name:
            return {
                "lane": lane,
                "child": child,
                "agent_name": agent_name,
                "classification": "generated" if lane == "generated" else lane,
                "generated_instance_id": agent.last_generated_instance_id,
            }
        return self._selection_defaults()

    def get_switchboard(self, agent_id: str = JL_FAT_AGENT_ID) -> dict[str, Any]:
        resolved_agent_id = str(agent_id or JL_FAT_AGENT_ID).strip() or JL_FAT_AGENT_ID
        current = self._selection_defaults()
        agent_snapshot: dict[str, Any] | None = None
        with self._lock:
            agent = self._agents.get(resolved_agent_id)
            if agent is not None:
                current = self._current_selection(agent)
                agent_snapshot = self._agent_snapshot(agent)
        return {
            "status": "ok",
            "agent_id": resolved_agent_id,
            "default_lane": self._switchboard_default_lane(),
            "lanes": (self._switchboard or {}).get("lanes") or {},
            "current": current,
            "agent": agent_snapshot,
        }

    def _sanitize_name_fragment(self, value: str) -> str:
        text = "".join(ch if ch.isalnum() or ch in ("-", "_") else "_" for ch in str(value or ""))
        text = re.sub(r"_+", "_", text).strip("_")
        return text or "agent"

    def _emit_stream_event(
        self,
        event_sink: Callable[[Dict[str, Any]], None] | None,
        event_type: str,
        **payload: Any,
    ) -> None:
        if event_sink is None:
            return
        try:
            event_sink({"type": event_type, **payload})
        except Exception:
            pass

    def _call_with_optional_event_sink(
        self,
        callable_obj: Any,
        *args: Any,
        event_sink: Callable[[Dict[str, Any]], None] | None = None,
        **kwargs: Any,
    ) -> Any:
        if event_sink is not None:
            try:
                signature = inspect.signature(callable_obj)
                params = signature.parameters
                if "event_sink" in params or any(
                    param.kind == inspect.Parameter.VAR_KEYWORD for param in params.values()
                ):
                    return callable_obj(*args, event_sink=event_sink, **kwargs)
            except (TypeError, ValueError):
                pass
        return callable_obj(*args, **kwargs)

    def _apply_runtime_backend_mode(self) -> dict[str, Any]:
        try:
            return backend_controller.apply_runtime_mode()
        except Exception:
            return {
                "configured_mode": "local_only",
                "effective_mode": "local_only",
                "fallback_reason": "backend_controller_unavailable",
                "brain_backend_id": "ollama-local",
                "tool_backend_id": "ollama-local",
            }

    def _backend_status(self) -> dict[str, Any]:
        status = dict(backend_controller.get_runtime_mode_status())
        status["effective_model"] = backend_controller.get_effective_model_name()
        return status

    def _load_agent_payload_by_name(self, agent_name: str) -> dict[str, Any]:
        registry = self._load_registry()
        entry = registry.get(agent_name) if isinstance(registry.get(agent_name), dict) else {}
        agent_file = str((entry or {}).get("jl_agent_file") or (entry or {}).get("agent_file") or "").strip()
        if not agent_file:
            return {}
        path = self._agents_dir / agent_file
        if not path.exists():
            return {}
        try:
            payload = json.loads(path.read_text(encoding="utf-8-sig"))
        except Exception:
            return {}
        if not isinstance(payload, dict):
            return {}
        if is_modular_agent_payload(payload):
            try:
                return resolve_modular_agent_payload(payload, agent_path=path)
            except Exception:
                return payload
        return payload

    def _resolve_agentic_profile(self, agent_name: str) -> dict[str, Any]:
        payload = self._load_agent_payload_by_name(agent_name)
        if not isinstance(payload, dict):
            payload = {}
        meta = payload.get("meta") if isinstance(payload.get("meta"), dict) else {}
        behavior = payload.get("behavior") if isinstance(payload.get("behavior"), dict) else {}
        capabilities = payload.get("capabilities") if isinstance(payload.get("capabilities"), dict) else {}
        runtime = payload.get("runtime") if isinstance(payload.get("runtime"), dict) else {}

        agentic_source: dict[str, Any] = {}
        for candidate in (
            payload.get("agentic"),
            meta.get("agentic") if isinstance(meta, dict) else None,
            behavior.get("agentic") if isinstance(behavior, dict) else None,
            capabilities.get("agentic") if isinstance(capabilities, dict) else None,
            runtime.get("agentic") if isinstance(runtime, dict) else None,
        ):
            if isinstance(candidate, dict):
                agentic_source = candidate
                break

        def _as_bool(value: Any, default: bool) -> bool:
            if value is None:
                return default
            if isinstance(value, bool):
                return value
            text = str(value).strip().lower()
            if text in {"1", "true", "on", "yes", "y"}:
                return True
            if text in {"0", "false", "off", "no", "n"}:
                return False
            return default

        def _as_int(value: Any, default: int) -> int:
            try:
                return int(value) if value is not None else default
            except (TypeError, ValueError):
                return default

        raw_tool_mode = str(
            agentic_source.get("tool_mode")
            or agentic_source.get("tooling_mode")
            or agentic_source.get("tool_policy")
            or "forge_first"
        ).strip().lower()
        if raw_tool_mode in {"forge-only", "forge_only"}:
            raw_tool_mode = "forge_only"
        if raw_tool_mode not in {"forge_first", "forge_only", "external_first", "external_only"}:
            raw_tool_mode = "forge_first"

        raw_external_fallback = agentic_source.get("external_fallback")
        if raw_external_fallback is None:
            raw_external_fallback = agentic_source.get("external_tool_fallback")

        profile = {
            "enabled": _as_bool(agentic_source.get("enabled"), True),
            "tool_mode": raw_tool_mode,
            "external_fallback": _as_bool(
                raw_external_fallback,
                raw_tool_mode in {"forge_first", "external_first"},
            ),
            "allow_unsafe_tools": _as_bool(agentic_source.get("allow_unsafe_tools"), default_allow_unsafe_tools()),
            "allow_direct_action_fallback": _as_bool(
                agentic_source.get("allow_direct_action_fallback"),
                _env_bool("JL_INTERPRETER_ALLOW_DIRECT_ACTION_FALLBACK", False),
            ),
            "delegation_mode": str(agentic_source.get("delegation_mode") or "").strip().lower() or None,
            "delegate_max_workers": max(
                1,
                min(_as_int(agentic_source.get("delegate_max_workers"), 6), 24),
            ),
            "delegated_execution_mode": str(
                agentic_source.get("delegated_execution_mode") or "execute"
            ).strip().lower(),
            "execution_mode": str(agentic_source.get("execution_mode") or "auto").strip().lower(),
        }
        if profile["delegated_execution_mode"] not in {"auto", "chat", "execute"}:
            profile["delegated_execution_mode"] = "execute"
        if profile["execution_mode"] not in {"auto", "chat", "execute"}:
            profile["execution_mode"] = "execute"
        return profile

    def _apply_session_agentic_profile(self, agent_obj: QuestAgent) -> None:
        profile = self._resolve_agentic_profile(agent_obj.agent)
        agent_obj.agentic_profile = dict(profile)
        session = agent_obj.session
        try:
            session.allow_direct_action_fallback = bool(profile.get("allow_direct_action_fallback", False))
        except Exception:
            pass
        try:
            session.allow_unsafe_tools = bool(profile.get("allow_unsafe_tools", default_allow_unsafe_tools()))
        except Exception:
            pass

    def _resolve_agent_selection_from_name(self, agent_name: str) -> dict[str, Any]:
        name = str(agent_name or "").strip()
        if not name:
            return self._selection_defaults()

        for lane_name, lane_entry in ((self._switchboard or {}).get("lanes") or {}).items():
            if not isinstance(lane_entry, dict) or str(lane_name) == "generated":
                continue
            children = lane_entry.get("children")
            if not isinstance(children, dict):
                continue
            for child_name, child_entry in children.items():
                if not isinstance(child_entry, dict):
                    continue
                resolved_agent = str(child_entry.get("agent_name") or child_name).strip()
                if name.lower() == resolved_agent.lower():
                    return {
                        "lane": str(lane_name),
                        "child": str(child_name),
                        "agent_name": resolved_agent,
                        "classification": str(child_entry.get("classification") or lane_name),
                        "generated_instance_id": None,
                    }

        registry = self._load_registry()
        lookup = {str(key).lower(): str(key) for key in registry.keys()}
        resolved_name = lookup.get(name.lower(), name)
        entry = registry.get(resolved_name) if isinstance(registry.get(resolved_name), dict) else {}
        classification = str((entry or {}).get("classification") or "").strip()
        if classification == "generated":
            switchboard_meta = (entry or {}).get("switchboard")
            if not isinstance(switchboard_meta, dict):
                payload = self._load_agent_payload_by_name(resolved_name)
                meta = payload.get("meta") if isinstance(payload.get("meta"), dict) else {}
                switchboard_meta = meta.get("switchboard") if isinstance(meta.get("switchboard"), dict) else {}
            child = str((switchboard_meta or {}).get("child") or resolved_name).strip() or resolved_name
            return {
                "lane": "generated",
                "child": child,
                "agent_name": resolved_name,
                "classification": "generated",
                "generated_instance_id": resolved_name,
            }
        if classification in {"fat_agent", "jl_agent", "runtime_support"}:
            return {
                "lane": classification,
                "child": resolved_name,
                "agent_name": resolved_name,
                "classification": classification,
                "generated_instance_id": None,
            }
        return {
            "lane": self._switchboard_default_lane(),
            "child": resolved_name,
            "agent_name": resolved_name,
            "classification": classification or self._switchboard_default_lane(),
            "generated_instance_id": None,
        }

    def _set_agent_selection_state(
        self,
        agent_obj: QuestAgent,
        *,
        lane: str,
        child: str,
        agent_name: str,
        generated_instance_id: str | None = None,
    ) -> None:
        agent_obj.active_lane = str(lane or self._switchboard_default_lane()).strip() or self._switchboard_default_lane()
        agent_obj.active_child = str(child or agent_name or "SparkByte").strip() or "SparkByte"
        agent_obj.active_agent_name = str(agent_name or agent_obj.agent or "SparkByte").strip() or "SparkByte"
        if generated_instance_id:
            agent_obj.last_generated_instance_id = str(generated_instance_id)
            agent_obj.generated_children[agent_obj.active_child] = str(generated_instance_id)
        elif agent_obj.active_lane != "generated":
            agent_obj.last_generated_instance_id = None

    def _build_generated_agent_payload(
        self,
        *,
        instance_name: str,
        child: str,
        template: dict[str, Any],
        parent_agent_id: str,
        parent_lane: str,
        parent_agent_name: str,
        source_task: str,
    ) -> dict[str, Any]:
        style = str(template.get("style") or "focused").strip() or "focused"
        directives = [str(item) for item in (template.get("directives") or []) if str(item).strip()]
        tags = [str(item) for item in (template.get("tags") or []) if str(item).strip()]
        if "generated" not in tags:
            tags.append("generated")
        return {
            "identity": {
                "name": instance_name,
                "role": str(template.get("role") or child or "Generated Agent").strip() or "Generated Agent",
                "description": str(template.get("description") or f"{child} generated for {parent_agent_name}.").strip(),
                "tags": tags,
            },
            "behavior": {
                "directives": directives
                or [
                    "Take ownership of a narrow sub-task and return a clean summary.",
                    "Stay aligned with the parent agent's intent and constraints.",
                ],
                "boundaries": [],
                "tone": style,
                "scenario": "switchboard_generated",
            },
            "communication_style": {
                "voice": style,
                "agentlity": {"temperament": "focused"},
                "style_notes": [style],
            },
            "memory": {"mode": "HYBRID"},
            "gait": {"default": "walk"},
            "rhythm": {"default": "flop"},
            "aperture": {"mode": "balanced"},
            "llm_profiles": {
                "generic_llm": {
                    "boot_prompt": (
                        f"You are {instance_name}, a generated {child} agent operating under {parent_agent_name}. "
                        "Do the sub-task cleanly and return material the parent agent can present."
                    )
                }
            },
            "agentic": {
                "enabled": True,
                "tool_mode": "forge_first",
                "external_fallback": True,
                "execution_mode": "execute",
                "delegated_execution_mode": "execute",
                "allow_direct_action_fallback": False,
            },
            "meta": {
                "source": "switchboard_generated_template",
                "switchboard": {
                    "lane": "generated",
                    "child": child,
                    "parent_lane": parent_lane,
                    "parent_agent_id": parent_agent_id,
                    "parent_agent_name": parent_agent_name,
                    "created_at": time.time(),
                    "source_task": str(source_task or "")[:2000],
                },
            },
        }

    def _find_generated_instance(self, parent_agent_id: str, child: str) -> dict[str, Any] | None:
        registry = self._load_registry()
        best_match: dict[str, Any] | None = None
        best_created = -1.0
        for agent_name, raw_entry in registry.items():
            entry = raw_entry if isinstance(raw_entry, dict) else {}
            if str(entry.get("classification") or "").strip() != "generated":
                continue
            switchboard_meta = entry.get("switchboard")
            if not isinstance(switchboard_meta, dict):
                payload = self._load_agent_payload_by_name(str(agent_name))
                meta = payload.get("meta") if isinstance(payload.get("meta"), dict) else {}
                switchboard_meta = meta.get("switchboard") if isinstance(meta.get("switchboard"), dict) else {}
            if not isinstance(switchboard_meta, dict):
                continue
            if str(switchboard_meta.get("parent_agent_id") or "").strip() != str(parent_agent_id or "").strip():
                continue
            if str(switchboard_meta.get("child") or "").strip() != str(child or "").strip():
                continue
            created_at = float(switchboard_meta.get("created_at") or 0.0)
            if created_at >= best_created:
                best_created = created_at
                best_match = {
                    "agent_name": str(agent_name),
                    "entry": entry,
                    "switchboard": switchboard_meta,
                }
        return best_match

    def _ensure_generated_instance(
        self,
        *,
        parent_agent_id: str,
        parent_lane: str,
        parent_agent_name: str,
        child: str,
        template: dict[str, Any],
        new_instance: bool = False,
        source_task: str = "",
    ) -> dict[str, Any]:
        if not new_instance:
            existing = self._find_generated_instance(parent_agent_id=parent_agent_id, child=child)
            if existing:
                return {
                    "lane": "generated",
                    "child": child,
                    "agent_name": str(existing.get("agent_name") or child),
                    "classification": "generated",
                    "generated_instance_id": str(existing.get("agent_name") or child),
                }

        base_name = f"{child} ({self._sanitize_name_fragment(parent_agent_id)})"
        instance_name = base_name if not new_instance else f"{base_name} #{int(time.time() * 1000)}"
        payload = self._build_generated_agent_payload(
            instance_name=instance_name,
            child=child,
            template=template,
            parent_agent_id=parent_agent_id,
            parent_lane=parent_lane,
            parent_agent_name=parent_agent_name,
            source_task=source_task,
        )
        self._persist_agent(
            instance_name,
            payload,
            classification="generated",
            persist_registry=False,
            registry_extra={
                "switchboard": {
                    "lane": "generated",
                    "child": child,
                    "parent_lane": parent_lane,
                    "parent_agent_id": parent_agent_id,
                    "parent_agent_name": parent_agent_name,
                    "created_at": float((payload.get("meta") or {}).get("switchboard", {}).get("created_at") or time.time()),
                }
            },
        )
        return {
            "lane": "generated",
            "child": child,
            "agent_name": instance_name,
            "classification": "generated",
            "generated_instance_id": instance_name,
        }

    def _resolve_switch_selection(
        self,
        *,
        agent_obj: QuestAgent,
        lane: str | None = None,
        child: str | None = None,
        agent_name: str | None = None,
        new_instance: bool = False,
        source_task: str = "",
        parent_agent_id: str | None = None,
        parent_lane: str | None = None,
        parent_agent_name: str | None = None,
    ) -> dict[str, Any]:
        explicit_agent = str(agent_name or "").strip()
        if explicit_agent:
            return self._resolve_agent_selection_from_name(explicit_agent)

        explicit_lane = str(lane or "").strip()
        explicit_child = str(child or "").strip()
        if explicit_child and not explicit_lane:
            for lane_name, lane_entry in ((self._switchboard or {}).get("lanes") or {}).items():
                children = lane_entry.get("children") if isinstance(lane_entry, dict) else {}
                if isinstance(children, dict) and explicit_child in children:
                    explicit_lane = str(lane_name)
                    break

        if not explicit_lane:
            current = self._current_selection(agent_obj)
            explicit_lane = str(current.get("lane") or self._switchboard_default_lane())
            explicit_child = explicit_child or str(current.get("child") or "")

        resolved_child, child_entry = self._switchboard_child_entry(explicit_lane, explicit_child or None)
        if explicit_lane == "generated":
            if not resolved_child or not child_entry:
                resolved_child, child_entry = self._switchboard_child_entry("generated", None)
            return self._ensure_generated_instance(
                parent_agent_id=str(parent_agent_id or agent_obj.agent_id or "").strip() or agent_obj.agent_id,
                parent_lane=str(parent_lane or agent_obj.active_lane or self._switchboard_default_lane()),
                parent_agent_name=str(parent_agent_name or agent_obj.active_agent_name or agent_obj.agent or "SparkByte"),
                child=resolved_child or "Task Helper",
                template=child_entry or {},
                new_instance=new_instance,
                source_task=source_task,
            )

        if resolved_child and child_entry:
            return {
                "lane": explicit_lane,
                "child": resolved_child,
                "agent_name": str(child_entry.get("agent_name") or resolved_child).strip() or resolved_child,
                "classification": str(child_entry.get("classification") or explicit_lane).strip() or explicit_lane,
                "generated_instance_id": None,
            }

        return self._resolve_agent_selection_from_name(explicit_child or explicit_lane or "SparkByte")

    def switch_agent(
        self,
        *,
        agent_id: str,
        lane: str,
        child: str | None = None,
        new_instance: bool = False,
    ) -> dict[str, Any]:
        resolved_agent_id = str(agent_id or JL_FAT_AGENT_ID).strip() or JL_FAT_AGENT_ID
        agent_obj = self.ensure_agent(resolved_agent_id)
        selection = self._resolve_switch_selection(
            agent_obj=agent_obj,
            lane=lane,
            child=child,
            new_instance=new_instance,
        )
        self._sync_agent_agent(agent_obj, selection.get("agent_name"))
        with self._lock:
            self._set_agent_selection_state(
                agent_obj,
                lane=str(selection.get("lane") or self._switchboard_default_lane()),
                child=str(selection.get("child") or selection.get("agent_name") or "SparkByte"),
                agent_name=str(selection.get("agent_name") or "SparkByte"),
                generated_instance_id=str(selection.get("generated_instance_id") or "") or None,
            )
        return {
            "status": "ok",
            "agent_id": resolved_agent_id,
            "selection": selection,
            "agent": self._agent_snapshot(agent_obj),
        }

    def list_agents(self) -> list[dict[str, Any]]:
        with self._lock:
            return [self._agent_snapshot(agent) for agent in self._agents.values()]

    def ensure_agent(self, agent_id: str, agent_name: str = "SparkByte") -> QuestAgent:
        with self._lock:
            existing = self._agents.get(agent_id)
            if existing:
                agent_obj = existing
                if str(agent_name or "").strip():
                    self._sync_agent_agent(agent_obj, agent_name)
                self._apply_session_agentic_profile(agent_obj)
            else:
                self._apply_runtime_backend_mode()
                forge = PrivilegedMemoryForge()
                engine = JLEngineCore()
                self._activate_engine(engine)
                try:
                    engine.set_agent(agent_name)
                except Exception:
                    pass
                profile = self._resolve_agentic_profile(agent_name)
                session = InterpreterSession(
                    engine=engine,
                    memory_forge=forge,
                    allow_unsafe_tools=bool(profile.get("allow_unsafe_tools", default_allow_unsafe_tools())),
                    allow_direct_action_fallback=bool(profile.get("allow_direct_action_fallback", False)),
                )
                agent_obj = QuestAgent(agent_id=agent_id, agent=agent_name, session=session, forge=forge)
                agent_obj.agentic_profile = dict(profile)
                selection = self._resolve_agent_selection_from_name(agent_name)
                self._set_agent_selection_state(
                    agent_obj,
                    lane=str(selection.get("lane") or "fat_agent"),
                    child=str(selection.get("child") or agent_name),
                    agent_name=str(selection.get("agent_name") or agent_name),
                    generated_instance_id=str(selection.get("generated_instance_id") or "") or None,
                )
                self._agents[agent_id] = agent_obj
            self._apply_session_agentic_profile(agent_obj)
        return agent_obj

    def _sync_agent_agent(self, agent_obj: QuestAgent, agent_name: str | None = None) -> None:
        desired_agent = str(agent_name or agent_obj.agent or "SparkByte").strip() or "SparkByte"
        agent_obj.agent = desired_agent
        agent_obj.active_agent_name = desired_agent
        engine = agent_obj.session.engine
        current_agent = str(getattr(engine, "current_agent_name", "") or "").strip()
        if current_agent == desired_agent:
            self._apply_session_agentic_profile(agent_obj)
            return
        try:
            self._activate_engine(engine)
            engine.set_agent(desired_agent)
        except Exception:
            pass
        self._apply_session_agentic_profile(agent_obj)

    def register_agent(
        self, agent_id: str, agent_name: str = "SparkByte", parent_agent_id: str | None = None
    ) -> dict[str, Any]:
        agent_obj = self.ensure_agent(agent_id, agent_name=agent_name)
        with self._lock:
            selection = self._resolve_agent_selection_from_name(agent_name)
            self._sync_agent_agent(agent_obj, agent_name)
            self._set_agent_selection_state(
                agent_obj,
                lane=str(selection.get("lane") or self._switchboard_default_lane()),
                child=str(selection.get("child") or agent_name),
                agent_name=str(selection.get("agent_name") or agent_name),
                generated_instance_id=str(selection.get("generated_instance_id") or "") or None,
            )
            if parent_agent_id:
                agent_obj.parent_agent_id = parent_agent_id
        return {"status": "ok", "agent": self._agent_snapshot(agent_obj)}

    def register_business_agent(
        self,
        agent_id: str,
        *,
        name: str,
        industry: str,
        voice: str,
        audience: str,
        values: str,
        style: str,
        abilities: str,
        mission: str = "",
        products: str = "",
        docs: str = "",
    ) -> dict[str, Any]:
        agent_payload = generate_business_mpf(
            name=name,
            industry=industry,
            voice=voice,
            audience=audience,
            values=values,
            style=style,
            abilities=abilities,
            mission=mission,
            products=products,
            docs=docs,
        )
        agent_name = str(((agent_payload.get("identity") or {}).get("name")) or name or agent_id)
        self._persist_agent(agent_name, agent_payload)
        return self.register_agent(agent_id=agent_id, agent_name=agent_name)

    def register_card_agent(self, agent_id: str, card_path: str) -> dict[str, Any]:
        card = card2mpf.load_card(Path(card_path))
        agent_payload = card2mpf.normalizeFinal(card2mpf.normalizeAgentInput(card))
        agent_name = str(((agent_payload.get("identity") or {}).get("name")) or Path(card_path).stem)
        self._persist_agent(agent_name, agent_payload)
        return self.register_agent(agent_id=agent_id, agent_name=agent_name)

    def register_mpf_agent(self, agent_id: str, mpf_path: str) -> dict[str, Any]:
        safe_path = card2mpf.resolve_safe_import_path(Path(mpf_path), allowed_suffixes={".json", ".mpf"})
        payload = json.loads(safe_path.read_text(encoding="utf-8"))
        agent_payload = card2mpf.normalizeFinal(card2mpf.normalizeAgentInput(payload))
        agent_name = str(((agent_payload.get("identity") or {}).get("name")) or Path(mpf_path).stem)
        self._persist_agent(agent_name, agent_payload)
        result = self.register_agent(agent_id=agent_id, agent_name=agent_name)
        self._set_agent_loop_persistent(agent_id, True)
        self._ensure_agent_loop(agent_id)
        return result

    def register_mpf_agent_agent(self, agent_id: str, agent_name: str) -> dict[str, Any]:
        requested = str(agent_name or "").strip()
        if not requested:
            return {"status": "error", "error": "agent_name_required"}

        registry = self._load_registry()
        if requested not in registry:
            lookup = {str(name).lower(): str(name) for name in registry.keys()}
            match = lookup.get(requested.lower())
            if not match:
                return {"status": "error", "error": f"agent_not_found:{requested}"}
            requested = match

        entry = registry.get(requested) if isinstance(registry.get(requested), dict) else {}
        jl_agent_file = str((entry or {}).get("jl_agent_file") or (entry or {}).get("agent_file") or "").strip()
        if not jl_agent_file:
            return {"status": "error", "error": f"agent_missing_file:{requested}"}

        agent_path = self._agents_dir / jl_agent_file
        if not agent_path.exists():
            return {
                "status": "error",
                "error": f"jl_agent_file_missing:{jl_agent_file}",
                "agent_name": requested,
                "path": str(agent_path),
            }

        result = self.register_agent(agent_id, requested)
        self._set_agent_loop_persistent(agent_id, True)
        self._ensure_agent_loop(agent_id)
        result["agent_name"] = requested
        result["agent_name"] = requested
        result["jl_agent_file"] = jl_agent_file
        result["path"] = str(agent_path)
        return result

    def _build_agent_info(self, agent_name: str, entry: dict[str, Any]) -> dict[str, Any]:
        jl_agent_file = str(entry.get("jl_agent_file") or entry.get("agent_file") or "").strip()
        agent_path = (self._agents_dir / jl_agent_file) if jl_agent_file else self._agents_dir
        tags_raw = entry.get("tags")
        tags = [str(tag) for tag in tags_raw] if isinstance(tags_raw, list) else []
        payload = self._load_agent_payload_by_name(str(agent_name)) if jl_agent_file else {}
        modular_summary = get_modular_agent_summary(payload)
        profile_type = "modular_fat_agent" if modular_summary else "classic_agent"
        return {
            "agent_name": str(agent_name),
            "name": str(agent_name),
            "jl_agent_file": jl_agent_file,
            "path": str(agent_path),
            "exists": agent_path.exists() if jl_agent_file else False,
            "default_backend_id": entry.get("default_backend_id"),
            "default_memory_mode": entry.get("default_memory_mode"),
            "drive_type": entry.get("drive_type"),
            "classification": entry.get("classification"),
            "tags": tags,
            "profile_type": profile_type,
            "modular_summary": modular_summary,
        }

    def list_mpf_agents(self) -> list[dict[str, Any]]:
        registry = self._load_registry()
        agents: list[dict[str, Any]] = []
        for agent_name in sorted(registry.keys(), key=lambda item: str(item).lower()):
            if str(agent_name).startswith("_"):
                # Underscore-prefixed keys are metadata (e.g. _license) — skip silently.
                continue
            entry_obj = registry.get(agent_name)
            entry = entry_obj if isinstance(entry_obj, dict) else {}
            agents.append(self._build_agent_info(agent_name, entry))
        return agents
        return agents

    def register_agentlized_agent(
        self,
        agent_id: str,
        *,
        name: str,
        role: str,
        description: str = "",
        style: str = "",
        directives: list[str] | None = None,
    ) -> dict[str, Any]:
        agent_payload = {
            "identity": {
                "name": name.strip() or agent_id,
                "role": role.strip() or "Agent",
                "description": description.strip()
                or f"{name.strip() or agent_id} is an agentlized questing agent.",
                "tags": ["agentlized", "fat-agent"],
            },
            "behavior": {
                "directives": directives or [
                    "Operate directly through in-memory tools when possible.",
                    "Escalate to side quests for secondary tasks.",
                    "Preserve continuity by cloning on detected loop/failure.",
                ],
                "boundaries": [],
                "tone": style.strip() or "clear",
                "scenario": "quest_runtime",
            },
            "communication_style": {
                "voice": style.strip() or "clear",
                "agentlity": {"temperament": "focused"},
                "style_notes": [style.strip()] if style.strip() else [],
            },
            "memory": {"mode": "HYBRID"},
            "gait": {"default": "walk"},
            "rhythm": {"default": "flop"},
            "aperture": {"mode": "balanced"},
            "llm_profiles": {
                "generic_llm": {
                    "boot_prompt": (
                        f"You are {name.strip() or agent_id}, a {role.strip() or 'agent'} "
                        "built for direct execution and quest continuity."
                    )
                }
            },
            "meta": {"source": "agentlized_agent_builder"},
        }
        agent_name = str((agent_payload.get("identity") or {}).get("name") or agent_id)
        self._persist_agent(agent_name, agent_payload)
        return self.register_agent(agent_id=agent_id, agent_name=agent_name)

    def _score_task_against_agent(self, task: str, agent_name: str) -> int:
        registry = self._load_registry()
        entry = registry.get(agent_name) if isinstance(registry.get(agent_name), dict) else {}
        task_text = str(task or "").strip().lower()
        if not task_text:
            return 0
        tokens = {tok for tok in re.split(r"[^a-z0-9]+", task_text) if tok}
        score = 0
        name_tokens = [tok for tok in re.split(r"[^a-z0-9]+", str(agent_name).lower()) if tok]
        for token in name_tokens:
            if len(token) > 2 and token in tokens:
                score += 2
        for tag in (entry.get("tags") or []):
            tag_text = str(tag or "").strip().lower()
            if tag_text and (tag_text in tokens or f" {tag_text} " in f" {task_text} "):
                score += 3
        drive_type = str(entry.get("drive_type") or "").strip().lower()
        if drive_type and drive_type in tokens:
            score += 2
        return score

    def _select_jl_specialist_child(self, task: str) -> str | None:
        lane_entry = self._switchboard_lane_entry("jl_agent")
        children = lane_entry.get("children") if isinstance(lane_entry, dict) else {}
        if not isinstance(children, dict):
            return None
        best_child: str | None = None
        best_score = 0
        for child_name, entry in children.items():
            if not isinstance(entry, dict):
                continue
            score = self._score_task_against_agent(task, str(entry.get("agent_name") or child_name))
            if score > best_score:
                best_score = score
                best_child = str(child_name)
        return best_child if best_score > 0 else None

    def _select_generated_child_template(self, task: str) -> str:
        task_text = str(task or "").strip().lower()
        if any(term in task_text for term in ("fix", "debug", "error", "triage", "stuck", "broken")):
            return "Support Wing"
        if any(term in task_text for term in ("build", "create", "implement", "design", "specialist", "wire")):
            return "Specialist Builder"
        return "Task Helper"

    def _should_delegate_to_generated(self, task: str, specialist_child: str | None = None) -> bool:
        task_text = str(task or "").strip().lower()
        if specialist_child:
            return False
        signals = (
            " and ",
            " then ",
            "multi",
            "complex",
            "plan",
            "investigate",
            "analyze",
            "compare",
            "figure out",
            "help me build",
            "help me make",
        )
        return any(signal in task_text for signal in signals) or len(task_text.split()) >= 16

    def _choose_delegation(
        self,
        *,
        agent_obj: QuestAgent,
        message: str,
        current_selection: dict[str, Any],
        explicit_selection: bool,
    ) -> dict[str, Any] | None:
        if explicit_selection:
            return None
        if str(current_selection.get("lane") or "") != "fat_agent":
            return None
        specialist_child = self._select_jl_specialist_child(message)
        if specialist_child:
            return {
                "lane": "jl_agent",
                "child": specialist_child,
                "reason": "specialist_match",
            }
        if self._should_delegate_to_generated(message, specialist_child=specialist_child):
            return {
                "lane": "generated",
                "child": self._select_generated_child_template(message),
                "reason": "generated_branch",
            }
        return None

    def _switchboard_children(self, lane: str) -> list[str]:
        lane_entry = self._switchboard_lane_entry(lane)
        children = lane_entry.get("children") if isinstance(lane_entry, dict) else {}
        if not isinstance(children, dict):
            return []
        names: list[str] = []
        for child_name, child_entry in children.items():
            if not isinstance(child_entry, dict):
                continue
            names.append(str(child_name))
        return names

    def _switchboard_children_with_entries(self, lane: str) -> list[tuple[str, dict[str, Any]]]:
        lane_entry = self._switchboard_lane_entry(lane)
        children = lane_entry.get("children") if isinstance(lane_entry, dict) else {}
        if not isinstance(children, dict):
            return []
        entries: list[tuple[str, dict[str, Any]]] = []
        for child_name, child_entry in children.items():
            if not isinstance(child_entry, dict):
                continue
            entries.append((str(child_name), child_entry))
        return entries

    def _score_delegation_candidate(
        self,
        *,
        message: str,
        lane: str,
        child: str,
        entry: dict[str, Any] | None,
    ) -> int:
        task = str(message or "").strip().lower()
        if not task:
            return 0
        score = 0
        child_low = str(child or "").strip().lower()
        safe_entry = entry if isinstance(entry, dict) else {}

        if lane == "jl_agent":
            agent_name = str(safe_entry.get("agent_name") or child or "").strip()
            score += self._score_task_against_agent(message, agent_name)
            if child_low == "forgebinder":
                if any(
                    term in task
                    for term in (
                        "code",
                        "build",
                        "implement",
                        "debug",
                        "fix",
                        "tool",
                        "automation",
                        "script",
                        "run",
                        "execute",
                        "python",
                        "repo",
                        "file",
                        "api",
                    )
                ):
                    score += 6
            elif "copywriter" in child_low:
                if any(
                    term in task
                    for term in (
                        "copy",
                        "headline",
                        "cta",
                        "landing",
                        "conversion",
                        "ad",
                        "email",
                        "marketing",
                        "brand",
                        "positioning",
                        "pitch",
                        "offer",
                    )
                ):
                    score += 6
            elif "youtube" in child_low or "scriptwriter" in child_low:
                if any(
                    term in task
                    for term in (
                        "youtube",
                        "video",
                        "script",
                        "hook",
                        "thumbnail",
                        "shorts",
                        "retention",
                        "channel",
                        "title",
                        "description",
                    )
                ):
                    score += 6
            return score

        if lane == "generated":
            if child_low == "support wing":
                if any(term in task for term in ("debug", "fix", "error", "traceback", "broken", "stuck", "triage")):
                    score += 7
            elif child_low == "specialist builder":
                if any(term in task for term in ("build", "implement", "design", "architect", "create", "develop")):
                    score += 7
            elif child_low == "task helper":
                score += 2
                if any(term in task for term in ("plan", "organize", "steps", "compare", "analyze", "coordinate", "multi")):
                    score += 3
            return score

        return score

    def _resolve_delegation_mode(self, context: dict[str, Any] | None) -> str:
        payload = context if isinstance(context, dict) else {}
        raw = str(
            payload.get("delegation_mode")
            or payload.get("delegate_mode")
            or payload.get("worker_mode")
            or ""
        ).strip().lower()
        if raw in {"off", "none", "disabled", "false", "0"}:
            return "off"
        if raw in {"all", "all_workers", "all_agents", "full"}:
            return "all"
        if raw in {"multi", "crew", "swarm", "parallel"}:
            return "multi"
        return "single"

    def _resolve_delegation_worker_limit(self, context: dict[str, Any] | None, mode: str) -> int:
        payload = context if isinstance(context, dict) else {}
        default_limit = 1 if mode == "single" else 3 if mode == "multi" else 6
        raw = payload.get("delegate_max_workers", payload.get("max_workers", payload.get("worker_count")))
        try:
            parsed = int(raw) if raw is not None else default_limit
        except (TypeError, ValueError):
            parsed = default_limit
        return max(1, min(parsed, 24))

    def _choose_delegation_plan(
        self,
        *,
        agent_obj: QuestAgent,
        message: str,
        current_selection: dict[str, Any],
        explicit_selection: bool,
        context: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        mode = self._resolve_delegation_mode(context)
        if mode == "off":
            return []
        if mode == "single":
            single = self._choose_delegation(
                agent_obj=agent_obj,
                message=message,
                current_selection=current_selection,
                explicit_selection=explicit_selection,
            )
            return [single] if single else []

        if explicit_selection:
            return []
        if str(current_selection.get("lane") or "") != "fat_agent":
            return []

        scored_candidates: list[tuple[int, dict[str, Any]]] = []
        seen: set[str] = set()

        def _add_scored(lane: str, child: str, reason: str, entry: dict[str, Any] | None = None) -> None:
            key = f"{lane}::{child}".lower()
            if key in seen:
                return
            seen.add(key)
            score = self._score_delegation_candidate(message=message, lane=lane, child=child, entry=entry)
            if score <= 0:
                return
            scored_candidates.append(
                (
                    score,
                    {
                        "lane": lane,
                        "child": child,
                        "reason": reason,
                    },
                )
            )

        specialist_child = self._select_jl_specialist_child(message)
        jl_children = dict(self._switchboard_children_with_entries("jl_agent"))
        generated_children = dict(self._switchboard_children_with_entries("generated"))

        if specialist_child:
            _add_scored(
                "jl_agent",
                specialist_child,
                "specialist_match",
                entry=jl_children.get(specialist_child) or {},
            )

        if mode == "all":
            for child, entry in jl_children.items():
                _add_scored("jl_agent", child, "all_jl_agents", entry=entry)
            for child, entry in generated_children.items():
                _add_scored("generated", child, "all_generated_templates", entry=entry)
        else:
            if not specialist_child:
                default_jl_child, default_jl_entry = self._switchboard_child_entry("jl_agent", None)
                _add_scored("jl_agent", default_jl_child, "default_specialist", entry=default_jl_entry)
            generated_child = self._select_generated_child_template(message)
            _add_scored(
                "generated",
                generated_child,
                "generated_branch",
                entry=generated_children.get(generated_child) or {},
            )
            if self._should_delegate_to_generated(message, specialist_child=specialist_child):
                _add_scored(
                    "generated",
                    "Task Helper",
                    "task_decomposition",
                    entry=generated_children.get("Task Helper") or {},
                )

        scored_candidates.sort(key=lambda item: item[0], reverse=True)
        plan = [item[1] for item in scored_candidates]
        if not plan:
            fallback = self._choose_delegation(
                agent_obj=agent_obj,
                message=message,
                current_selection=current_selection,
                explicit_selection=explicit_selection,
            )
            if fallback:
                plan = [fallback]
        limit = self._resolve_delegation_worker_limit(context, mode)
        return plan[:limit]

    def _telemetry_summary(self, telemetry: dict[str, Any] | None, engine: Any) -> dict[str, Any]:
        payload = telemetry if isinstance(telemetry, dict) else {}
        aperture = payload.get("aperture_state") if isinstance(payload.get("aperture_state"), dict) else {}
        rhythm = payload.get("rhythm") if isinstance(payload.get("rhythm"), dict) else {}
        if not aperture and hasattr(engine, "emotional_aperture") and hasattr(engine.emotional_aperture, "get_state"):
            try:
                aperture = engine.emotional_aperture.get_state()
            except Exception:
                aperture = {}
        return {
            "behavior_profile": payload.get("behavior_profile") or getattr(engine, "behavior_profile_name", None),
            "cognitive_mode": payload.get("cognitive_mode") or getattr(getattr(engine, "current_cognitive_state", None), "dominant_mode", None),
            "gait": payload.get("active_gait_state") or getattr(engine, "current_gait", None),
            "rhythm": (rhythm or {}).get("mode") or payload.get("active_rhythm_pattern") or getattr(engine, "current_rhythm_mode", None),
            "aperture_mode": (aperture or {}).get("mode"),
            "aperture_score": (aperture or {}).get("score"),
        }

    def _merge_delegated_reply(
        self,
        *,
        parent_agent: QuestAgent,
        parent_message: str,
        delegated_reply: str,
        delegated_selection: dict[str, Any],
        context: dict[str, Any],
    ) -> tuple[str, dict[str, Any], dict[str, Any]]:
        merge_context = self._sharp_context(
            {
                **dict(context or {}),
                "delegation_context": {
                    "delegated_to": delegated_selection,
                    "delegated_reply": delegated_reply,
                },
            },
            mode="main_chat",
        )
        merge_prompt = (
            f"User request:\n{parent_message}\n\n"
            f"Delegated {delegated_selection.get('lane')}/{delegated_selection.get('child')} output:\n"
            f"{delegated_reply}\n\n"
            "Reply to the user in the active parent agent voice while integrating the delegated result."
        )
        return parent_agent.session.engine.generate_response(
            merge_prompt,
            agent_name=parent_agent.agent,
            context=merge_context,
        )

    def _merge_delegated_bundle_reply(
        self,
        *,
        parent_agent: QuestAgent,
        parent_message: str,
        delegated_runs: list[dict[str, Any]],
        context: dict[str, Any],
    ) -> tuple[str, dict[str, Any], dict[str, Any]]:
        if len(delegated_runs) == 1:
            run = delegated_runs[0]
            selection = run.get("selection") if isinstance(run.get("selection"), dict) else {}
            return self._merge_delegated_reply(
                parent_agent=parent_agent,
                parent_message=parent_message,
                delegated_reply=str(run.get("reply") or ""),
                delegated_selection=dict(selection),
                context=context,
            )

        delegated_bundle: list[dict[str, Any]] = []
        bundle_blocks: list[str] = []
        for idx, run in enumerate(delegated_runs, start=1):
            selection = run.get("selection") if isinstance(run.get("selection"), dict) else {}
            lane = str(selection.get("lane") or "unknown")
            child = str(selection.get("child") or selection.get("agent_name") or "worker")
            agent_name = str(selection.get("agent_name") or child)
            reply = str(run.get("reply") or "")
            delegated_bundle.append(
                {
                    "index": idx,
                    "lane": lane,
                    "child": child,
                    "agent_name": agent_name,
                    "classification": str(selection.get("classification") or lane),
                    "generated_instance_id": selection.get("generated_instance_id"),
                    "reply": reply,
                }
            )
            bundle_blocks.append(
                f"[Worker {idx}] lane={lane} child={child} agent={agent_name}\n{reply}"
            )

        merge_context = self._sharp_context(
            {
                **dict(context or {}),
                "delegated_bundle": delegated_bundle,
            },
            mode="main_chat",
        )
        merge_prompt = (
            f"User request:\n{parent_message}\n\n"
            "Delegated worker outputs:\n"
            + "\n\n".join(bundle_blocks)
            + "\n\n"
            "Reply to the user in the active parent agent voice while integrating the delegated results into one coherent answer."
        )
        return parent_agent.session.engine.generate_response(
            merge_prompt,
            agent_name=parent_agent.agent,
            context=merge_context,
        )

    def chat(
        self,
        agent_id: str,
        message: str,
        agent: str | None = None,
        lane: str | None = None,
        child: str | None = None,
        new_instance: bool = False,
        context: dict[str, Any] | None = None,
        execution_mode: str = "auto",
        return_trace: bool = True,
        allow_clone: bool = True,
        event_sink: Callable[[Dict[str, Any]], None] | None = None,
    ) -> dict[str, Any]:
        resolved_agent_id = str(agent_id or JL_FAT_AGENT_ID)
        self.ensure_agent(resolved_agent_id, agent_name=agent or "SparkByte")
        return self._submit_agent_job(
            resolved_agent_id,
            "chat",
            {
                "agent_id": resolved_agent_id,
                "message": message,
                "agent": agent,
                "lane": lane,
                "child": child,
                "new_instance": new_instance,
                "context": context,
                "execution_mode": execution_mode,
                "return_trace": return_trace,
                "allow_clone": allow_clone,
                "event_sink": event_sink,
            },
        )

    def _chat_impl(
        self,
        agent_id: str,
        message: str,
        agent: str | None = None,
        lane: str | None = None,
        child: str | None = None,
        new_instance: bool = False,
        context: dict[str, Any] | None = None,
        execution_mode: str = "auto",
        return_trace: bool = True,
        allow_clone: bool = True,
        event_sink: Callable[[Dict[str, Any]], None] | None = None,
    ) -> dict[str, Any]:
        context = dict(context or {})
        visible_agent = self.ensure_agent(agent_id, agent_name=agent or "SparkByte")
        explicit_selection = bool(str(agent or "").strip() or str(lane or "").strip() or str(child or "").strip() or new_instance)
        selection = self._resolve_switch_selection(
            agent_obj=visible_agent,
            lane=lane,
            child=child,
            agent_name=agent,
            new_instance=new_instance,
            source_task=message,
        )
        self._sync_agent_agent(visible_agent, str(selection.get("agent_name") or visible_agent.agent))
        agentic_profile = (
            visible_agent.agentic_profile
            if isinstance(visible_agent.agentic_profile, dict) and visible_agent.agentic_profile
            else self._resolve_agentic_profile(visible_agent.agent)
        )
        if not context.get("delegation_mode") and agentic_profile.get("delegation_mode"):
            context["delegation_mode"] = str(agentic_profile.get("delegation_mode"))
        if not context.get("delegate_max_workers") and agentic_profile.get("delegate_max_workers"):
            context["delegate_max_workers"] = int(agentic_profile.get("delegate_max_workers") or 1)
        if not context.get("delegated_execution_mode") and agentic_profile.get("delegated_execution_mode"):
            context["delegated_execution_mode"] = str(agentic_profile.get("delegated_execution_mode"))
        context.setdefault("tooling_mode", str(agentic_profile.get("tool_mode") or "forge_first"))
        profile_external_fallback = bool(agentic_profile.get("external_fallback", True))

        def _context_bool(value: Any, default: bool) -> bool:
            if value is None:
                return default
            if isinstance(value, bool):
                return value
            lowered = str(value).strip().lower()
            if lowered in {"1", "true", "on", "yes", "y"}:
                return True
            if lowered in {"0", "false", "off", "no", "n"}:
                return False
            return default

        external_fallback_value = context.get("external_tool_fallback")
        if external_fallback_value is None:
            external_fallback_value = context.get("external_fallback")
        normalized_external_fallback = _context_bool(external_fallback_value, profile_external_fallback)
        context["external_tool_fallback"] = normalized_external_fallback
        context["external_fallback"] = normalized_external_fallback
        if str(context.get("tooling_mode") or "").strip().lower() in {"forge_first", "forge_only"}:
            context.setdefault("interpreter_hint", "forge_first")

        requested_mode = str(execution_mode or "auto").strip().lower()
        if requested_mode not in {"auto", "chat", "execute"}:
            requested_mode = "auto"
        preferred_mode = str(agentic_profile.get("execution_mode") or "").strip().lower()
        if requested_mode == "auto" and preferred_mode in {"auto", "chat", "execute"}:
            requested_mode = preferred_mode

        with self._lock:
            self._set_agent_selection_state(
                visible_agent,
                lane=str(selection.get("lane") or self._switchboard_default_lane()),
                child=str(selection.get("child") or selection.get("agent_name") or visible_agent.agent),
                agent_name=str(selection.get("agent_name") or visible_agent.agent),
                generated_instance_id=str(selection.get("generated_instance_id") or "") or None,
            )
            visible_agent.last_delegated_to = None
            visible_agent.last_delegated_class = None
            visible_agent.agentic_profile = dict(agentic_profile)
        current_selection = self._current_selection(visible_agent)
        self._emit_stream_event(
            event_sink,
            "quest_chat_started",
            agent_id=agent_id,
            agent=visible_agent.agent,
            lane=current_selection.get("lane"),
            child=current_selection.get("child"),
            execution_mode=requested_mode,
            explicit_selection=explicit_selection,
            tooling_mode=context.get("tooling_mode"),
        )

        def _finish(result: dict[str, Any]) -> dict[str, Any]:
            self._emit_stream_event(
                event_sink,
                "turn_result",
                result=dict(result),
                status=str(result.get("status") or "ok"),
                final=str(result.get("reply") or result.get("final") or ""),
                reply=str(result.get("reply") or result.get("final") or ""),
                lane=current_selection.get("lane"),
                child=current_selection.get("child"),
                delegated_to=result.get("delegated_to"),
                delegated_class=result.get("delegated_class"),
                generated_instance_id=result.get("generated_instance_id"),
            )
            return result

        delegation_plan = self._choose_delegation_plan(
            agent_obj=visible_agent,
            message=message,
            current_selection=current_selection,
            explicit_selection=explicit_selection,
            context=context,
        )
        mode_used = requested_mode

        try:
            if delegation_plan:
                delegated_runs: list[dict[str, Any]] = []
                for delegation in delegation_plan:
                    helper_agent_id = (
                        f"{agent_id}__delegate__{self._sanitize_name_fragment(str(delegation.get('lane') or 'delegate'))}"
                        f"__{self._sanitize_name_fragment(str(delegation.get('child') or 'agent'))}"
                    )
                    helper_agent = self.ensure_agent(helper_agent_id)
                    self._emit_stream_event(
                        event_sink,
                        "quest_delegation_started",
                        agent_id=agent_id,
                        delegated_agent_id=helper_agent_id,
                        lane=str(delegation.get("lane") or ""),
                        child=str(delegation.get("child") or ""),
                        source_task=message,
                    )
                    delegated_selection = self._resolve_switch_selection(
                        agent_obj=helper_agent,
                        lane=str(delegation.get("lane") or ""),
                        child=str(delegation.get("child") or ""),
                        source_task=message,
                        parent_agent_id=visible_agent.agent_id,
                        parent_lane=str(current_selection.get("lane") or "fat_agent"),
                        parent_agent_name=visible_agent.agent,
                    )
                    self._sync_agent_agent(helper_agent, str(delegated_selection.get("agent_name") or helper_agent.agent))
                    with self._lock:
                        helper_agent.parent_agent_id = agent_id
                        self._set_agent_selection_state(
                            helper_agent,
                            lane=str(delegated_selection.get("lane") or "jl_agent"),
                            child=str(delegated_selection.get("child") or delegated_selection.get("agent_name") or helper_agent.agent),
                            agent_name=str(delegated_selection.get("agent_name") or helper_agent.agent),
                            generated_instance_id=str(delegated_selection.get("generated_instance_id") or "") or None,
                        )

                    delegated_context = self._sharp_context(
                        {
                            **context,
                            "delegated_from": agent_id,
                            "switchboard_selection": delegated_selection,
                        },
                        mode="main_chat",
                    )
                    delegated_mode = str(
                        (context or {}).get("delegated_execution_mode")
                        or ("execute" if requested_mode in {"auto", "execute"} else "chat")
                    ).strip().lower()
                    if delegated_mode not in {"auto", "chat", "execute"}:
                        delegated_mode = "execute"
                    delegated_reply = ""
                    delegated_status = "ok"
                    delegated_executed = False
                    delegated_tool_trace_count = 0
                    session_run = getattr(helper_agent.session, "run", None)
                    if callable(session_run) and delegated_mode in {"auto", "execute"}:
                        delegated_context_mode = "main_chat_auto" if delegated_mode == "auto" else "main_chat_execute"
                        delegated_result = self._call_with_optional_event_sink(
                            session_run,
                            message,
                            context=self._sharp_context(
                                {
                                    **delegated_context,
                                    "switchboard_selection": delegated_selection,
                                },
                                mode=delegated_context_mode,
                            ),
                            event_sink=event_sink,
                        )
                        delegated_status = str((delegated_result or {}).get("status") or "ok")
                        delegated_reply = str(
                            (delegated_result or {}).get("final")
                            or (delegated_result or {}).get("reply")
                            or ""
                        )
                        delegated_tool_trace = (
                            (delegated_result or {}).get("tool_trace")
                            if isinstance((delegated_result or {}).get("tool_trace"), list)
                            else []
                        )
                        delegated_tool_trace_count = len(delegated_tool_trace)
                        delegated_executed = delegated_tool_trace_count > 0
                    else:
                        delegated_reply, _, _ = helper_agent.session.engine.generate_response(
                            message,
                            agent_name=helper_agent.agent,
                            context=delegated_context,
                        )
                    self._emit_stream_event(
                        event_sink,
                        "quest_delegation_result",
                        agent_id=agent_id,
                        delegated_agent_id=helper_agent_id,
                        delegated_selection=delegated_selection,
                        status=delegated_status,
                        executed=delegated_executed,
                        tool_trace_count=delegated_tool_trace_count,
                        reply=str(delegated_reply or ""),
                    )
                    delegated_runs.append(
                        {
                            "delegated_agent_id": helper_agent_id,
                            "selection": delegated_selection,
                            "status": delegated_status,
                            "executed": delegated_executed,
                            "tool_trace_count": delegated_tool_trace_count,
                            "reply": str(delegated_reply or ""),
                        }
                    )

                reply, telemetry, feedback = self._merge_delegated_bundle_reply(
                    parent_agent=visible_agent,
                    parent_message=message,
                    delegated_runs=delegated_runs,
                    context=context,
                )

                delegated_workers: list[dict[str, Any]] = []
                delegated_names: list[str] = []
                delegated_classes: list[str] = []
                for run in delegated_runs:
                    selection = run.get("selection") if isinstance(run.get("selection"), dict) else {}
                    worker_name = str(selection.get("agent_name") or selection.get("child") or "")
                    worker_class = str(selection.get("classification") or selection.get("lane") or "")
                    if worker_name:
                        delegated_names.append(worker_name)
                    if worker_class:
                        delegated_classes.append(worker_class)
                    delegated_workers.append(
                        {
                            "delegated_agent_id": run.get("delegated_agent_id"),
                            "lane": selection.get("lane"),
                            "child": selection.get("child"),
                            "agent_name": selection.get("agent_name"),
                            "classification": selection.get("classification") or selection.get("lane"),
                            "generated_instance_id": selection.get("generated_instance_id"),
                            "status": run.get("status"),
                            "executed": bool(run.get("executed")),
                            "tool_trace_count": int(run.get("tool_trace_count") or 0),
                        }
                    )

                primary_selection = (
                    delegated_runs[0].get("selection")
                    if delegated_runs and isinstance(delegated_runs[0].get("selection"), dict)
                    else {}
                )
                with self._lock:
                    if delegated_names:
                        visible_agent.last_delegated_to = delegated_names[0]
                    if delegated_classes:
                        visible_agent.last_delegated_class = (
                            delegated_classes[0] if len(set(delegated_classes)) == 1 and len(delegated_classes) == 1 else "multi"
                        )

                response = {
                    "status": "ok",
                    "agent_id": agent_id,
                    "agent": visible_agent.agent,
                    "mode_used": "chat",
                    "executed": any(bool(item.get("executed")) for item in delegated_runs),
                    "reply": reply,
                    "telemetry": telemetry,
                    "feedback": feedback,
                    "lane": current_selection.get("lane"),
                    "child": current_selection.get("child"),
                    "delegated_to": delegated_names[0] if len(delegated_names) == 1 else ", ".join(delegated_names),
                    "delegated_class": delegated_classes[0] if len(delegated_classes) == 1 else "multi",
                    "generated_instance_id": primary_selection.get("generated_instance_id"),
                    "delegated_workers": delegated_workers,
                    "delegation_count": len(delegated_workers),
                    "backend_mode": self._backend_status(),
                    "telemetry_summary": self._telemetry_summary(telemetry, visible_agent.session.engine),
                }
                return _finish(response)

            if mode_used in {"auto", "execute"}:
                context_mode = "main_chat_auto" if mode_used == "auto" else "main_chat_execute"
                result = self._call_with_optional_event_sink(
                    visible_agent.session.run,
                    message,
                    context=self._sharp_context(
                        {
                            **context,
                            "switchboard_selection": current_selection,
                        },
                        mode=context_mode,
                    ),
                    event_sink=event_sink,
                )
                response = self._session_result_response(
                    agent=visible_agent,
                    result=result,
                    mode_used=mode_used,
                    return_trace=return_trace,
                )
                auto_approve_actions = _context_bool(context.get("auto_approve_actions"), False)
                if response.get("status") == "confirmation_required" and auto_approve_actions:
                    auto_note = str(
                        context.get("auto_approve_note")
                        or "Auto-approved by ui_main_chat runtime policy."
                    ).strip()
                    try:
                        max_auto_raw = int(context.get("auto_approve_max", 3) or 3)
                    except (TypeError, ValueError):
                        max_auto_raw = 3
                    max_auto = max(1, min(max_auto_raw, 8))
                    attempts = 0
                    while response.get("status") == "confirmation_required" and attempts < max_auto:
                        pending = response.get("pending_action") if isinstance(response.get("pending_action"), dict) else {}
                        pending_id = str((pending or {}).get("id") or "").strip()
                        if not pending_id:
                            break
                        response = self.confirm_pending_action(
                            agent_id=agent_id,
                            pending_action_id=pending_id,
                            approved=True,
                            note=auto_note,
                            return_trace=return_trace,
                            event_sink=event_sink,
                        )
                        attempts += 1
                    if response.get("status") == "ok":
                        response["auto_approved"] = True
                        response["auto_approve_count"] = attempts
                if response.get("status") != "ok":
                    response["lane"] = current_selection.get("lane")
                    response["child"] = current_selection.get("child")
                    response["delegated_to"] = None
                    response["delegated_class"] = None
                    response["generated_instance_id"] = current_selection.get("generated_instance_id")
                    response["backend_mode"] = self._backend_status()
                    response["telemetry_summary"] = self._telemetry_summary({}, visible_agent.session.engine)
                    return _finish(response)

                final = str(response.get("reply") or "")
                looped = self._record_and_check_loop(visible_agent, final)
                if looped and allow_clone:
                    clone = self.clone_agent(agent_id, reason="execute_loop_detected")
                    if clone.get("status") == "ok":
                        clone_id = clone.get("agent_id")
                        cloned = self._agents.get(str(clone_id))
                        if cloned:
                            return self.chat(
                                clone_id,
                                message,
                                agent=cloned.agent,
                                lane=current_selection.get("lane"),
                                child=current_selection.get("child"),
                                context={**context, "continued_from": agent_id},
                                execution_mode=requested_mode,
                                return_trace=return_trace,
                                allow_clone=False,
                                event_sink=event_sink,
                            )
                response["lane"] = current_selection.get("lane")
                response["child"] = current_selection.get("child")
                response["delegated_to"] = None
                response["delegated_class"] = None
                response["generated_instance_id"] = current_selection.get("generated_instance_id")
                response["backend_mode"] = self._backend_status()
                response["telemetry_summary"] = self._telemetry_summary({}, visible_agent.session.engine)
                return _finish(response)

            rich_context = self._sharp_context({**context, "switchboard_selection": current_selection}, mode="main_chat")
            reply, telemetry, feedback = visible_agent.session.engine.generate_response(
                message,
                agent_name=visible_agent.agent,
                context=rich_context,
            )
            looped = self._record_and_check_loop(visible_agent, reply)
            if looped and allow_clone:
                clone = self.clone_agent(agent_id, reason="loop_detected")
                if clone.get("status") == "ok":
                    clone_id = clone.get("agent_id")
                    cloned = self._agents.get(str(clone_id))
                    if cloned:
                        return self.chat(
                            clone_id,
                            message,
                            agent=cloned.agent,
                            lane=current_selection.get("lane"),
                            child=current_selection.get("child"),
                            context={**context, "continued_from": agent_id},
                            execution_mode=requested_mode,
                            return_trace=return_trace,
                            allow_clone=False,
                            event_sink=event_sink,
                        )
            return _finish({
                "status": "ok",
                "agent_id": agent_id,
                "agent": visible_agent.agent,
                "mode_used": "chat",
                "executed": False,
                "reply": reply,
                "telemetry": telemetry,
                "feedback": feedback,
                "lane": current_selection.get("lane"),
                "child": current_selection.get("child"),
                "delegated_to": None,
                "delegated_class": None,
                "generated_instance_id": current_selection.get("generated_instance_id"),
                "backend_mode": self._backend_status(),
                "telemetry_summary": self._telemetry_summary(telemetry, visible_agent.session.engine),
            })
        except Exception as exc:
            visible_agent.failures += 1
            if allow_clone:
                clone = self.clone_agent(agent_id, reason=f"failure:{exc}")
                if clone.get("status") == "ok":
                    clone_id = clone.get("agent_id")
                    cloned = self._agents.get(str(clone_id))
                    if cloned:
                        return self.chat(
                            clone_id,
                            message,
                            agent=cloned.agent,
                            lane=current_selection.get("lane"),
                            child=current_selection.get("child"),
                            context={**context, "continued_from": agent_id},
                            execution_mode=requested_mode,
                            return_trace=return_trace,
                            allow_clone=False,
                            event_sink=event_sink,
                        )
            return _finish({
                "status": "error",
                "agent_id": agent_id,
                "mode_used": mode_used,
                "error": str(exc),
                "lane": current_selection.get("lane"),
                "child": current_selection.get("child"),
                "delegated_to": None,
                "delegated_class": None,
                "generated_instance_id": current_selection.get("generated_instance_id"),
                "backend_mode": self._backend_status(),
            })

    def confirm_pending_action(
        self,
        agent_id: str,
        pending_action_id: str,
        *,
        approved: bool,
        note: str = "",
        return_trace: bool = True,
        event_sink: Callable[[Dict[str, Any]], None] | None = None,
    ) -> dict[str, Any]:
        resolved_agent_id = str(agent_id or JL_FAT_AGENT_ID).strip() or JL_FAT_AGENT_ID
        agent = self.ensure_agent(resolved_agent_id)
        self._sync_agent_agent(agent, agent.agent)
        result = self._call_with_optional_event_sink(
            agent.session.confirm_pending_action,
            pending_action_id,
            approved=approved,
            note=note,
            event_sink=event_sink,
        )
        response = self._session_result_response(
            agent=agent,
            result=result,
            mode_used="auto",
            return_trace=return_trace,
        )
        if response.get("status") == "ok":
            reply = str(response.get("reply") or "")
            if reply:
                self._record_and_check_loop(agent, reply)
        return response

    def stream_chat(
        self,
        agent_id: str,
        message: str,
        agent: str | None = None,
        lane: str | None = None,
        child: str | None = None,
        new_instance: bool = False,
        context: dict[str, Any] | None = None,
        execution_mode: str = "auto",
        return_trace: bool = True,
        allow_clone: bool = True,
    ) -> Iterable[Dict[str, Any]]:
        queue: Queue[Dict[str, Any] | object] = Queue()
        sentinel = object()
        resolved_agent_id = str(agent_id or JL_FAT_AGENT_ID).strip() or JL_FAT_AGENT_ID
        resolved_agent = str(agent or "SparkByte").strip() or "SparkByte"

        def _sink(event: Dict[str, Any]) -> None:
            payload = dict(event) if isinstance(event, dict) else {"type": "event", "payload": event}
            payload.setdefault("agent_id", resolved_agent_id)
            payload.setdefault("agent", resolved_agent)
            queue.put(payload)

        def _worker() -> None:
            try:
                self.chat(
                    agent_id=resolved_agent_id,
                    message=message,
                    agent=resolved_agent,
                    lane=lane,
                    child=child,
                    new_instance=new_instance,
                    context=context,
                    execution_mode=execution_mode,
                    return_trace=return_trace,
                    allow_clone=allow_clone,
                    event_sink=_sink,
                )
            except Exception as exc:
                queue.put({"type": "error", "agent_id": resolved_agent_id, "error": str(exc)})
            finally:
                queue.put(sentinel)

        Thread(
            target=_worker,
            daemon=True,
            name=f"quest-stream-{self._sanitize_name_fragment(resolved_agent_id)[:24]}",
        ).start()
        while True:
            item = queue.get()
            if item is sentinel:
                break
            yield item

    def _session_result_response(
        self,
        *,
        agent: QuestAgent,
        result: dict[str, Any],
        mode_used: str,
        return_trace: bool,
    ) -> dict[str, Any]:
        status = str((result or {}).get("status") or "ok")
        tool_trace = list((result or {}).get("tool_trace") or [])
        reply = str((result or {}).get("reply") or (result or {}).get("final") or "")

        if status == "confirmation_required":
            response: dict[str, Any] = {
                "status": status,
                "agent_id": agent.agent_id,
                "agent": agent.agent,
                "mode_used": mode_used,
                "executed": False,
                "reply": reply,
                "pending_action": (result or {}).get("pending_action"),
            }
            if return_trace and tool_trace:
                response["tool_trace"] = tool_trace
            return response

        if status != "ok":
            response = {
                "status": "error",
                "agent_id": agent.agent_id,
                "agent": agent.agent,
                "mode_used": mode_used,
                "error": (result or {}).get("error") or "interpreter_error",
                "reply": reply,
            }
            if (result or {}).get("pending_action"):
                response["pending_action"] = (result or {}).get("pending_action")
            if return_trace and tool_trace:
                response["tool_trace"] = tool_trace
            return response

        response = {
            "status": "ok",
            "agent_id": agent.agent_id,
            "agent": agent.agent,
            "mode_used": mode_used,
            "executed": bool(tool_trace),
            "reply": reply,
            "result": result,
        }
        if return_trace:
            response["tool_trace"] = tool_trace
        else:
            trimmed = dict(result) if isinstance(result, dict) else {"final": reply}
            trimmed.pop("tool_trace", None)
            response["result"] = trimmed
        return response

    def _classify_message_mode(self, message: str, context: dict[str, Any] | None = None) -> str:
        ctx = context or {}
        forced = str(ctx.get("execution_mode", "")).strip().lower()
        if forced in {"chat", "execute"}:
            return forced

        text = str(message or "").strip()
        if not text:
            return "chat"
        low = text.lower()

        shell_starts = (
            "powershell ",
            "cmd ",
            "bash ",
            "python ",
            "py ",
            "mkdir ",
            "cd ",
            "dir ",
            "ls ",
        )
        if any(low.startswith(prefix) for prefix in shell_starts):
            return "execute"

        action_terms = (
            "create",
            "make",
            "write",
            "save",
            "put",
            "delete",
            "remove",
            "rename",
            "move",
            "run",
            "execute",
            "launch",
            "open",
            "build",
            "install",
            "fix",
        )
        scope_terms = (
            "file",
            "folder",
            "directory",
            "desktop",
            "documents",
            "downloads",
            "path",
            "command",
            "terminal",
            "shell",
            "tool",
            "mission",
            "script",
        )
        has_path = bool(re.search(r"[a-z]:\\", low)) or ("\\" in low) or ("/" in low)
        has_action = any(term in low for term in action_terms)
        has_scope = any(term in low for term in scope_terms) or has_path

        if has_action and has_scope:
            return "execute"
        if self._has_explicit_destructive_intent(low):
            return "execute"
        return "chat"

    def _has_explicit_destructive_intent(self, low: str) -> bool:
        destructive_terms = (
            "delete",
            "remove",
            "wipe",
            "reset",
            "truncate",
            "overwrite",
            "cleanup",
            "clean up",
        )
        target_terms = ("file", "folder", "directory", "path", "project", "repo", "code")
        has_destructive = any(term in low for term in destructive_terms)
        has_target = any(term in low for term in target_terms) or bool(
            re.search(r"[a-z]:\\", low)
        )
        return has_destructive and has_target

    def run_quest(
        self,
        agent_id: str,
        task: str,
        agent: str | None = None,
        allow_clone: bool = True,
    ) -> dict[str, Any]:
        resolved_agent_id = str(agent_id or JL_FAT_AGENT_ID)
        self.ensure_agent(resolved_agent_id, agent_name=agent or "SparkByte")
        return self._submit_agent_job(
            resolved_agent_id,
            "quest",
            {
                "agent_id": resolved_agent_id,
                "task": task,
                "agent": agent,
                "allow_clone": allow_clone,
            },
        )

    def _run_quest_impl(
        self,
        agent_id: str,
        task: str,
        agent: str | None = None,
        allow_clone: bool = True,
    ) -> dict[str, Any]:
        quest_agent = self.ensure_agent(agent_id, agent_name=agent or "SparkByte")
        self._activate_engine(quest_agent.session.engine)
        if agent and agent != quest_agent.agent:
            quest_agent.agent = agent
            try:
                quest_agent.session.engine.set_agent(agent)
            except Exception:
                pass
        try:
            result = quest_agent.session.run(
                task,
                context=self._sharp_context(
                    {"switchboard_selection": self._current_selection(quest_agent)},
                    mode="quest_task",
                ),
            )
            final = str(result.get("final", ""))
            looped = self._record_and_check_loop(quest_agent, final)
            if looped and allow_clone:
                clone = self.clone_agent(agent_id, reason="quest_loop_detected")
                if clone.get("status") == "ok":
                    clone_id = clone.get("agent_id")
                    return self.run_quest(clone_id, task, agent=agent, allow_clone=False)
            return {
                "status": "ok",
                "agent_id": agent_id,
                "agent": quest_agent.agent,
                "result": result,
            }
        except Exception as exc:
            quest_agent.failures += 1
            if allow_clone:
                clone = self.clone_agent(agent_id, reason=f"quest_failure:{exc}")
                if clone.get("status") == "ok":
                    clone_id = clone.get("agent_id")
                    return self.run_quest(clone_id, task, agent=agent, allow_clone=False)
            return {"status": "error", "agent_id": agent_id, "error": str(exc)}

    def run_mission(
        self,
        task: str,
        agent_id: str = JL_FAT_AGENT_ID,
        agent: str | None = None,
        dynamic_agent: bool = True,
        allow_clone: bool = True,
    ) -> dict[str, Any]:
        selected_agent = (agent or "").strip() or "SparkByte"
        selection_reason = "manual_agent"

        if dynamic_agent and not agent:
            selected = self._select_agent_for_task(task)
            selected_agent = selected["agent_name"]
            selection_reason = selected["reason"]

        self.register_agent(agent_id=agent_id, agent_name=selected_agent)
        result = self.run_quest(
            agent_id=agent_id,
            task=task,
            agent=selected_agent,
            allow_clone=allow_clone,
        )
        result["selected_agent"] = selected_agent
        result["selected_agent"] = selected_agent
        result["selection_reason"] = selection_reason
        result["dynamic_agent"] = bool(dynamic_agent and not agent)
        result["dynamic_agent"] = bool(dynamic_agent and not agent)
        return result

    def clone_agent(self, source_agent_id: str, reason: str = "") -> dict[str, Any]:
        clone_id: str | None = None
        clone_snapshot: dict[str, Any] | None = None
        with self._lock:
            source = self._agents.get(source_agent_id)
            if not source:
                return {"status": "error", "error": "source_not_found"}
            clone_id = f"{source_agent_id}__clone_{int(time.time() * 1000)}"
            clone_agent = source.agent
            clone_forge = source.forge.clone()
            clone_engine = JLEngineCore()
            self._activate_engine(clone_engine)
            try:
                clone_engine.set_agent(clone_agent)
            except Exception:
                pass
            self._clear_agent_memory(clone_engine, clone_agent)
            clone_session = InterpreterSession(
                engine=clone_engine,
                memory_forge=clone_forge,
                allow_unsafe_tools=None,
                allow_direct_action_fallback=_env_bool(
                    "JL_INTERPRETER_ALLOW_DIRECT_ACTION_FALLBACK",
                    False,
                ),
            )
            # Start cloned sessions with clean short-term interpreter history.
            clone_session.history = []
            clone_agent = QuestAgent(
                agent_id=clone_id,
                agent=clone_agent,
                session=clone_session,
                forge=clone_forge,
                parent_agent_id=source_agent_id,
                clone_generation=source.clone_generation + 1,
                loop_persistent=bool(source.loop_persistent),
                active_lane=source.active_lane,
                active_child=source.active_child,
                active_agent_name=source.active_agent_name,
                generated_children=dict(source.generated_children),
                last_generated_instance_id=source.last_generated_instance_id,
                last_delegated_to=source.last_delegated_to,
                last_delegated_class=source.last_delegated_class,
                agentic_profile=dict(source.agentic_profile),
            )
            self._apply_session_agentic_profile(clone_agent)
            self._agents[clone_id] = clone_agent
            clone_snapshot = self._agent_snapshot(clone_agent)
        if clone_agent.loop_persistent:
            self._ensure_agent_loop(str(clone_id))
        return {
            "status": "ok",
            "reason": reason,
            "source_agent_id": source_agent_id,
            "agent_id": clone_id,
            "agent": clone_snapshot,
        }

    def spawn_side_quest(
        self, parent_agent_id: str, task: str, agent: str | None = None
    ) -> dict[str, Any]:
        parent = self.ensure_agent(parent_agent_id, agent_name=agent or "SparkByte")
        side_id = f"{parent_agent_id}__side_{len(parent.side_quests) + 1}"
        self.register_agent(side_id, agent_name=agent or parent.agent, parent_agent_id=parent_agent_id)
        side_agent = self.ensure_agent(side_id, agent_name=agent or parent.agent)
        with self._lock:
            side_agent.active_lane = parent.active_lane
            side_agent.active_child = parent.active_child
            side_agent.active_agent_name = parent.active_agent_name
            side_agent.generated_children = dict(parent.generated_children)
            side_agent.last_generated_instance_id = parent.last_generated_instance_id
        with self._lock:
            parent.side_quests.append(side_id)
        result = self.run_quest(side_id, task, agent=agent or parent.agent)
        return {"status": "ok", "parent_agent_id": parent_agent_id, "side_agent_id": side_id, "result": result}

    def create_ram_tool(
        self, agent_id: str, name: str, code: str, description: str = ""
    ) -> dict[str, Any]:
        agent = self.ensure_agent(agent_id)
        return agent.forge.create_tool(name=name, code=code, description=description)

    def list_ram_tools(self, agent_id: str) -> dict[str, Any]:
        agent = self.ensure_agent(agent_id)
        return agent.forge.list_tools()

    def run_ram_tool(self, agent_id: str, name: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        agent = self.ensure_agent(agent_id)
        return agent.forge.run_tool(name=name, payload=payload or {})

    def delete_ram_tool(self, agent_id: str, name: str) -> dict[str, Any]:
        agent = self.ensure_agent(agent_id)
        return agent.forge.delete_tool(name)

    def promote_ram_tool(self, agent_id: str, name: str) -> dict[str, Any]:
        agent = self.ensure_agent(agent_id)
        return agent.forge.promote_tool(name)

    def list_agent_loops(self) -> list[dict[str, Any]]:
        with self._lock:
            agent_ids = list(self._agents.keys())
        return [self._loop_snapshot(agent_id) for agent_id in agent_ids]

    def get_agent_loop_status(self, agent_id: str) -> dict[str, Any]:
        resolved_agent_id = str(agent_id or "").strip()
        if not resolved_agent_id:
            return {"status": "error", "error": "agent_id_required"}
        return {"status": "ok", "loop": self._loop_snapshot(resolved_agent_id)}

    def start_agent_loop(self, agent_id: str, agent_name: str | None = None) -> dict[str, Any]:
        resolved_agent_id = str(agent_id or JL_FAT_AGENT_ID).strip() or JL_FAT_AGENT_ID
        self.ensure_agent(resolved_agent_id, agent_name=agent_name or "SparkByte")
        self._ensure_agent_loop(resolved_agent_id)
        return {"status": "ok", "agent_id": resolved_agent_id, "loop": self._loop_snapshot(resolved_agent_id)}

    def stop_agent_loop(self, agent_id: str) -> dict[str, Any]:
        resolved_agent_id = str(agent_id or JL_FAT_AGENT_ID).strip() or JL_FAT_AGENT_ID
        with self._lock:
            queue = self._agent_loop_queues.get(resolved_agent_id)
            thread = self._agent_loop_threads.get(resolved_agent_id)
        if queue is None or thread is None or not thread.is_alive():
            with self._lock:
                agent = self._agents.get(resolved_agent_id)
                if agent:
                    agent.loop_active = False
            return {"status": "ok", "agent_id": resolved_agent_id, "loop": self._loop_snapshot(resolved_agent_id)}

        stop_job = AgentLoopJob(kind="__stop__", payload={"agent_id": resolved_agent_id})
        queue.put(stop_job)
        stop_job.done.wait(timeout=self._loop_task_timeout_seconds)
        thread.join(timeout=1.0)
        return {"status": "ok", "agent_id": resolved_agent_id, "loop": self._loop_snapshot(resolved_agent_id)}

    def _set_agent_loop_persistent(self, agent_id: str, persistent: bool) -> None:
        with self._lock:
            agent = self._agents.get(str(agent_id or "").strip())
            if agent:
                agent.loop_persistent = bool(persistent)

    def _ensure_agent_loop(self, agent_id: str) -> None:
        worker: Thread | None = None
        with self._lock:
            existing = self._agent_loop_threads.get(agent_id)
            if existing and existing.is_alive():
                agent = self._agents.get(agent_id)
                if agent:
                    agent.loop_active = True
                return
            queue: Queue[AgentLoopJob] = Queue()
            safe_name = re.sub(r"[^a-zA-Z0-9_.-]+", "_", agent_id).strip("._-") or "agent"
            worker = Thread(
                target=self._agent_loop_worker,
                args=(agent_id,),
                daemon=True,
                name=f"fat-agent-loop-{safe_name[:40]}",
            )
            self._agent_loop_queues[agent_id] = queue
            self._agent_loop_threads[agent_id] = worker
            agent = self._agents.get(agent_id)
            if agent:
                agent.loop_active = True
        if worker is not None:
            worker.start()

    def _is_agent_loop_thread(self, agent_id: str) -> bool:
        with self._lock:
            worker = self._agent_loop_threads.get(agent_id)
        return bool(worker and worker.ident and worker.ident == current_thread().ident)

    def _submit_agent_job(self, agent_id: str, kind: str, payload: dict[str, Any]) -> dict[str, Any]:
        if self._is_agent_loop_thread(agent_id):
            return self._execute_agent_loop_job(agent_id, kind, payload)

        self._ensure_agent_loop(agent_id)
        with self._lock:
            queue = self._agent_loop_queues.get(agent_id)
        if queue is None:
            return {
                "status": "error",
                "agent_id": agent_id,
                "error": "agent_loop_unavailable",
                "job_kind": kind,
            }

        job = AgentLoopJob(kind=kind, payload=payload)
        queue.put(job)
        finished = job.done.wait(timeout=self._loop_task_timeout_seconds)
        if not finished:
            return {
                "status": "error",
                "agent_id": agent_id,
                "error": f"agent_loop_timeout:{kind}",
                "job_kind": kind,
            }
        if isinstance(job.result, dict):
            return job.result
        return {
            "status": "error",
            "agent_id": agent_id,
            "error": "agent_loop_no_result",
            "job_kind": kind,
        }

    def _agent_loop_worker(self, agent_id: str) -> None:
        while True:
            with self._lock:
                queue = self._agent_loop_queues.get(agent_id)
            if queue is None:
                return

            job = queue.get()
            try:
                result = self._execute_agent_loop_job(agent_id, job.kind, job.payload)
            except Exception as exc:
                result = {
                    "status": "error",
                    "agent_id": agent_id,
                    "error": str(exc),
                    "job_kind": job.kind,
                }

            with self._lock:
                agent = self._agents.get(agent_id)
                if agent:
                    agent.loop_turns += 1
                    agent.loop_last_job = job.kind
                    agent.loop_last_error = str(result.get("error")) if result.get("status") == "error" else None
                    agent.loop_active = job.kind != "__stop__"
                if job.kind == "__stop__":
                    self._agent_loop_threads.pop(agent_id, None)
                    self._agent_loop_queues.pop(agent_id, None)

            job.result = result
            job.done.set()
            queue.task_done()

            if job.kind == "__stop__":
                return

    def _execute_agent_loop_job(self, agent_id: str, kind: str, payload: dict[str, Any]) -> dict[str, Any]:
        if kind == "chat":
            return self._chat_impl(**payload)
        if kind == "quest":
            return self._run_quest_impl(**payload)
        if kind == "__stop__":
            return {"status": "ok", "agent_id": str(payload.get("agent_id") or agent_id), "loop_stopped": True}
        return {
            "status": "error",
            "agent_id": agent_id,
            "error": f"unsupported_loop_job:{kind}",
        }

    def _loop_snapshot(self, agent_id: str) -> dict[str, Any]:
        with self._lock:
            queue = self._agent_loop_queues.get(agent_id)
            thread = self._agent_loop_threads.get(agent_id)
            agent = self._agents.get(agent_id)
        queue_depth = 0
        if queue is not None:
            try:
                queue_depth = int(queue.qsize())
            except Exception:
                queue_depth = 0
        return {
            "agent_id": agent_id,
            "active": bool(thread and thread.is_alive()),
            "persistent": bool(agent.loop_persistent) if agent else False,
            "queue_depth": queue_depth,
            "thread_name": thread.name if thread else None,
            "turns": int(agent.loop_turns if agent else 0),
            "last_job": agent.loop_last_job if agent else None,
            "last_error": agent.loop_last_error if agent else None,
        }

    def _record_and_check_loop(self, agent: QuestAgent, reply: str) -> bool:
        reply_text = str(reply or "").strip()
        if not reply_text:
            return False

        h = _hash_text(reply_text)
        hash_history = agent.last_reply_hashes
        hash_history.append(h)
        if len(hash_history) > 4:
            del hash_history[:-4]

        normalized = " ".join(reply_text.lower().split())
        text_history = agent.last_reply_texts
        text_history.append(normalized)
        if len(text_history) > 4:
            del text_history[:-4]

        # Exact-repeat detector.
        if len(hash_history) >= 3 and hash_history[-1] == hash_history[-2] == hash_history[-3]:
            return True

        # Near-repeat detector to catch tiny punctuation/whitespace drift.
        if len(text_history) < 3:
            return False
        tail = text_history[-3:]
        a_b = SequenceMatcher(a=tail[0], b=tail[1]).ratio()
        b_c = SequenceMatcher(a=tail[1], b=tail[2]).ratio()
        a_c = SequenceMatcher(a=tail[0], b=tail[2]).ratio()
        return min(a_b, b_c, a_c) >= 0.97

    def _clear_agent_memory(self, engine: JLEngineCore, agent_name: str) -> None:
        memory = getattr(engine, "memory_system", None)
        if memory is None:
            return
        try:
            if hasattr(memory, "_save_agent") and hasattr(memory, "_default_agent"):
                memory._save_agent(agent_name, memory._default_agent())  # type: ignore[attr-defined]
                return
            if hasattr(memory, "agent_store") and isinstance(memory.agent_store, dict):  # type: ignore[attr-defined]
                memory.agent_store[agent_name] = {  # type: ignore[attr-defined]
                    "recent_interactions": [],
                    "mood": "neutral",
                    "notes": {},
                    "dynamic_state": {},
                }
        except Exception:
            return

    def _agent_profile_summary(self, agent: QuestAgent) -> dict[str, Any]:
        engine = getattr(agent.session, "engine", None)
        current_agent_data = (
            getattr(engine, "current_agent_data", {})
            if isinstance(getattr(engine, "current_agent_data", {}), dict)
            else {}
        )
        identity = (
            current_agent_data.get("identity")
            if isinstance(current_agent_data.get("identity"), dict)
            else {}
        )
        modular_summary = get_modular_agent_summary(current_agent_data)
        return {
            "name": str(identity.get("name") or agent.active_agent_name or agent.agent or "").strip(),
            "role": str(identity.get("role") or "").strip(),
            "description": str(identity.get("description") or "").strip(),
            "profile_type": "modular_fat_agent" if modular_summary else "classic_agent",
            "modular_summary": modular_summary,
        }

    def _agent_snapshot(self, agent: QuestAgent) -> dict[str, Any]:
        return {
            "agent_id": agent.agent_id,
            "agent": agent.agent,
            "parent_agent_id": agent.parent_agent_id,
            "active_lane": agent.active_lane,
            "active_child": agent.active_child,
            "active_agent_name": agent.active_agent_name,
            "generated_children": dict(agent.generated_children),
            "last_generated_instance_id": agent.last_generated_instance_id,
            "last_delegated_to": agent.last_delegated_to,
            "last_delegated_class": agent.last_delegated_class,
            "clone_generation": agent.clone_generation,
            "side_quests": list(agent.side_quests),
            "failures": agent.failures,
            "forge_tools": agent.forge.list_tools().get("tools", []),
            "created_at": agent.created_at,
            "pending_action": agent.session.get_pending_action() if hasattr(agent.session, "get_pending_action") else None,
            "loop": self._loop_snapshot(agent.agent_id),
            "profile": self._agent_profile_summary(agent),
            "agentic_profile": dict(agent.agentic_profile),
        }

    def _activate_engine(self, engine: JLEngineCore) -> None:
        self._apply_runtime_backend_mode()
        # Keep all JL Engine subsystems active for fat agents.
        try:
            if hasattr(engine, "disable_engine_core_test_mode"):
                engine.disable_engine_core_test_mode()
        except Exception:
            pass
        try:
            if hasattr(engine, "config") and hasattr(engine.config, "safety_on"):
                # Capability-first runtime for fat-agent execution.
                engine.config.safety_on = False
        except Exception:
            pass
        try:
            if hasattr(engine, "set_behavior_profile"):
                engine.set_behavior_profile("expressive")
        except Exception:
            pass
        for attr, value in (
            ("supervisor_enabled", True),
            ("supervisor_gating", False),
            ("supervisor_postprocess", False),
            ("emotional_sampling", True),
            ("backoff_mode", False),
        ):
            try:
                setattr(engine, attr, value)
            except Exception:
                pass

    def _sharp_context(self, context: dict[str, Any], mode: str) -> dict[str, Any]:
        merged = dict(context or {})
        merged.setdefault("quest_mode", mode)
        if mode == "main_chat_auto":
            merged.setdefault("task_intent", "chat_assist")
            merged.setdefault("action_type", "conversation")
            merged.setdefault("autonomous_toolsmith", True)
            merged.setdefault("tool_creation_mode", "dynamic_ram")
            merged.setdefault("respect_selected_agent", True)
            merged.setdefault(
                "execution_directive",
                "Answer directly when possible. Use tools only when they materially help the user.",
            )
        elif mode == "main_chat":
            merged.setdefault("task_intent", "conversation")
            merged.setdefault("action_type", "conversation")
            merged.setdefault("autonomous_toolsmith", False)
            merged.setdefault("tool_creation_mode", "dynamic_ram")
            merged.setdefault("respect_selected_agent", True)
            merged.setdefault(
                "execution_directive",
                "Reply conversationally. Do not force tool use unless explicitly requested elsewhere.",
            )
        elif mode == "main_chat_execute":
            merged.setdefault("task_intent", "quest_execution")
            merged.setdefault("action_type", "execution")
            merged.setdefault("autonomous_toolsmith", True)
            merged.setdefault("tool_creation_mode", "dynamic_ram")
            merged.setdefault("respect_selected_agent", True)
            merged.setdefault(
                "execution_directive",
                "Agent defines needed tools and execution strategy from task intent.",
            )
        else:
            merged.setdefault("task_intent", "quest_execution")
            merged.setdefault("action_type", "execution")
            merged.setdefault("autonomous_toolsmith", True)
            merged.setdefault("tool_creation_mode", "dynamic_ram")
            merged.setdefault(
                "execution_directive",
                "Agent defines needed tools and execution strategy from task intent.",
            )
        merged.setdefault(
            "jl_subsystems",
            {
                "behavior_engine": True,
                "rhythm_engine": True,
                "aperture": True,
                "drift_pressure": True,
                "supervisor": True,
                "memory": True,
                "temporal_projection": True,
            },
        )
        merged.setdefault("backend_mode", self._backend_status())
        return merged

    def _persist_agent(
        self,
        agent_name: str,
        payload: dict[str, Any],
        *,
        classification: str = "generated",
        default_backend_id: str = "ollama-local",
        default_memory_mode: str = "HYBRID",
        drive_type: str | None = None,
        registry_extra: dict[str, Any] | None = None,
        persist_registry: bool = True,
    ) -> Path:
        self._agents_dir.mkdir(parents=True, exist_ok=True)
        self._generated_agents_dir.mkdir(parents=True, exist_ok=True)
        safe_name = "".join(ch if ch.isalnum() or ch in ("-", "_") else "_" for ch in agent_name)
        safe_name = safe_name.strip("_") or "agent"
        jl_agent_file = f"{safe_name}.json"
        relative_jl_agent_file = f"generated/{jl_agent_file}"
        agent_path = self._generated_agents_dir / jl_agent_file
        agent_path.write_text(json.dumps(payload, indent=2, ensure_ascii=True), encoding="utf-8")

        registry_entry = {
            "jl_agent_file": relative_jl_agent_file,
            "default_memory_mode": default_memory_mode,
            "default_backend_id": default_backend_id,
            "drive_type": drive_type,
            "classification": classification,
            "tags": ((payload.get("identity") or {}).get("tags") or []),
        }
        if isinstance(registry_extra, dict):
            registry_entry.update(registry_extra)
        self._runtime_registry_entries[agent_name] = registry_entry
        if persist_registry:
            registry = self._load_registry(include_runtime=False)
            registry[agent_name] = registry_entry
            self._write_registry(registry)
        return agent_path

    def _load_registry(self, *, include_runtime: bool = True) -> dict[str, Any]:
        for path in self._registry_paths():
            if not path.exists():
                continue
            try:
                loaded = json.loads(path.read_text(encoding="utf-8-sig"))
                if isinstance(loaded, dict):
                    if include_runtime and self._runtime_registry_entries:
                        merged = dict(loaded)
                        merged.update(self._runtime_registry_entries)
                        return merged
                    return loaded
            except Exception:
                continue
        if include_runtime and self._runtime_registry_entries:
            return dict(self._runtime_registry_entries)
        return {}

    def _write_registry(self, registry: dict[str, Any]) -> None:
        payload = json.dumps(registry, indent=2, ensure_ascii=True)
        primary, alt = self._registry_paths()
        primary.parent.mkdir(parents=True, exist_ok=True)
        alt.parent.mkdir(parents=True, exist_ok=True)
        primary.write_text(payload, encoding="utf-8")
        alt.write_text(payload, encoding="utf-8")

    def _registry_paths(self) -> tuple[Path, Path]:
        primary = self._registry_path
        if str(primary).endswith(".json"):
            alt = Path(str(primary)[: -len(".json")])
        else:
            alt = Path(f"{primary}.json")
        return primary, alt

    def _select_agent_for_task(self, task: str) -> dict[str, str]:
        registry = self._load_registry()
        if not registry:
            return {"agent_name": "SparkByte", "reason": "registry_empty_default_sparkbyte"}

        task_text = str(task or "").strip().lower()
        if not task_text:
            default_name = "SparkByte" if "SparkByte" in registry else str(next(iter(registry.keys())))
            return {"agent_name": default_name, "reason": "empty_task_default_agent"}

        task_tokens = {tok for tok in re.split(r"[^a-z0-9]+", task_text) if tok}
        best_name = "SparkByte" if "SparkByte" in registry else str(next(iter(registry.keys())))
        best_score = -1
        best_hits: list[str] = []

        for agent_name, raw_entry in registry.items():
            entry = raw_entry if isinstance(raw_entry, dict) else {}
            score = 0
            hits: list[str] = []

            name_text = str(agent_name).lower()
            if f" {name_text} " in f" {task_text} ":
                score += 6
                hits.append(f"name:{agent_name}")

            for token in [tok for tok in re.split(r"[^a-z0-9]+", name_text) if tok]:
                if token in task_tokens and len(token) > 2:
                    score += 2
                    hits.append(f"name_token:{token}")

            tags = entry.get("tags")
            if isinstance(tags, list):
                for raw_tag in tags:
                    tag = str(raw_tag).strip().lower()
                    if not tag:
                        continue
                    if tag in task_tokens or f" {tag} " in f" {task_text} ":
                        score += 3
                        hits.append(f"tag:{tag}")

            drive_type = str(entry.get("drive_type") or "").strip().lower()
            if drive_type and (drive_type in task_tokens or f" {drive_type} " in f" {task_text} "):
                score += 2
                hits.append(f"drive:{drive_type}")

            if score > best_score:
                best_score = score
                best_name = str(agent_name)
                best_hits = hits

        if best_score <= 0:
            if "SparkByte" in registry:
                return {"agent_name": "SparkByte", "reason": "no_match_default_sparkbyte"}
            fallback = str(next(iter(registry.keys())))
            return {"agent_name": fallback, "reason": "no_match_default_first_registry"}

        reason = "task_match:" + ",".join(best_hits[:5]) if best_hits else "task_match_score"
        return {"agent_name": best_name, "reason": reason}
