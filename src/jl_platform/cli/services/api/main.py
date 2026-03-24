"""Licensed under the MIT License. See LICENSE.md."""

from __future__ import annotations

from contextlib import asynccontextmanager
import json
import os
import subprocess
import sys
import time
import logging
from threading import Event, Lock, Thread
from typing import Any, Dict, Optional
from pathlib import Path
from urllib.parse import urlparse

from fastapi import Body, FastAPI, HTTPException, Query
from fastapi.responses import StreamingResponse
from fastapi.staticfiles import StaticFiles

from jl_platform.core.engine import CoreEngine
from jl_platform.core.quest_runtime import FatQuestRuntime
from jl_platform.core.runtime.app import PlatformApp
from jl_platform.sdk.client import HOST_REGISTRY, resolve_host_name, start_app
from jl_platform.core.tools.builtin import register_core_tools
from jl_platform.core.tools.registry import ToolRegistry
from jl_platform.core.tools.cc import run_cc_command
from jl_platform.core.tools.shell import run_shell
from jl_platform.core.interpreter import InterpreterSession
from jl_platform.core.browser_bridge import BrowserBridgeManager
from jl_platform.controllers import backend_controller
from jl_platform.services.api.schemas import (
    AuditRequest,
    BackendSelectionRequest,
    BridgeRequest,
    CCRunRequest,
    ChatLoopStartRequest,
    ChatLoopStopRequest,
    ChatRequest,
    ForgeCreateRequest,
    ForgeDeleteRequest,
    ForgePromoteRequest,
    ForgeRunRequest,
    InterpreterRequest,
    JL_FAT_AGENT_ID,
    OllamaModelSelectionRequest,
    OpenAISettingsRequest,
    QuestAgentRegisterRequest,
    QuestAgentlizedAgentRequest,
    QuestBusinessAgentRequest,
    QuestCardAgentRequest,
    QuestChatConfirmRequest,
    QuestChatRequest,
    QuestCloneRequest,
    QuestLoopStartRequest,
    QuestLoopStopRequest,
    QuestMissionRequest,
    QuestMPFAgentAgentRequest,
    QuestMPFAgentRequest,
    QuestRunRequest,
    QuestSideQuestRequest,
    QuestSwitchRequest,
    QuestToolCreateRequest,
    QuestToolDeleteRequest,
    QuestToolRunRequest,
    RuntimeModeRequest,
    SelfEditLabRequest,
    SelfEditStartRequest,
    SelfEditStopRequest,
    ToolRequest,
    WorkspaceReviewRequest,
    WorkspaceSaveRequest,
)
from jl_engine_core.engine_core import JLEngineCore


@asynccontextmanager
async def _lifespan(_app: FastAPI):
    _autostart_self_edit_loop_on_boot()
    try:
        yield
    finally:
        _shutdown_background_loops()


app = FastAPI(title="JL Platform API", lifespan=_lifespan)
logger = logging.getLogger(__name__)
_HOST_APPS: Dict[str, PlatformApp] = {}
_QUEST_RUNTIME = FatQuestRuntime()
_UI_DIR = Path(__file__).resolve().parents[4] / "ui_web"
_UI_EASY_DIR = Path(__file__).resolve().parents[4] / "ui_easy"
_WORKSPACE_ROOT = Path(__file__).resolve().parents[4]
_REVIEW_ENGINE = JLEngineCore()
_BROWSER_BRIDGE = BrowserBridgeManager()
JL_FAT_AGENT_ID = "jl_fat_agent"
_SELF_EDIT_LOCK = Lock()
_SELF_EDIT_PROC: Optional[subprocess.Popen[Any]] = None
_SELF_EDIT_STARTED_AT: Optional[float] = None
_SELF_EDIT_LAST_CONFIG: Dict[str, Any] = {}
_CHAT_LOOP_LOCK = Lock()
_CHAT_LOOP_THREADS: Dict[str, Thread] = {}
_CHAT_LOOP_STOPS: Dict[str, Event] = {}
_CHAT_LOOP_STATE: Dict[str, Dict[str, Any]] = {}

if _UI_DIR.exists():
    app.mount("/ui", StaticFiles(directory=str(_UI_DIR), html=True), name="ui")
if _UI_EASY_DIR.exists():
    app.mount("/ui-easy", StaticFiles(directory=str(_UI_EASY_DIR), html=True), name="ui-easy")


def _env_bool(name: str, default: bool) -> bool:
    raw = str(os.getenv(name, "1" if default else "0")).strip().lower()
    return raw not in {"0", "false", "off", "no"}


def _env_float(name: str, default: float) -> float:
    raw = str(os.getenv(name, str(default))).strip()
    try:
        return float(raw)
    except (TypeError, ValueError):
        return float(default)


def _env_int(name: str, default: int) -> int:
    raw = str(os.getenv(name, str(default))).strip()
    try:
        return int(raw)
    except (TypeError, ValueError):
        return int(default)


def _platform_base_url() -> str:
    configured_url = str(os.getenv("JL_PLATFORM_API_URL", "") or "").strip()
    if not configured_url:
        host = str(os.getenv("JL_PLATFORM_HOST", "127.0.0.1") or "127.0.0.1").strip() or "127.0.0.1"
        port = str(os.getenv("JL_PLATFORM_PORT", "8000") or "8000").strip() or "8000"
        configured_url = f"http://{host}:{port}"
    if "://" not in configured_url:
        configured_url = f"http://{configured_url}"
    return configured_url.rstrip("/")


def _normalize_url(value: str | None) -> str:
    normalized = str(value or "").strip()
    if not normalized:
        return ""
    if "://" not in normalized:
        normalized = f"http://{normalized}"
    return normalized.rstrip("/")


def _is_loopback_browser_bridge_url(value: str | None) -> bool:
    normalized = _normalize_url(value)
    if not normalized:
        return False
    parsed = urlparse(normalized)
    host = str(parsed.hostname or "").strip().lower()
    path = str(parsed.path or "").rstrip("/")
    return host in {"127.0.0.1", "localhost"} and path == "/browser-bridge"


def _configure_browser_bridge_url() -> str:
    desired_url = f"{_platform_base_url()}/browser-bridge"
    current_url = _normalize_url(os.getenv("JL_BROWSER_BRIDGE_URL", ""))

    # Keep explicit non-local bridge targets intact, but make local loopback
    # bridge URLs follow the currently running JL Engine server.
    if not current_url or _is_loopback_browser_bridge_url(current_url):
        os.environ["JL_BROWSER_BRIDGE_URL"] = desired_url
        return desired_url

    os.environ["JL_BROWSER_BRIDGE_URL"] = current_url
    return current_url


def _resolve_agent_profile(
    *,
    agent_name: str | None = None,
    agent_alias: str | None = None,
    default: str = "SparkByte",
) -> str:
    selected = str(agent_name or agent_alias or default).strip()
    return selected or default


_VALID_EXECUTION_MODES = {"auto", "chat", "execute"}
_VALID_DELEGATED_EXECUTION_MODES = {"auto", "chat", "execute"}
_VALID_TOOLING_MODES = {"forge_first", "forge_only", "external_first", "external_only"}


def _as_bool(value: Any, default: bool) -> bool:
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


def _parse_bool_setting(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    lowered = str(value).strip().lower()
    if lowered in {"1", "true", "on", "yes", "y"}:
        return True
    if lowered in {"0", "false", "off", "no", "n"}:
        return False
    raise ValueError(f"invalid_boolean_value:{value}")


def _resolve_quest_execution_mode(requested: str | None) -> str:
    normalized = str(requested or "").strip().lower()
    if normalized in {"chat", "execute"}:
        return normalized
    if normalized == "auto":
        auto_mode = str(os.getenv("JL_API_AUTO_EXECUTION_MODE", "execute") or "execute").strip().lower()
        if auto_mode in _VALID_EXECUTION_MODES:
            return auto_mode
        return "execute"
    default_mode = str(os.getenv("JL_API_DEFAULT_QUEST_EXECUTION_MODE", "execute") or "execute").strip().lower()
    if default_mode in _VALID_EXECUTION_MODES:
        return default_mode
    return "execute"


def _with_agentic_defaults(context: dict[str, Any] | None, *, channel: str) -> dict[str, Any]:
    merged = dict(context or {})
    merged.setdefault("channel", channel)

    delegated_default = str(
        os.getenv("JL_API_DEFAULT_DELEGATED_EXECUTION_MODE", "execute") or "execute"
    ).strip().lower()
    if delegated_default not in _VALID_DELEGATED_EXECUTION_MODES:
        delegated_default = "execute"
    requested_delegated = merged.get("delegated_execution_mode")
    delegated_mode = str(requested_delegated or delegated_default).strip().lower()
    if delegated_mode not in _VALID_DELEGATED_EXECUTION_MODES:
        if requested_delegated is None:
            delegated_mode = delegated_default
        else:
            raise ValueError(f"invalid_delegated_execution_mode:{requested_delegated}")
    merged["delegated_execution_mode"] = delegated_mode

    tooling_default = str(os.getenv("JL_API_DEFAULT_TOOLING_MODE", "forge_first") or "forge_first").strip().lower()
    if tooling_default not in _VALID_TOOLING_MODES:
        tooling_default = "forge_first"
    requested_tooling = merged.get("tooling_mode")
    tooling_mode = str(requested_tooling or tooling_default).strip().lower()
    if tooling_mode not in _VALID_TOOLING_MODES:
        if requested_tooling is None:
            tooling_mode = tooling_default
        else:
            raise ValueError(f"invalid_tooling_mode:{requested_tooling}")
    merged["tooling_mode"] = tooling_mode

    fallback_value = merged.get("external_tool_fallback")
    if fallback_value is None:
        fallback_value = merged.get("external_fallback")
    if fallback_value is None:
        fallback_bool = True
    else:
        fallback_bool = _parse_bool_setting(fallback_value)
    merged["external_tool_fallback"] = fallback_bool
    merged["external_fallback"] = fallback_bool

    if tooling_mode in {"forge_first", "forge_only"}:
        merged.setdefault("interpreter_hint", "forge_first")

    return merged


def _sse_frame(event: Dict[str, Any]) -> str:
    event_type = str((event or {}).get("type") or "message")
    payload = json.dumps(event or {}, ensure_ascii=False, default=str)
    return f"event: {event_type}\ndata: {payload}\n\n"


def _chat_loop_status_snapshot(agent_id: str) -> dict[str, Any]:
    resolved = str(agent_id or JL_FAT_AGENT_ID).strip() or JL_FAT_AGENT_ID
    with _CHAT_LOOP_LOCK:
        state = dict(_CHAT_LOOP_STATE.get(resolved) or {})
        thread = _CHAT_LOOP_THREADS.get(resolved)
    running = bool(thread and thread.is_alive())
    if not state:
        state = {
            "agent_id": resolved,
            "running": False,
            "waiting_for_confirmation": False,
            "turns": 0,
            "last_status": None,
            "last_error": None,
            "last_reply": None,
            "started_at": None,
            "stopped_at": None,
            "config": {},
        }
    else:
        state["running"] = running
    return state


def _chat_loop_pending_action(agent_id: str, agent: str) -> dict[str, Any] | None:
    try:
        agent = _QUEST_RUNTIME.ensure_agent(agent_id, agent_name=agent)
        if hasattr(agent.session, "get_pending_action"):
            return agent.session.get_pending_action()
    except Exception:
        return None
    return None


def _chat_loop_worker(
    *,
    agent_id: str,
    agent: str,
    message: str,
    context: dict[str, Any],
    execution_mode: str,
    interval_seconds: float,
    max_iterations: int,
    return_trace: bool,
    stop_event: Event,
) -> None:
    logger.info("[ChatLoop] started agent_id=%s agent=%s", agent_id, agent)
    turns = 0
    while not stop_event.is_set():
        turns += 1
        run_started = time.time()
        result: dict[str, Any] = {}
        try:
            result = _QUEST_RUNTIME.chat(
                agent_id=agent_id,
                message=message,
                agent=agent,
                context=context,
                execution_mode=execution_mode,
                return_trace=return_trace,
            )
            reply_text = str(result.get("reply") or "")
            with _CHAT_LOOP_LOCK:
                state = _CHAT_LOOP_STATE.setdefault(agent_id, {})
                state["turns"] = int(turns)
                state["last_status"] = str(result.get("status") or "ok")
                state["last_error"] = result.get("error")
                state["last_reply"] = reply_text[-4000:] if reply_text else ""
                state["pending_action"] = result.get("pending_action")
                state["waiting_for_confirmation"] = False
                state["last_run_at"] = run_started
                state["last_duration_ms"] = round((time.time() - run_started) * 1000.0, 2)
            reply_preview = str(result.get("reply") or result.get("final") or "").strip().replace("\n", " ")
            if len(reply_preview) > 240:
                reply_preview = reply_preview[:240] + "..."
            logger.info(
                "[ChatLoop] agent_id=%s turn=%s status=%s reply=%s",
                agent_id,
                turns,
                str(result.get("status") or "ok"),
                reply_preview or "<empty>",
            )
        except Exception as exc:
            with _CHAT_LOOP_LOCK:
                state = _CHAT_LOOP_STATE.setdefault(agent_id, {})
                state["turns"] = int(turns)
                state["last_status"] = "error"
                state["last_error"] = str(exc)
                state["waiting_for_confirmation"] = False
                state["last_run_at"] = run_started
                state["last_duration_ms"] = round((time.time() - run_started) * 1000.0, 2)
            logger.exception("[ChatLoop] agent_id=%s turn=%s failed: %s", agent_id, turns, exc)

        if str(result.get("status") or "") == "confirmation_required":
            pending_summary = str((result.get("pending_action") or {}).get("summary") or "").strip()
            if pending_summary:
                logger.info("[ChatLoop] agent_id=%s waiting_for_confirmation=%s", agent_id, pending_summary)
            with _CHAT_LOOP_LOCK:
                state = _CHAT_LOOP_STATE.setdefault(agent_id, {})
                state["waiting_for_confirmation"] = True
            while not stop_event.is_set():
                pending = _chat_loop_pending_action(agent_id, agent)
                with _CHAT_LOOP_LOCK:
                    state = _CHAT_LOOP_STATE.setdefault(agent_id, {})
                    state["pending_action"] = pending
                    state["waiting_for_confirmation"] = pending is not None
                if pending is None:
                    break
                stop_event.wait(min(interval_seconds, 0.5))
            if stop_event.is_set():
                break
            stop_event.wait(interval_seconds)
            continue
        if max_iterations > 0 and turns >= max_iterations:
            logger.info("[ChatLoop] agent_id=%s reached max_iterations=%s", agent_id, max_iterations)
            break
        stop_event.wait(interval_seconds)

    with _CHAT_LOOP_LOCK:
        state = _CHAT_LOOP_STATE.setdefault(agent_id, {})
        state["running"] = False
        state["stopped_at"] = time.time()
        thread = _CHAT_LOOP_THREADS.get(agent_id)
        if thread and not thread.is_alive():
            _CHAT_LOOP_THREADS.pop(agent_id, None)
        _CHAT_LOOP_STOPS.pop(agent_id, None)
    logger.info("[ChatLoop] stopped agent_id=%s", agent_id)


def _start_chat_loop(payload: ChatLoopStartRequest) -> dict[str, Any]:
    agent_id = str(payload.agent_id or JL_FAT_AGENT_ID).strip() or JL_FAT_AGENT_ID
    agent = _resolve_agent_profile(agent_name=payload.agent, agent_alias=payload.agent)
    interval_seconds = float(payload.interval_seconds if payload.interval_seconds is not None else 3.0)
    interval_seconds = max(0.2, min(interval_seconds, 120.0))
    max_iterations = int(payload.max_iterations if payload.max_iterations is not None else 0)
    if max_iterations < 0:
        max_iterations = 0
    execution_mode = _resolve_quest_execution_mode(payload.execution_mode)
    message = str(payload.message or "").strip() or "Continue the conversation and keep momentum."
    try:
        context = _with_agentic_defaults(payload.context, channel="api_chat_loop")
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    context.setdefault("synthetic_turn", True)
    context.setdefault("suppress_memory_write", True)
    context.setdefault("suppress_feedback_log", True)
    context.setdefault("memory_origin", "chat_loop")

    if bool(payload.autostart_agent_loop if payload.autostart_agent_loop is not None else True):
        _QUEST_RUNTIME.start_agent_loop(agent_id=agent_id, agent_name=agent)
    else:
        _QUEST_RUNTIME.ensure_agent(agent_id, agent_name=agent)
    logger.info(
        "[ChatLoop] starting agent_id=%s agent=%s interval_seconds=%.2f max_iterations=%s",
        agent_id,
        agent,
        interval_seconds,
        max_iterations,
    )

    with _CHAT_LOOP_LOCK:
        existing = _CHAT_LOOP_THREADS.get(agent_id)
        if existing and existing.is_alive():
            status = _chat_loop_status_snapshot(agent_id)
            status["message"] = "already_running"
            return {"status": "ok", "loop": status}

        stop_event = Event()
        _CHAT_LOOP_STOPS[agent_id] = stop_event
        _CHAT_LOOP_STATE[agent_id] = {
            "agent_id": agent_id,
            "running": True,
            "waiting_for_confirmation": False,
            "turns": 0,
            "last_status": None,
            "last_error": None,
            "last_reply": None,
            "started_at": time.time(),
            "stopped_at": None,
            "config": {
                "agent": agent,
                "message": message,
                "context": context,
                "execution_mode": execution_mode,
                "interval_seconds": interval_seconds,
                "max_iterations": max_iterations,
                "return_trace": bool(payload.return_trace if payload.return_trace is not None else False),
            },
        }
        thread = Thread(
            target=_chat_loop_worker,
            kwargs={
                "agent_id": agent_id,
                "agent": agent,
                "message": message,
                "context": context,
                "execution_mode": execution_mode,
                "interval_seconds": interval_seconds,
                "max_iterations": max_iterations,
                "return_trace": bool(payload.return_trace if payload.return_trace is not None else False),
                "stop_event": stop_event,
            },
            daemon=True,
            name=f"chat-agent-loop-{agent_id[:40]}",
        )
        _CHAT_LOOP_THREADS[agent_id] = thread

    thread.start()
    return {"status": "ok", "loop": _chat_loop_status_snapshot(agent_id)}


def _stop_chat_loop(payload: ChatLoopStopRequest) -> dict[str, Any]:
    agent_id = str(payload.agent_id or JL_FAT_AGENT_ID).strip() or JL_FAT_AGENT_ID
    wait_seconds = float(payload.wait_seconds if payload.wait_seconds is not None else 6.0)
    wait_seconds = max(0.0, min(wait_seconds, 60.0))

    with _CHAT_LOOP_LOCK:
        stop_event = _CHAT_LOOP_STOPS.get(agent_id)
        thread = _CHAT_LOOP_THREADS.get(agent_id)

    if stop_event is not None:
        stop_event.set()
    if thread is not None:
        thread.join(timeout=wait_seconds)
    logger.info("[ChatLoop] stop requested agent_id=%s wait_seconds=%.2f", agent_id, wait_seconds)

    with _CHAT_LOOP_LOCK:
        thread_now = _CHAT_LOOP_THREADS.get(agent_id)
        if not thread_now or not thread_now.is_alive():
            _CHAT_LOOP_THREADS.pop(agent_id, None)
            _CHAT_LOOP_STOPS.pop(agent_id, None)
            state = _CHAT_LOOP_STATE.setdefault(agent_id, {"agent_id": agent_id})
            state["running"] = False
            state["stopped_at"] = time.time()

    return {"status": "ok", "loop": _chat_loop_status_snapshot(agent_id)}


@app.get("/")
def read_root():
    return {"status": "ok", "hosts": sorted(HOST_REGISTRY.keys())}


@app.get("/health")
def health():
    return {
        "status": "ok",
        "service": "jl_platform",
        "hosts": sorted(HOST_REGISTRY.keys()),
        "browser_bridge": _BROWSER_BRIDGE.status(),
        "runtime_mode": backend_controller.get_runtime_mode_status(),
    }


@app.get("/hosts")
def list_hosts():
    """Return available host adapters with simple labels."""
    hosts = []
    for name in sorted(HOST_REGISTRY.keys()):
        adapter_cls = HOST_REGISTRY[name]
        hosts.append({"id": name, "label": getattr(adapter_cls, "name", name)})
    return {"hosts": hosts}


@app.get("/settings/ollama")
def ollama_settings():
    return {
        "status": "ok",
        "backend_id": "ollama-local",
        "brain_backend_id": backend_controller.get_brain_backend_id(),
        "tool_backend_id": backend_controller.get_tool_backend_id(),
        "base_url": backend_controller.get_ollama_base_url(),
        "configured_model": backend_controller.get_ollama_configured_model(),
        "current_model": backend_controller.get_ollama_model(),
        "models": backend_controller.list_ollama_models(),
    }


@app.post("/settings/ollama/model")
def ollama_set_model(payload: OllamaModelSelectionRequest):
    requested = str(payload.model_name or "").strip()
    if not requested:
        raise HTTPException(status_code=400, detail="model_name_required")

    installed_models = backend_controller.list_ollama_models()
    if installed_models and requested not in {str(item.get("name") or "") for item in installed_models}:
        raise HTTPException(status_code=400, detail=f"model_not_installed:{requested}")

    try:
        result = backend_controller.set_ollama_model(requested, persist=True)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return {
        "status": "ok",
        "message": f"Ollama model set to {result['model_name']}",
        **result,
        "models": installed_models or backend_controller.list_ollama_models(),
    }


@app.get("/settings/openai")
def openai_settings():
    return {
        "status": "ok",
        "backend_id": "openai",
        "brain_backend_id": backend_controller.get_brain_backend_id(),
        "tool_backend_id": backend_controller.get_tool_backend_id(),
        "base_url": backend_controller.get_openai_base_url(),
        "current_model": backend_controller.get_openai_model(),
        "api_key_configured": backend_controller.has_openai_api_key(),
    }


@app.post("/settings/openai")
def openai_set_settings(payload: OpenAISettingsRequest):
    try:
        result = backend_controller.set_openai_config(
            api_key=payload.api_key,
            model_name=payload.model_name,
            base_url=payload.base_url,
            persist=True,
        )
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    return {
        "status": "ok",
        "message": "OpenAI settings saved",
        **result,
    }


@app.get("/settings/backends")
def backend_settings():
    return {
        "status": "ok",
        "brain_backend_id": backend_controller.get_brain_backend_id(),
        "tool_backend_id": backend_controller.get_tool_backend_id(),
        "runtime_mode": backend_controller.get_runtime_mode_status(),
        "backends": backend_controller.list_backends(),
    }


@app.post("/settings/backends/select")
def backend_select(payload: BackendSelectionRequest):
    try:
        result = backend_controller.set_active_backends(
            brain_backend_id=payload.brain_backend_id,
            tool_backend_id=payload.tool_backend_id,
            persist=True,
        )
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    return {
        "status": "ok",
        "message": "Backend selection updated",
        **result,
        "runtime_mode": backend_controller.get_runtime_mode_status(),
        "backends": backend_controller.list_backends(),
    }


@app.get("/settings/runtime-mode")
def runtime_mode_settings():
    return {
        "status": "ok",
        **backend_controller.get_runtime_mode_status(),
        "effective_model": backend_controller.get_effective_model_name(),
    }


@app.post("/settings/runtime-mode")
def runtime_mode_set(payload: RuntimeModeRequest):
    try:
        result = backend_controller.set_runtime_mode(str(payload.mode or "").strip(), persist=True)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {
        "status": "ok",
        "message": f"Runtime mode set to {result['configured_mode']}",
        **result,
        "effective_model": backend_controller.get_effective_model_name(),
    }


@app.post("/hosts/{host}/chat")
def host_chat(host: str, payload: ChatRequest):
    """
    Generic chat endpoint that routes through a host adapter + CoreEngine.
    """
    resolved_host = resolve_host_name(host)
    if resolved_host is None or resolved_host not in HOST_REGISTRY:
        raise HTTPException(status_code=404, detail="Unknown host")

    app_instance = _HOST_APPS.get(resolved_host)
    if app_instance is None:
        engine = CoreEngine()
        app_instance = start_app(host_name=resolved_host, config_path=None, engine=engine)
        _HOST_APPS[resolved_host] = app_instance
    context = payload.context or {}
    agent_profile = _resolve_agent_profile(agent_name=payload.agent, agent_alias=payload.agent)
    requested_agent = context.get("agent_id") if isinstance(context, dict) else None
    agent_id = str(requested_agent or f"api_{resolved_host}_{agent_profile.replace(' ', '_')}")
    existing_agents = getattr(app_instance.engine, "_engines", {})
    if agent_id not in existing_agents:
        app_instance.register_agent(agent_id, agent=agent_profile)
    events = payload.events or []
    result = app_instance.process_host(
        agent_id, text=payload.message, events=events, context=context
    )
    return {"host": resolved_host, "agent_id": agent_id, "result": result}


@app.post("/tools/py-exec")
def run_py_exec(payload: ToolRequest):
    registry = ToolRegistry()
    register_core_tools(registry)
    return registry.call("py_exec_stream", {"code": payload.code})


@app.post("/tools/audit")
def run_audit(payload: AuditRequest):
    registry = ToolRegistry()
    register_core_tools(registry)
    return registry.call(
        "audit_crosscheck",
        {
            "code": payload.code,
            "output": payload.output or "",
            "expected_output_sha256": payload.expected_output_sha256,
        },
    )


@app.post("/tools/forge/create")
def forge_create(payload: ForgeCreateRequest):
    registry = ToolRegistry()
    register_core_tools(registry)
    return registry.call(
        "forge_create",
        {"name": payload.name, "code": payload.code, "description": payload.description or ""},
    )


@app.get("/tools/forge/list")
def forge_list():
    registry = ToolRegistry()
    register_core_tools(registry)
    return registry.call("forge_list", {})


@app.post("/tools/forge/run")
def forge_run(payload: ForgeRunRequest):
    registry = ToolRegistry()
    register_core_tools(registry)
    return registry.call("forge_run", {"name": payload.name, "payload": payload.payload or {}})


@app.post("/tools/forge/delete")
def forge_delete(payload: ForgeDeleteRequest):
    registry = ToolRegistry()
    register_core_tools(registry)
    return registry.call("forge_delete", {"name": payload.name})


@app.post("/tools/forge/promote")
def forge_promote(payload: ForgePromoteRequest):
    registry = ToolRegistry()
    register_core_tools(registry)
    return registry.call("forge_promote", {"name": payload.name})


@app.post("/tools/forge/promote-last")
def forge_promote_last():
    registry = ToolRegistry()
    register_core_tools(registry)
    return registry.call("forge_promote_last", {})


@app.post("/tools/bridge")
def bridge(payload: BridgeRequest):
    registry = ToolRegistry()
    register_core_tools(registry)
    return registry.call("bridge_local", {"mode": payload.mode, "data": payload.data or {}})


@app.post("/browser-bridge")
def browser_bridge(payload: Optional[Dict[str, Any]] = Body(default=None)):
    return _BROWSER_BRIDGE.handle(payload or {})


@app.get("/browser/state")
def browser_state():
    return _BROWSER_BRIDGE.status()


@app.post("/browser/inspect")
def browser_inspect(payload: Optional[Dict[str, Any]] = Body(default=None)):
    return _BROWSER_BRIDGE.inspect(payload or {})


@app.post("/browser/action")
def browser_action(payload: Optional[Dict[str, Any]] = Body(default=None)):
    return _BROWSER_BRIDGE.action(payload or {})


@app.post("/browser/reset")
def browser_reset():
    _BROWSER_BRIDGE.shutdown()
    return _BROWSER_BRIDGE.status()


def run_cc_command_route(payload: CCRunRequest):
    command_payload = {
        "action": "run",
        "command": payload.command,
        "cwd": payload.cwd,
        "timeout": payload.timeout,
        "shell": payload.shell if payload.shell is not None else True,
    }
    return run_cc_command(command_payload)


@app.post("/tools/cc-run")
def cc_run(payload: CCRunRequest):
    return run_cc_command_route(payload)


@app.post("/tools/shell-run")
def shell_run(payload: CCRunRequest):
    return run_shell(
        {
            "command": payload.command,
            "cwd": payload.cwd,
            "timeout": payload.timeout,
            "shell": payload.shell if payload.shell is not None else True,
        }
    )


@app.get("/quest/agents")
def quest_list_agents():
    return {"status": "ok", "agents": _QUEST_RUNTIME.list_agents()}


@app.get("/quest/switchboard")
def quest_switchboard(agent_id: str = Query(default=JL_FAT_AGENT_ID)):
    return _QUEST_RUNTIME.get_switchboard(agent_id=agent_id or JL_FAT_AGENT_ID)


@app.get("/quest/loops")
def quest_list_loops():
    return {"status": "ok", "loops": _QUEST_RUNTIME.list_agent_loops()}


@app.get("/quest/loops/{agent_id}")
def quest_loop_status(agent_id: str):
    return _QUEST_RUNTIME.get_agent_loop_status(agent_id=agent_id)


@app.post("/quest/loops/start")
def quest_loop_start(payload: QuestLoopStartRequest):
    return _QUEST_RUNTIME.start_agent_loop(
        agent_id=payload.agent_id or JL_FAT_AGENT_ID,
        agent_name=_resolve_agent_profile(agent_name=payload.agent, agent_alias=payload.agent, default=""),
    )


@app.post("/quest/loops/stop")
def quest_loop_stop(payload: QuestLoopStopRequest):
    return _QUEST_RUNTIME.stop_agent_loop(
        agent_id=payload.agent_id or JL_FAT_AGENT_ID,
    )


@app.get("/chat-loop")
def chat_loop_list():
    with _CHAT_LOOP_LOCK:
        ids = sorted(set(_CHAT_LOOP_STATE.keys()) | set(_CHAT_LOOP_THREADS.keys()))
    return {"status": "ok", "loops": [_chat_loop_status_snapshot(agent_id) for agent_id in ids]}


@app.get("/chat-loop/{agent_id}")
def chat_loop_status(agent_id: str):
    return {"status": "ok", "loop": _chat_loop_status_snapshot(agent_id)}


@app.post("/chat-loop/start")
def chat_loop_start(payload: ChatLoopStartRequest):
    return _start_chat_loop(payload)


@app.post("/chat-loop/stop")
def chat_loop_stop(payload: ChatLoopStopRequest):
    return _stop_chat_loop(payload)


@app.get("/quest/agents/mpf")
def quest_list_mpf_agents():
    return {"status": "ok", "agents": _QUEST_RUNTIME.list_mpf_agents()}


@app.get("/quest/agents/profiles/mpf")
def quest_list_mpf_agent_profiles():
    profiles = _QUEST_RUNTIME.list_mpf_agents()
    return {"status": "ok", "agent_profiles": profiles, "agents": profiles, "personas": profiles}


@app.get("/quest/personas/mpf")
def quest_list_mpf_personas():
    profiles = _QUEST_RUNTIME.list_mpf_agents()
    return {"status": "ok", "agent_profiles": profiles, "agents": profiles, "personas": profiles}


@app.post("/quest/agents/register")
def quest_register_agent(payload: QuestAgentRegisterRequest):
    return _QUEST_RUNTIME.register_agent(
        agent_id=payload.agent_id or JL_FAT_AGENT_ID,
        agent_name=_resolve_agent_profile(agent_name=payload.agent, agent_alias=payload.agent),
    )


@app.post("/quest/agents/register-business")
def quest_register_business_agent(payload: QuestBusinessAgentRequest):
    return _QUEST_RUNTIME.register_business_agent(
        agent_id=payload.agent_id,
        name=payload.name,
        industry=payload.industry,
        voice=payload.voice,
        audience=payload.audience,
        values=payload.values,
        style=payload.style,
        abilities=payload.abilities,
        mission=payload.mission,
        products=payload.products,
        docs=payload.docs,
    )


@app.post("/quest/agents/register-card")
def quest_register_card_agent(payload: QuestCardAgentRequest):
    return _QUEST_RUNTIME.register_card_agent(agent_id=payload.agent_id, card_path=payload.card_path)


@app.post("/quest/agents/register-mpf")
def quest_register_mpf_agent(payload: QuestMPFAgentRequest):
    return _QUEST_RUNTIME.register_mpf_agent(agent_id=payload.agent_id, mpf_path=payload.mpf_path)


@app.post("/quest/agents/register-mpf-agent")
def quest_register_mpf_agent_agent(payload: QuestMPFAgentAgentRequest):
    return _QUEST_RUNTIME.register_mpf_agent_agent(
        agent_id=payload.agent_id,
        agent_name=str(payload.agent_name or payload.agent_name).strip(),
    )


@app.post("/quest/agents/register-agentlized")
def quest_register_agentlized_agent(payload: QuestAgentlizedAgentRequest):
    return _QUEST_RUNTIME.register_agentlized_agent(
        agent_id=payload.agent_id,
        name=payload.name,
        role=payload.role,
        description=payload.description,
        style=payload.style,
        directives=payload.directives,
    )


@app.post("/quest/switch")
def quest_switch(payload: QuestSwitchRequest):
    return _QUEST_RUNTIME.switch_agent(
        agent_id=payload.agent_id or JL_FAT_AGENT_ID,
        lane=str(payload.lane or "").strip(),
        child=str(payload.child or "").strip() or None,
        new_instance=bool(payload.new_instance if payload.new_instance is not None else False),
    )


@app.post("/quest/chat")
def quest_chat(payload: QuestChatRequest):
    try:
        context = _with_agentic_defaults(payload.context, channel="api_quest_chat")
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return _QUEST_RUNTIME.chat(
        agent_id=payload.agent_id or JL_FAT_AGENT_ID,
        message=payload.message,
        agent=_resolve_agent_profile(agent_name=payload.agent, agent_alias=payload.agent, default=""),
        lane=str(payload.lane or "").strip() or None,
        child=str(payload.child or "").strip() or None,
        new_instance=bool(payload.new_instance if payload.new_instance is not None else False),
        context=context,
        execution_mode=_resolve_quest_execution_mode(payload.execution_mode),
        return_trace=bool(payload.return_trace if payload.return_trace is not None else True),
    )


@app.post("/quest/chat/stream")
def quest_chat_stream(payload: QuestChatRequest):
    try:
        context = _with_agentic_defaults(payload.context, channel="api_quest_chat_stream")
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    execution_mode = _resolve_quest_execution_mode(payload.execution_mode)

    def _event_iterator():
        stream_runner = getattr(_QUEST_RUNTIME, "stream_chat", None)
        if callable(stream_runner):
            for event in stream_runner(
                agent_id=payload.agent_id or JL_FAT_AGENT_ID,
                message=payload.message,
                agent=_resolve_agent_profile(agent_name=payload.agent, agent_alias=payload.agent, default=""),
                lane=str(payload.lane or "").strip() or None,
                child=str(payload.child or "").strip() or None,
                new_instance=bool(payload.new_instance if payload.new_instance is not None else False),
                context=context,
                execution_mode=execution_mode,
                return_trace=bool(payload.return_trace if payload.return_trace is not None else True),
            ):
                frame_event = dict(event) if isinstance(event, dict) else {"type": "event", "payload": event}
                frame_event["agent_id"] = payload.agent_id or JL_FAT_AGENT_ID
                yield _sse_frame(frame_event)
            return

        try:
            result = _QUEST_RUNTIME.chat(
                agent_id=payload.agent_id or JL_FAT_AGENT_ID,
                message=payload.message,
                agent=_resolve_agent_profile(agent_name=payload.agent, agent_alias=payload.agent, default=""),
                lane=str(payload.lane or "").strip() or None,
                child=str(payload.child or "").strip() or None,
                new_instance=bool(payload.new_instance if payload.new_instance is not None else False),
                context=context,
                execution_mode=execution_mode,
                return_trace=bool(payload.return_trace if payload.return_trace is not None else True),
            )
        except Exception as exc:
            yield _sse_frame({"type": "error", "agent_id": payload.agent_id or JL_FAT_AGENT_ID, "error": str(exc)})
            return

        result = dict(result or {})
        result["agent_id"] = payload.agent_id or JL_FAT_AGENT_ID
        yield _sse_frame(
            {
                "type": "turn_result",
                "agent_id": payload.agent_id or JL_FAT_AGENT_ID,
                "result": result,
                "status": result.get("status"),
                "final": result.get("reply") or result.get("final") or "",
            }
        )

    return StreamingResponse(
        _event_iterator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


@app.post("/quest/chat/confirm")
def quest_chat_confirm(payload: QuestChatConfirmRequest):
    return _QUEST_RUNTIME.confirm_pending_action(
        agent_id=payload.agent_id or JL_FAT_AGENT_ID,
        pending_action_id=payload.pending_action_id,
        approved=bool(payload.approved),
        note=str(payload.note or ""),
        return_trace=bool(payload.return_trace if payload.return_trace is not None else True),
    )


@app.post("/quest/run")
def quest_run(payload: QuestRunRequest):
    return _QUEST_RUNTIME.run_quest(
        agent_id=payload.agent_id or JL_FAT_AGENT_ID,
        task=payload.task,
        agent=_resolve_agent_profile(agent_name=payload.agent, agent_alias=payload.agent, default=""),
    )


@app.post("/quest/mission")
def quest_mission(payload: QuestMissionRequest):
    dynamic_agent = payload.dynamic_agent
    if dynamic_agent is None:
        dynamic_agent = payload.dynamic_agent
    return _QUEST_RUNTIME.run_mission(
        task=payload.task,
        agent_id=payload.agent_id or JL_FAT_AGENT_ID,
        agent=_resolve_agent_profile(agent_name=payload.agent, agent_alias=payload.agent, default=""),
        dynamic_agent=bool(dynamic_agent if dynamic_agent is not None else True),
        allow_clone=bool(payload.allow_clone if payload.allow_clone is not None else True),
    )


@app.post("/quest/clone")
def quest_clone(payload: QuestCloneRequest):
    return _QUEST_RUNTIME.clone_agent(
        source_agent_id=payload.agent_id or JL_FAT_AGENT_ID,
        reason=payload.reason or "",
    )


@app.post("/quest/sidequest")
def quest_sidequest(payload: QuestSideQuestRequest):
    return _QUEST_RUNTIME.spawn_side_quest(
        parent_agent_id=payload.parent_agent_id,
        task=payload.task,
        agent=_resolve_agent_profile(agent_name=payload.agent, agent_alias=payload.agent, default=""),
    )


@app.get("/quest/tools/{agent_id}")
def quest_list_tools(agent_id: str):
    return _QUEST_RUNTIME.list_ram_tools(agent_id=agent_id)


@app.post("/quest/tools/create")
def quest_create_tool(payload: QuestToolCreateRequest):
    return _QUEST_RUNTIME.create_ram_tool(
        agent_id=payload.agent_id,
        name=payload.name,
        code=payload.code,
        description=payload.description or "",
    )


@app.post("/quest/tools/run")
def quest_run_tool(payload: QuestToolRunRequest):
    return _QUEST_RUNTIME.run_ram_tool(
        agent_id=payload.agent_id,
        name=payload.name,
        payload=payload.payload or {},
    )


@app.post("/quest/tools/delete")
def quest_delete_tool(payload: QuestToolDeleteRequest):
    return _QUEST_RUNTIME.delete_ram_tool(agent_id=payload.agent_id, name=payload.name)


@app.post("/quest/tools/promote")
def quest_promote_tool(payload: QuestToolDeleteRequest):
    return _QUEST_RUNTIME.promote_ram_tool(agent_id=payload.agent_id, name=payload.name)


_INTERPRETER_SESSIONS: Dict[str, InterpreterSession] = {}


@app.post("/interpreter/run")
def interpreter_run(payload: InterpreterRequest):
    sid = payload.session_id or "default"
    session = _INTERPRETER_SESSIONS.get(sid)
    if session is None:
        # Keep the interpreter aligned with local engine defaults and let
        # the local runtime execute direct actions by default.
        session = InterpreterSession(
            allow_unsafe_tools=None,
            allow_direct_action_fallback=_env_bool(
                "JL_INTERPRETER_ALLOW_DIRECT_ACTION_FALLBACK",
                False,
            ),
        )
        _INTERPRETER_SESSIONS[sid] = session
    result = session.run(payload.message)
    result["session_id"] = sid
    return result


@app.post("/interpreter/stream")
def interpreter_stream(payload: InterpreterRequest):
    sid = payload.session_id or "default"
    session = _INTERPRETER_SESSIONS.get(sid)
    if session is None:
        session = InterpreterSession(
            allow_unsafe_tools=None,
            allow_direct_action_fallback=_env_bool(
                "JL_INTERPRETER_ALLOW_DIRECT_ACTION_FALLBACK",
                False,
            ),
        )
        _INTERPRETER_SESSIONS[sid] = session

    def _event_iterator():
        stream_runner = getattr(session, "stream_run", None)
        if callable(stream_runner):
            for event in stream_runner(payload.message):
                frame_event = dict(event) if isinstance(event, dict) else {"type": "event", "payload": event}
                frame_event["session_id"] = sid
                yield _sse_frame(frame_event)
            return

        try:
            result = session.run(payload.message)
        except Exception as exc:
            yield _sse_frame({"type": "error", "session_id": sid, "error": str(exc)})
            return

        result = dict(result or {})
        result["session_id"] = sid
        yield _sse_frame(
            {
                "type": "turn_result",
                "session_id": sid,
                "result": result,
                "status": result.get("status"),
                "final": result.get("final") or result.get("reply") or "",
            }
        )

    return StreamingResponse(
        _event_iterator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


def _safe_workspace_path(raw_path: str | None) -> Path:
    rel = str(raw_path or ".").strip() or "."
    candidate = (_WORKSPACE_ROOT / rel).resolve()
    if candidate != _WORKSPACE_ROOT and _WORKSPACE_ROOT not in candidate.parents:
        raise HTTPException(status_code=400, detail="path_outside_workspace")
    return candidate


def _workspace_rel(path: Path) -> str:
    if path == _WORKSPACE_ROOT:
        return "."
    return path.relative_to(_WORKSPACE_ROOT).as_posix()


def _self_edit_lab_path(raw_lab_dir: str | None) -> Path:
    rel = str(raw_lab_dir or ".self_edit_lab").strip() or ".self_edit_lab"
    candidate = (_WORKSPACE_ROOT / rel).resolve()
    if candidate != _WORKSPACE_ROOT and _WORKSPACE_ROOT not in candidate.parents:
        raise HTTPException(status_code=400, detail="self_edit_lab_outside_workspace")
    return candidate


def _self_edit_script_path() -> Path:
    return (_WORKSPACE_ROOT / "tools" / "engine_self_edit_loop.py").resolve()


def _tail_file(path: Path, lines: int = 120, max_chars: int = 50000) -> str:
    if lines <= 0 or not path.exists() or not path.is_file():
        return ""
    try:
        content = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""
    sliced = "\n".join(content.splitlines()[-lines:])
    return sliced[-max_chars:]


def _self_edit_status(log_lines: int = 120) -> dict[str, Any]:
    global _SELF_EDIT_PROC, _SELF_EDIT_STARTED_AT
    with _SELF_EDIT_LOCK:
        proc = _SELF_EDIT_PROC
        started_at = _SELF_EDIT_STARTED_AT
        cfg = dict(_SELF_EDIT_LAST_CONFIG)
        if proc and proc.poll() is not None:
            proc = None
            started_at = _SELF_EDIT_STARTED_AT
            cfg = dict(_SELF_EDIT_LAST_CONFIG)
            _SELF_EDIT_PROC = None
            _SELF_EDIT_STARTED_AT = started_at

    lab_dir = _self_edit_lab_path(cfg.get("lab_dir"))
    control_file = lab_dir / "control.txt"
    shuttle_file = lab_dir / "SHUTTLE"
    log_file = lab_dir / "loop.log"
    running = bool(proc and proc.poll() is None)
    returncode = None if running else (proc.poll() if proc else None)
    control_text = ""
    if control_file.exists():
        control_text = control_file.read_text(encoding="utf-8", errors="replace")
    return {
        "status": "ok",
        "running": running,
        "pid": proc.pid if running and proc else None,
        "returncode": returncode,
        "started_at": started_at,
        "config": cfg,
        "lab_dir": _workspace_rel(lab_dir) if lab_dir.exists() else str(lab_dir),
        "paths": {
            "lab_dir": str(lab_dir),
            "copy_dir": str(lab_dir / "engine_copy"),
            "venv_dir": str(lab_dir / ".venv"),
            "control_file": str(control_file),
            "shuttle_file": str(shuttle_file),
            "log_file": str(log_file),
        },
        "shuttle_present": shuttle_file.exists(),
        "control_text": control_text[-8000:],
        "log_tail": _tail_file(log_file, lines=max(0, min(int(log_lines), 4000))),
        "script_exists": _self_edit_script_path().exists(),
    }


@app.get("/self-edit/status")
def self_edit_status(log_lines: int = Query(default=120, ge=0, le=4000)):
    return _self_edit_status(log_lines=log_lines)


@app.post("/self-edit/start")
def self_edit_start(payload: SelfEditStartRequest):
    global _SELF_EDIT_PROC, _SELF_EDIT_STARTED_AT, _SELF_EDIT_LAST_CONFIG
    script_path = _self_edit_script_path()
    if not script_path.exists():
        raise HTTPException(status_code=404, detail=f"self_edit_script_missing:{script_path}")

    interval = float(payload.interval_seconds if payload.interval_seconds is not None else 3.0)
    interval = max(1.0, min(interval, 30.0))
    max_iterations = int(payload.max_iterations if payload.max_iterations is not None else 0)
    if max_iterations < 0:
        max_iterations = 0
    lab_dir = _self_edit_lab_path(payload.lab_dir)
    lab_dir.mkdir(parents=True, exist_ok=True)
    shuttle_file = lab_dir / "SHUTTLE"
    if shuttle_file.exists():
        shuttle_file.unlink()

    already_running = False
    with _SELF_EDIT_LOCK:
        existing = _SELF_EDIT_PROC
        if existing and existing.poll() is None:
            already_running = True
        else:
            cmd: list[str] = [
                sys.executable,
                str(script_path),
                "--lab-dir",
                _workspace_rel(lab_dir),
                "--interval-seconds",
                str(interval),
                "--max-iterations",
                str(max_iterations),
            ]
            if bool(payload.reseed_copy):
                cmd.append("--reseed-copy")

            creationflags = 0
            if os.name == "nt" and hasattr(subprocess, "CREATE_NEW_CONSOLE"):
                creationflags = subprocess.CREATE_NEW_CONSOLE

            proc = subprocess.Popen(
                cmd,
                cwd=str(_WORKSPACE_ROOT),
                shell=False,
                env=dict(os.environ),
                creationflags=creationflags,
            )
            _SELF_EDIT_PROC = proc
            _SELF_EDIT_STARTED_AT = time.time()
            _SELF_EDIT_LAST_CONFIG = {
                "lab_dir": _workspace_rel(lab_dir),
                "interval_seconds": interval,
                "max_iterations": max_iterations,
                "reseed_copy": bool(payload.reseed_copy),
                "command": cmd,
            }
            logger.info(
                "[SelfEdit] started pid=%s lab_dir=%s log_file=%s visible_console=%s",
                proc.pid,
                _workspace_rel(lab_dir),
                str(lab_dir / "loop.log"),
                bool(creationflags),
            )

    if already_running:
        status = _self_edit_status(log_lines=120)
        status["message"] = "already_running"
        return status

    time.sleep(0.1)
    return _self_edit_status(log_lines=120)


@app.post("/self-edit/stop")
def self_edit_stop(payload: SelfEditStopRequest):
    global _SELF_EDIT_PROC
    status_before = _self_edit_status(log_lines=int(payload.log_lines or 120))
    lab_dir = _self_edit_lab_path(payload.lab_dir or status_before.get("lab_dir"))
    lab_dir.mkdir(parents=True, exist_ok=True)
    shuttle_file = lab_dir / "SHUTTLE"
    shuttle_file.write_text("shuttle\n", encoding="utf-8")

    wait_seconds = float(payload.wait_seconds if payload.wait_seconds is not None else 6.0)
    wait_seconds = max(0.0, min(wait_seconds, 60.0))
    deadline = time.time() + wait_seconds

    proc: Optional[subprocess.Popen[Any]]
    with _SELF_EDIT_LOCK:
        proc = _SELF_EDIT_PROC
    while proc and proc.poll() is None and time.time() < deadline:
        time.sleep(0.2)

    force = bool(payload.force)
    if proc and proc.poll() is None and force:
        try:
            proc.terminate()
        except Exception as exc:
            logger.warning("Self-edit terminate failed: %s", exc)
        time.sleep(0.4)
    if proc and proc.poll() is None and force:
        try:
            proc.kill()
        except Exception as exc:
            logger.warning("Self-edit kill failed: %s", exc)

    with _SELF_EDIT_LOCK:
        current = _SELF_EDIT_PROC
        if current and current.poll() is not None:
            _SELF_EDIT_PROC = None
    return _self_edit_status(log_lines=int(payload.log_lines or 120))


@app.post("/self-edit/shuttle/clear")
def self_edit_clear_shuttle(payload: SelfEditLabRequest):
    status_before = _self_edit_status(log_lines=40)
    lab_dir = _self_edit_lab_path(payload.lab_dir or status_before.get("lab_dir"))
    shuttle_file = lab_dir / "SHUTTLE"
    if shuttle_file.exists():
        shuttle_file.unlink()
    control_file = lab_dir / "control.txt"
    if control_file.exists():
        lines = control_file.read_text(encoding="utf-8", errors="replace").splitlines()
        filtered = [
            line
            for line in lines
            if line.strip().lower() not in {"shuttle", "stop=shuttle", "command:shuttle"}
        ]
        control_file.write_text("\n".join(filtered).strip() + ("\n" if filtered else ""), encoding="utf-8")
    return _self_edit_status(log_lines=120)


def _autostart_self_edit_loop_on_boot():
    _configure_browser_bridge_url()
    if not _env_bool("JL_SELF_EDIT_AUTOSTART", False):
        return
    lab_dir = str(os.getenv("JL_SELF_EDIT_LAB_DIR", ".self_edit_lab")).strip() or ".self_edit_lab"
    if _env_bool("JL_SELF_EDIT_AUTOSTART_CLEAR_SHUTTLE", True):
        try:
            self_edit_clear_shuttle(SelfEditLabRequest(lab_dir=lab_dir))
        except Exception as exc:
            logger.warning("Self-edit shuttle clear during startup failed: %s", exc)
    try:
        self_edit_start(
            SelfEditStartRequest(
                lab_dir=lab_dir,
                interval_seconds=_env_float("JL_SELF_EDIT_INTERVAL", 3.0),
                max_iterations=_env_int("JL_SELF_EDIT_MAX_ITERATIONS", 0),
                reseed_copy=_env_bool("JL_SELF_EDIT_RESEED", False),
            )
        )
    except Exception:
        # Never block API boot if loop launch fails.
        logger.exception("Self-edit autostart failed")


def _shutdown_background_loops():
    _BROWSER_BRIDGE.shutdown()
    # Keep local servers clean on exit/restart.
    try:
        self_edit_stop(SelfEditStopRequest(wait_seconds=1.0, force=True, log_lines=20))
    except Exception:
        logger.debug("Self-edit shutdown cleanup skipped.", exc_info=True)

    with _CHAT_LOOP_LOCK:
        loop_ids = list(_CHAT_LOOP_STOPS.keys())
        events = {agent_id: _CHAT_LOOP_STOPS.get(agent_id) for agent_id in loop_ids}
        threads = {agent_id: _CHAT_LOOP_THREADS.get(agent_id) for agent_id in loop_ids}

    for event in events.values():
        if event is not None:
            event.set()
    for thread in threads.values():
        if thread is not None:
            thread.join(timeout=1.0)

    with _CHAT_LOOP_LOCK:
        for agent_id in loop_ids:
            state = _CHAT_LOOP_STATE.setdefault(agent_id, {"agent_id": agent_id})
            state["running"] = False
            state["stopped_at"] = time.time()
            state["last_status"] = state.get("last_status") or "stopped"
        _CHAT_LOOP_THREADS.clear()
        _CHAT_LOOP_STOPS.clear()


@app.get("/workspace/list")
def workspace_list(path: str = Query(default="."), show_hidden: bool = Query(default=False)):
    base = _safe_workspace_path(path)
    if not base.exists():
        raise HTTPException(status_code=404, detail="path_not_found")
    if not base.is_dir():
        raise HTTPException(status_code=400, detail="path_is_not_directory")

    entries: list[dict[str, Any]] = []
    for child in sorted(base.iterdir(), key=lambda item: (not item.is_dir(), item.name.lower())):
        name = child.name
        if not show_hidden and name.startswith("."):
            continue
        if name == "__pycache__":
            continue
        try:
            size = child.stat().st_size if child.is_file() else None
        except OSError:
            size = None
        entries.append(
            {
                "name": name,
                "path": _workspace_rel(child),
                "is_dir": child.is_dir(),
                "size": size,
            }
        )
        if len(entries) >= 800:
            break

    parent_path = "."
    if base != _WORKSPACE_ROOT:
        parent_path = _workspace_rel(base.parent)

    return {
        "status": "ok",
        "path": _workspace_rel(base),
        "parent_path": parent_path,
        "entries": entries,
    }


@app.get("/workspace/file")
def workspace_file(path: str = Query(...), max_chars: int = Query(default=200000, ge=1000, le=1000000)):
    target = _safe_workspace_path(path)
    if not target.exists():
        raise HTTPException(status_code=404, detail="path_not_found")
    if not target.is_file():
        raise HTTPException(status_code=400, detail="path_is_not_file")

    raw = target.read_bytes()
    if b"\x00" in raw:
        raise HTTPException(status_code=400, detail="binary_file_not_supported")

    text = raw.decode("utf-8", errors="replace")
    clipped = text[:max_chars]
    return {
        "status": "ok",
        "path": _workspace_rel(target),
        "total_chars": len(text),
        "returned_chars": len(clipped),
        "truncated": len(text) > len(clipped),
        "content": clipped,
    }


@app.post("/workspace/file/save")
def workspace_file_save(payload: WorkspaceSaveRequest):
    target = _safe_workspace_path(payload.path)
    if target.exists() and not target.is_file():
        raise HTTPException(status_code=400, detail="path_is_not_file")
    if not target.parent.exists():
        raise HTTPException(status_code=400, detail="parent_directory_missing")
    target.write_text(payload.content, encoding="utf-8")
    return {
        "status": "ok",
        "path": _workspace_rel(target),
        "saved_chars": len(payload.content or ""),
    }


def _fallback_review(path: str, content: str) -> str:
    lines = content.splitlines()
    findings: list[str] = []
    for idx, line in enumerate(lines, start=1):
        l = line.lower()
        if "todo" in l or "fixme" in l:
            findings.append(f"- medium [{idx}] leftover todo/fixme marker.")
        if "except:" in l:
            findings.append(f"- high [{idx}] bare except can hide failures.")
        if "shell=true" in l:
            findings.append(f"- high [{idx}] shell=true usage can be risky.")
        if "eval(" in l or "exec(" in l:
            findings.append(f"- high [{idx}] dynamic eval/exec detected.")
        if len(findings) >= 10:
            break
    if not findings:
        findings.append("- no obvious static red flags detected in quick fallback pass.")
    return "\n".join([f"File: {path}", *findings])


@app.post("/workspace/review")
def workspace_review(payload: WorkspaceReviewRequest):
    target = _safe_workspace_path(payload.path)
    if not target.exists():
        raise HTTPException(status_code=404, detail="path_not_found")
    if not target.is_file():
        raise HTTPException(status_code=400, detail="path_is_not_file")

    text = target.read_text(encoding="utf-8", errors="replace")
    max_chars = int(payload.max_chars or 20000)
    snippet = text[:max(1000, min(max_chars, 100000))]
    rel = _workspace_rel(target)
    focus = str(payload.focus or "").strip() or "bugs, regressions, missing tests"
    review_prompt = (
        "Review this source file for practical engineering quality.\n"
        "Return concise findings first, ordered by severity, with line references.\n"
        "Then list assumptions briefly.\n"
        f"Focus: {focus}\n"
        f"Path: {rel}\n\n"
        f"{snippet}"
    )

    try:
        reply, telemetry, _feedback = _REVIEW_ENGINE.generate_response(
            user_message=review_prompt,
            agent_name="SparkByte",
            context={
                "task_intent": "code_review",
                "action_type": "review",
                "workspace_path": rel,
            },
        )
        return {
            "status": "ok",
            "path": rel,
            "focus": focus,
            "review": reply,
            "fallback": False,
            "telemetry": telemetry,
        }
    except Exception:
        return {
            "status": "ok",
            "path": rel,
            "focus": focus,
            "review": _fallback_review(rel, snippet),
            "fallback": True,
        }
