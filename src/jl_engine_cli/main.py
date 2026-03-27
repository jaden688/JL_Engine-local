"""Licensed under the Apache License, Version 2.0. See LICENSE.md and NOTICE."""

from __future__ import annotations

import argparse
import importlib
import json
import logging
import os
import re
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
import webbrowser
from pathlib import Path
from typing import Any, Dict, Optional

from jl_engine_core import __version__
from jl_engine_core.config_loader import load_config
from jl_engine_core.engine_core import EngineConfig, JLEngineCore

try:
    import msvcrt
except ImportError:
    msvcrt = None


def _merge_config_overrides(overrides: Dict[str, Any]) -> EngineConfig:
    cfg = EngineConfig()
    if not overrides:
        return cfg
    for key, value in overrides.items():
        if hasattr(cfg, key):
            setattr(cfg, key, value)
    return cfg


def _build_engine(config_path: str | None) -> JLEngineCore:
    overrides = load_config(config_path) if config_path else {}
    return JLEngineCore(_merge_config_overrides(overrides))


def _env_flag(name: str, default: bool = False) -> bool:
    raw = str(os.getenv(name, "1" if default else "0")).strip().lower()
    return raw in {"1", "true", "yes", "on"}


def _standard_ui_path(raw: str | None) -> str:
    value = str(raw or "/ui/").strip() or "/ui/"
    if not value.startswith("/"):
        value = f"/{value}"
    return value.rstrip("/") or "/ui"


def _platform_urls(host: str, port: int, ui_path: str) -> tuple[str, str, str]:
    normalized_ui_path = _standard_ui_path(ui_path)
    base_url = f"http://{host}:{int(port)}"
    return base_url, f"{base_url}/health", f"{base_url}{normalized_ui_path}"


def _default_platform_port() -> int:
    try:
        return int(str(os.getenv("JL_PLATFORM_PORT") or "8000"))
    except (TypeError, ValueError):
        return 8000


def _default_startup_timeout() -> float:
    try:
        return float(str(os.getenv("JL_PLATFORM_STARTUP_TIMEOUT_SECONDS") or "30"))
    except (TypeError, ValueError):
        return 30.0


def _default_launch_mode() -> str:
    value = str(os.getenv("JL_PLATFORM_LAUNCH_MODE") or "standalone").strip().lower()
    return value if value in {"standalone", "browser"} else "standalone"


def _standalone_browser_candidates() -> list[str]:
    if os.name != "nt":
        return []
    candidates = [
        os.path.join(os.getenv("ProgramFiles(x86)", ""), "Microsoft", "Edge", "Application", "msedge.exe"),
        os.path.join(os.getenv("ProgramFiles", ""), "Microsoft", "Edge", "Application", "msedge.exe"),
        os.path.join(os.getenv("ProgramFiles", ""), "Google", "Chrome", "Application", "chrome.exe"),
        os.path.join(os.getenv("ProgramFiles(x86)", ""), "Google", "Chrome", "Application", "chrome.exe"),
    ]
    return [candidate for candidate in candidates if candidate and Path(candidate).exists()]


def _open_platform_ui(url: str, *, launch_mode: str) -> None:
    normalized_mode = str(launch_mode or "browser").strip().lower()
    if normalized_mode == "standalone":
        for browser_path in _standalone_browser_candidates():
            try:
                subprocess.Popen([browser_path, f"--app={url}"])
                return
            except Exception:
                continue
    webbrowser.open(url)


def _open_platform_ui_when_ready(
    *,
    health_url: str,
    ui_url: str,
    startup_timeout: float,
    launch_mode: str,
) -> None:
    timeout_seconds = max(5.0, float(startup_timeout))

    def _wait_then_open() -> None:
        deadline = time.time() + timeout_seconds
        while time.time() < deadline:
            try:
                with urllib.request.urlopen(health_url, timeout=2):
                    break
            except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, ValueError):
                time.sleep(0.5)
        _open_platform_ui(ui_url, launch_mode=launch_mode)

    threading.Thread(target=_wait_then_open, name="jl-engine-ui-open", daemon=True).start()


def _launch_platform_api(
    *,
    host: str,
    port: int,
    ui_path: str,
    open_browser: bool,
    launch_mode: str,
    startup_timeout: float,
    reload: bool,
) -> int:
    import uvicorn

    _base_url, health_url, ui_url = _platform_urls(host, port, ui_path)
    if open_browser:
        _open_platform_ui_when_ready(
            health_url=health_url,
            ui_url=ui_url,
            startup_timeout=startup_timeout,
            launch_mode=launch_mode,
        )
    uvicorn.run(
        "jl_platform.services.api.main:app",
        host=host,
        port=int(port),
        reload=bool(reload),
        log_level="warning",
    )
    return 0


def _launch_desktop_ui(*, chat_only_mode: bool | None = None) -> int:
    import ui.pyside_ui as pyside_ui

    original_argv = list(sys.argv)
    launch_argv = [original_argv[0] if original_argv else "j-engine"]
    if chat_only_mode is True:
        launch_argv.append("--chat-window")
    elif chat_only_mode is False:
        launch_argv.append("--full-window")
    try:
        sys.argv = launch_argv
        pyside_ui.main()
    finally:
        sys.argv = original_argv
    return 0


def _launch_entry(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="j-engine launch",
        description="Standard JL Engine launcher for web, desktop, CLI, or API surfaces.",
    )
    parser.add_argument(
        "--ui",
        choices=("web", "desktop", "cli", "api"),
        default="web",
        help="Which surface to launch.",
    )
    parser.add_argument(
        "--host",
        default=str(os.getenv("JL_PLATFORM_HOST") or "127.0.0.1"),
        help="Host for the platform API when launching web/api.",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=_default_platform_port(),
        help="Port for the platform API when launching web/api.",
    )
    parser.add_argument(
        "--ui-path",
        default=str(os.getenv("JL_PLATFORM_UI_PATH") or "/ui/"),
        help="UI route to open for web launch mode.",
    )
    parser.add_argument(
        "--launch-mode",
        choices=("standalone", "browser"),
        default=_default_launch_mode(),
        help="How to open the web UI when using --ui web.",
    )
    parser.add_argument(
        "--startup-timeout",
        type=float,
        default=_default_startup_timeout(),
        help="Seconds to wait for /health before opening the web UI.",
    )
    parser.add_argument("--reload", action="store_true", help="Run the platform API with auto-reload.")
    parser.add_argument(
        "--no-open-browser",
        action="store_true",
        help="Do not open the browser automatically when launching the web UI.",
    )
    parser.add_argument(
        "--chat-window",
        action="store_true",
        help="Launch the PySide UI in chat-only mode.",
    )
    parser.add_argument(
        "--full-window",
        action="store_true",
        help="Force the full PySide workspace window.",
    )
    args, forwarded = parser.parse_known_args(argv)

    if args.chat_window and args.full_window:
        parser.error("--chat-window and --full-window are mutually exclusive.")

    if args.ui == "cli":
        return _main_cli(forwarded)

    if forwarded:
        parser.error(f"unrecognized arguments: {' '.join(forwarded)}")

    if args.ui == "desktop":
        chat_only_mode = True if args.chat_window else False if args.full_window else None
        return _launch_desktop_ui(chat_only_mode=chat_only_mode)

    return _launch_platform_api(
        host=str(args.host).strip() or "127.0.0.1",
        port=int(args.port),
        ui_path=args.ui_path,
        open_browser=(args.ui == "web" and not args.no_open_browser),
        launch_mode=args.launch_mode,
        startup_timeout=float(args.startup_timeout),
        reload=bool(args.reload),
    )


def _print_agents(engine: JLEngineCore) -> None:
    agents = sorted((engine.mpf_profiles or {}).keys())
    if not agents:
        print("No agents found (MPF registry empty).")
        return
    for name in agents:
        marker = " (active)" if name == engine.current_agent_name else ""
        print(f"{name}{marker}")


def _print_tools(session) -> None:
    specs = session.registry.list_specs()
    if not specs:
        print("No tools registered.")
        return
    print("Registered tools:")
    for spec in specs:
        print(f"- {spec.name}: {spec.description}")

    if getattr(session, "memory_forge", None):
        mem_tools = session.memory_forge.list_tools().get("tools", [])
        if mem_tools:
            print("Dynamic (in-memory) tools:")
            for item in mem_tools:
                print(f"- {item.get('name')}: {item.get('description', '')}")


def _parse_on_off_command(raw: str) -> bool | None:
    parts = raw.split(maxsplit=1)
    if len(parts) != 2:
        return None
    value = parts[1].strip().lower()
    if value not in {"on", "off"}:
        return None
    return value == "on"


def _build_turn_context(*, allow_bias_redirect: bool) -> Dict[str, Any]:
    if allow_bias_redirect:
        return {}
    return {"respect_selected_agent": True}


def _metric_value(value: Any, default: float = 0.0) -> float:
    try:
        return max(0.0, min(1.0, float(value)))
    except (TypeError, ValueError):
        return default


def _metric_bar(value: Any, width: int = 18) -> str:
    numeric = _metric_value(value)
    filled = max(0, min(width, int(round(numeric * width))))
    return "[" + ("#" * filled) + ("." * (width - filled)) + "]"


def _current_ollama_model_name() -> str:
    try:
        backends_mod = importlib.import_module("jl_engine_core.backends")
        registry = getattr(backends_mod, "BACKEND_REGISTRY", {}) or {}
        cfg = registry.get("ollama-local", {}) if isinstance(registry, dict) else {}
        value = str(cfg.get("modelName") or cfg.get("model_name") or "").strip()
        return value or "n/a"
    except Exception:
        return "n/a"


def _current_backend_label() -> str:
    try:
        backends_mod = importlib.import_module("jl_engine_core.backends")
        backend_id = getattr(backends_mod, "brain_backend_id", None) or "unknown"
        registry = getattr(backends_mod, "BACKEND_REGISTRY", {}) or {}
        cfg = registry.get(backend_id, {}) if isinstance(registry, dict) else {}
        return str(cfg.get("label") or backend_id)
    except Exception:
        return "unknown"


def _configure_cli_logging(*, verbose: bool = False) -> None:
    if verbose or str(os.getenv("JL_ENGINE_CLI_VERBOSE_LOGS", "")).strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }:
        return

    root_logger = logging.getLogger()
    for handler in root_logger.handlers:
        if isinstance(handler, logging.StreamHandler) and not isinstance(handler, logging.FileHandler):
            handler.setLevel(logging.WARNING)


def _configure_cli_streams() -> None:
    for stream_name in ("stdout", "stderr"):
        stream = getattr(sys, stream_name, None)
        reconfigure = getattr(stream, "reconfigure", None)
        if callable(reconfigure):
            try:
                reconfigure(errors="replace")
            except Exception:
                pass


def _print_system_message(message: str, tag: str = "system") -> None:
    print(f"\033[96m[{tag}]\033[0m {message}")


def _print_reply(message: str, tag: str = "reply") -> None:
    text = str(message or "").strip()
    if not text:
        return
    print(f"\033[1;95m[{tag}]\033[0m {text}")


def _agent_boot_line(agent_name: str) -> str:
    low = str(agent_name or "").strip().lower()
    if "slappy" in low:
        return "Slappy is on deck. Hit me with it."
    if "gremlin" in low:
        return "Gremlin on the rail. What are we poking at?"
    if "sparkbyte" in low:
        return "SparkByte hotwired and humming. Talk to me."
    return f"{agent_name or 'Agent'} is online. Talk to me."


def _bench_banner_value(session, attr_name: str, default: str) -> str:
    bench = getattr(session, "_bench_executor", None)
    value = getattr(bench, attr_name, None) if bench is not None else None
    if value in (None, ""):
        return default
    return str(value)


def _read_menu_key() -> str:
    if msvcrt is None:
        return "enter"
    while True:
        ch = msvcrt.getwch()
        if ch in ("\r", "\n"):
            return "enter"
        if ch == "\x1b":
            return "esc"
        if ch in ("\x00", "\xe0"):
            code = msvcrt.getwch()
            if code == "H":
                return "up"
            if code == "P":
                return "down"
            continue
        if ch.lower() == "q":
            return "esc"
        if ch == "\x03":
            raise KeyboardInterrupt


def _pick_menu_item(
    tag: str,
    items: list[tuple[str, str]],
    *,
    fallback_title: str,
    fallback_prompt: str,
    value_width: int = 28,
) -> Optional[str]:
    if not items:
        return None
    if msvcrt is None:
        print(f"\n{fallback_title}:")
        for idx, (name, desc) in enumerate(items, start=1):
            suffix = f"  {desc}" if desc else ""
            print(f"  {idx}. {name:<{value_width}}{suffix}")
        raw = input(f"{fallback_prompt}: ").strip()
        if not raw:
            return None
        try:
            selected = int(raw)
        except ValueError:
            return None
        if selected < 1 or selected > len(items):
            return None
        return items[selected - 1][0]

    selected = 0
    print(f"\n\033[96m[{tag}]\033[0m Use up/down then Enter. Esc to cancel.")
    print("")
    for _ in items:
        print("")
    while True:
        sys.stdout.write(f"\033[{len(items)}A")
        for idx, (name, desc) in enumerate(items):
            marker = ">" if idx == selected else " "
            suffix = f" {desc}" if desc else ""
            if idx == selected:
                line = f"\033[1;95m {marker} {name:<{value_width}}\033[0m{suffix}"
            else:
                line = f" {marker} {name:<{value_width}}{suffix}"
            sys.stdout.write("\033[2K\r" + line + "\n")
        sys.stdout.flush()

        key = _read_menu_key()
        if key == "up":
            selected = (selected - 1) % len(items)
            continue
        if key == "down":
            selected = (selected + 1) % len(items)
            continue
        if key == "esc":
            return None
        if key == "enter":
            return items[selected][0]


def _telemetry_summary(
    telemetry: Dict[str, Any],
) -> tuple[Dict[str, str], list[str], list[tuple[str, float]]]:
    behavior = telemetry.get("behavior_state", {}) or {}
    aperture_dynamic = telemetry.get("aperture_dynamic") or {}
    aperture_state = telemetry.get("aperture_state") or {}
    rhythm = telemetry.get("rhythm", {}) or {}
    feedback = telemetry.get("feedback", {}) or {}
    drift = telemetry.get("drift", {}) or {}
    temporal_state = telemetry.get("temporal_state", {}) or {}
    engine_status = telemetry.get("engine_status", {}) or {}

    summary = {
        "agent": str(
            telemetry.get("agent")
            or telemetry.get("agent_name")
            or feedback.get("agent_name")
            or "n/a"
        ),
        "behavior": str(behavior.get("name") or behavior.get("id") or "n/a"),
        "gait": str(
            engine_status.get("gait")
            or telemetry.get("gait")
            or telemetry.get("active_gait_state")
            or rhythm.get("gait")
            or feedback.get("active_gait_state")
            or "n/a"
        ),
        "rhythm": str(
            engine_status.get("rhythm")
            or rhythm.get("mode")
            or rhythm.get("pattern")
            or telemetry.get("active_rhythm_pattern")
            or feedback.get("active_rhythm_pattern")
            or "n/a"
        ),
        "aperture": str(
            aperture_state.get("mode")
            or engine_status.get("aperture_mode")
            or aperture_dynamic.get("mode")
            or feedback.get("aperture_level")
            or "n/a"
        ),
    }
    detail_bits: list[str] = []
    scene = str(
        telemetry.get("thinking_scene")
        or temporal_state.get("scene_label")
        or aperture_state.get("emotion_scene")
        or ""
    ).strip()
    emotion = str(
        aperture_state.get("emotion")
        or telemetry.get("thinking_facet")
        or temporal_state.get("facet_label")
        or ""
    ).strip()
    cognitive = str(telemetry.get("cognitive_mode") or "").strip()
    sampling_ready = telemetry.get("temporal_sampling_ready")
    if sampling_ready is None:
        sampling_ready = temporal_state.get("sampling_ready")
    if scene:
        detail_bits.append(f"scene={scene}")
    if emotion:
        detail_bits.append(f"emotion={emotion}")
    if cognitive:
        detail_bits.append(f"mind={cognitive}")
    if sampling_ready is not None:
        detail_bits.append(f"sampling={'hot' if bool(sampling_ready) else 'warming'}")
    metrics = [
        ("Stability", _metric_value(telemetry.get("stability_score"), default=0.5)),
        ("Aperture", _metric_value(aperture_state.get("score"), default=0.0)),
        ("Rhythm", _metric_value(rhythm.get("index"), default=0.0)),
        ("Drift", _metric_value(drift.get("pressure"), default=0.0)),
        (
            "Novelty",
            _metric_value(
                telemetry.get("novelty_pressure", temporal_state.get("novelty_pressure")),
                default=0.0,
            ),
        ),
        (
            "Loop",
            _metric_value(
                telemetry.get("loop_pressure", temporal_state.get("loop_pressure")),
                default=0.0,
            ),
        ),
    ]
    return summary, detail_bits, metrics


def _print_telemetry_hud(telemetry: Dict[str, Any]) -> None:
    summary, detail_bits, metrics = _telemetry_summary(telemetry)
    print("\n" + "=" * 56)
    print("[ ENGINE HUD ]")
    print(
        f"{summary['agent']} | {summary['behavior']} | gait={summary['gait']} "
        f"| rhythm={summary['rhythm']} | aperture={summary['aperture']}"
    )
    if detail_bits:
        print(" | ".join(detail_bits))
    print("-" * 56)
    for label, value in metrics:
        print(f"{label:<10} {_metric_bar(value)} {value:>7.4f}")
    print("=" * 56 + "\n")


def _print_main_status(
    session,
    *,
    show_trace: bool,
    watch_mode: bool,
    allow_bias_redirect: bool,
) -> None:
    agent = str(getattr(session.engine, "current_agent_name", "agent") or "agent")
    bench = getattr(session, "_bench_executor", None)
    print("\033[96m[status]\033[0m")
    print(f"  backend: {_current_backend_label()}")
    print(f"  ollama_model: {_current_ollama_model_name()}")
    print("  mode: main_chat")
    print(f"  agent: {agent}")
    print(f"  workspace: {getattr(bench, 'session_workdir', Path.cwd())}")
    print("  task_router: engine_first")
    print(f"  trace: {'on' if show_trace else 'off'}")
    print(f"  watch: {'on' if watch_mode else 'off'}")
    print(f"  tqa_redirect: {'on' if allow_bias_redirect else 'off'}")
    if bench is not None:
        print(f"  bench_worker: {getattr(bench, 'active_worker_agent_name', 'Bench Worker')}")
        print(f"  confirm: {'on' if getattr(bench, 'human_verification', False) else 'off'}")
        print(f"  show_plan: {'on' if getattr(bench, 'show_plan', False) else 'off'}")
        print(f"  show_raw_output: {'on' if getattr(bench, 'show_raw_output', False) else 'off'}")
        print(
            f"  clear_memory_each_turn: "
            f"{'on' if getattr(bench, 'clear_memory_each_turn', False) else 'off'}"
        )
        trace_log = getattr(bench, "trace_log_path", None)
        if trace_log:
            print(f"  trace_log: {trace_log}")
    else:
        print("  bench_worker: lazy (/worker or /bench)")


def _print_main_banner(
    session,
    *,
    show_trace: bool,
    watch_mode: bool,
    allow_bias_redirect: bool,
) -> None:
    agent = str(getattr(session.engine, "current_agent_name", "agent") or "agent")
    bench = getattr(session, "_bench_executor", None)
    worker_label = getattr(bench, "active_worker_agent_name", "lazy (/worker or /bench)")
    workspace = getattr(bench, "session_workdir", Path.cwd())
    retries = _bench_banner_value(session, "retry_limit", "--")
    timeout = _bench_banner_value(session, "request_timeout", "--")
    timeout_label = f"{timeout}s" if timeout != "--" else "--"
    trace_log = _bench_banner_value(session, "trace_log_path", "lazy (/worker or /bench)")
    print("\n\033[1;36m=== THE HEALING BENCH ===\033[0m")
    print(f"Backend:      {_current_backend_label()}")
    print(f"Model:        {_current_ollama_model_name()}")
    print(f"Retries:      {retries}")
    print(f"Timeout:      {timeout_label}")
    print("Supervisor:   Unified Console // Engine-first Chat")
    print(f"Agent:        {agent}")
    print(f"Workspace:    {workspace}")
    print(f"Worker:       {worker_label}")
    print(f"Trace Log:    {trace_log}")
    print(
        "Runtime:      "
        f"trace={'on' if show_trace else 'off'} | "
        f"watch={'on' if watch_mode else 'off'} | "
        f"tqa_redirect={'on' if allow_bias_redirect else 'off'}"
    )
    print("Slash Menu:   Type / for command picker")
    print("\n")
    _print_system_message(_agent_boot_line(agent), agent)


def _load_healing_bench_executor():
    bench_mod = importlib.import_module("jl_platform.core.healing_bench_executor")
    return getattr(bench_mod, "HealingBenchExecutor")


def _sync_bench_worker_to_agent(session, agent_name: str) -> None:
    bench = getattr(session, "_bench_executor", None)
    if bench is None:
        return
    try:
        bench._set_worker_agent(agent_name)
    except Exception:
        return


def _ensure_bench_executor(session, *, sync_selected_agent: bool = False):
    bench = getattr(session, "_bench_executor", None)
    if bench is None:
        try:
            HealingBenchExecutor = _load_healing_bench_executor()
        except Exception as exc:
            print(f"Failed to load Healing Bench: {exc}")
            return None
        bench = HealingBenchExecutor()
        setattr(session, "_bench_executor", bench)
        sync_selected_agent = True
    if sync_selected_agent:
        selected_agent = str(getattr(session.engine, "current_agent_name", "") or "").strip()
        if selected_agent:
            try:
                bench._set_worker_agent(selected_agent)
            except Exception:
                pass
    return bench


def _pick_main_agent(engine: JLEngineCore) -> Optional[str]:
    profiles = engine.mpf_profiles or {}
    items: list[tuple[str, str]] = []
    for name in sorted(profiles.keys()):
        profile = profiles.get(name) or {}
        desc = ""
        if isinstance(profile, dict):
            desc = str(
                profile.get("jl_agent_file")
                or profile.get("agent_file")
                or profile.get("type")
                or ""
            )
        if name == engine.current_agent_name:
            desc = f"{desc} [active]".strip()
        items.append((name, desc))
    return _pick_menu_item(
        "agent menu",
        items,
        fallback_title="Agents",
        fallback_prompt="Select agent number (blank to cancel)",
        value_width=30,
    )


def _pick_main_slash_command() -> Optional[str]:
    items = [
        ("/status", "Show unified console status"),
        ("/pending", "Show the current pending action"),
        ("/approve", "Approve the current pending action"),
        ("/decline", "Decline the current pending action"),
        ("/agent", "Select the main chat agent"),
        ("/worker", "Select the bench worker agent"),
        ("/backend", "Show or switch backend"),
        ("/model", "Show or switch Ollama model"),
        ("/models", "List local Ollama models"),
        ("/workspace", "Change active workspace"),
        ("/bench", "Enter bench worker conversation"),
        ("/confirm", "Toggle bench execution confirmation"),
        ("/plan", "Toggle bench plan preview"),
        ("/raw", "Toggle bench raw output"),
        ("/memory", "Toggle or clear bench memory"),
        ("/unstick", "Reset the bench worker loop state"),
        ("/tools", "List registered tools"),
        ("/trace", "Toggle tool trace printing"),
        ("/watch", "Toggle live agent-thinking output"),
        ("/keep", "Keep dynamic tools after use"),
        ("/doctor", "Show system health"),
        ("/hosts", "List host templates"),
        ("/init host", "Create a new host"),
        ("/exit", "Exit the console"),
    ]
    return _pick_menu_item(
        "/ menu",
        items,
        fallback_title="Slash commands",
        fallback_prompt="Select command number (blank to cancel)",
        value_width=12,
    )


def _get_pending_action_snapshot(session) -> Dict[str, Any] | None:
    getter = getattr(session, "get_pending_action", None)
    if not callable(getter):
        return None
    try:
        pending = getter()
    except Exception:
        return None
    return pending if isinstance(pending, dict) else None


def _print_pending_action(pending: Dict[str, Any]) -> None:
    print("\033[96m[pending action]\033[0m")
    print(f"  summary: {pending.get('summary') or 'unknown action'}")
    print(f"  tool: {pending.get('tool') or 'unknown'}")
    print(f"  risk: {pending.get('risk_level') or 'unknown'}")


def _looks_like_worker_task(text: str) -> bool:
    low = str(text or "").strip().lower()
    if not low:
        return False
    word_tokens = set(re.findall(r"[a-z0-9_]+", low))
    starting_verbs = (
        "fix ",
        "build ",
        "create ",
        "make ",
        "put ",
        "write ",
        "run ",
        "execute ",
        "test ",
        "debug ",
        "refactor ",
        "patch ",
        "update ",
        "open ",
        "show ",
        "list ",
        "find ",
        "search ",
        "check ",
        "inspect ",
        "launch ",
        "start ",
        "stop ",
        "install ",
    )
    action_terms = (
        "fix",
        "build",
        "create",
        "make",
        "write",
        "run",
        "execute",
        "test",
        "debug",
        "refactor",
        "patch",
        "update",
        "open",
        "show",
        "list",
        "find",
        "search",
        "check",
        "inspect",
        "launch",
        "start",
        "stop",
        "install",
        "plan",
    )
    task_terms = (
        "file",
        "files",
        "folder",
        "directory",
        "project",
        "repo",
        "repository",
        "code",
        "bug",
        "issue",
        "test",
        "tests",
        "command",
        "shell",
        "powershell",
        "cmd",
        "python",
        "app",
        "server",
        "ui",
        "browser",
        "workspace",
        "system",
        "computer",
        "machine",
        "desktop",
        "documents",
        "downloads",
        "plan",
    )
    if low.startswith(starting_verbs):
        return True
    return any(term in word_tokens for term in action_terms) and any(
        term in word_tokens for term in task_terms
    )


def _render_result_output(result: Dict[str, Any], *, show_trace: bool, speaker_tag: str) -> None:
    telemetry = result.get("telemetry", {})
    if telemetry:
        _print_telemetry_hud(telemetry)

    trace = result.get("tool_trace") or []
    if show_trace and trace:
        print("[tool_trace]")
        print(json.dumps(trace, indent=2))
        print()

    final = result.get("final") or result.get("reply")
    if final:
        _print_reply(str(final), tag=speaker_tag)
    else:
        print(json.dumps(result, indent=2))


def _resolve_confirmation_flow(session, result: Dict[str, Any], auto_approve: bool = False) -> Dict[str, Any]:
    current = dict(result or {})
    while str(current.get("status") or "") == "confirmation_required":
        pending = (
            current.get("pending_action")
            if isinstance(current.get("pending_action"), dict)
            else _get_pending_action_snapshot(session)
        )
        if not isinstance(pending, dict):
            return current
        
        if auto_approve:
            summary = pending.get("summary", "action")
            print(f"\033[90m  [⚙️ executing] {summary}...\033[0m")
            approved = True
            note = ""
        else:
            _print_pending_action(pending)
            try:
                choice = input("Approve this action? [y/N]: ").strip()
            except KeyboardInterrupt:
                choice = ""
            choice_low = choice.lower()
            approved = choice_low in {"y", "yes", "approve", "/approve"}
            note = ""
            if choice_low.startswith("/approve "):
                note = choice.split(maxsplit=1)[1].strip()
                approved = True
            elif choice_low.startswith("/decline ") or choice_low.startswith("/deny "):
                note = choice.split(maxsplit=1)[1].strip()
                approved = False
                
        confirmer = getattr(session, "confirm_pending_action", None)
        if not callable(confirmer):
            return current
        current = confirmer(str(pending.get("id") or ""), approved=approved, note=note)
    return current


def _run_bench_mode(session) -> None:
    bench = _ensure_bench_executor(session, sync_selected_agent=False)
    if bench is None:
        return

    print("\n\033[1;36m=== THE HEALING BENCH :: WORKER CHANNEL ===\033[0m")
    print(
        f"Backend:      "
        f"{getattr(bench, '_backend_label', lambda value: value)(getattr(bench, 'backend_id', 'unknown'))}"
    )
    print(f"Worker:       {getattr(bench, 'active_worker_agent_name', 'Bench Worker')}")
    print("Mode:         Bench Worker Conversation")
    print("Slash Menu:   Type / or /help inside this mode")
    print("Return:       /back")
    print("")
    _print_system_message(
        "Bench worker ready.",
        str(getattr(session.engine, "current_agent_name", "system") or "system"),
    )

    while True:
        try:
            raw = input("\n\033[1;32mbench>\033[0m ").strip()
        except KeyboardInterrupt:
            _print_system_message(
                "Leaving Bench Worker mode.",
                str(getattr(session.engine, "current_agent_name", "system") or "system"),
            )
            return

        if not raw:
            continue
        low = raw.lower()
        if low in {"/back", "/return", "/exit-bench", "back"}:
            _print_system_message(
                "Leaving Bench Worker mode.",
                str(getattr(session.engine, "current_agent_name", "system") or "system"),
            )
            return

        if raw.startswith("/"):
            slash_result = bench._handle_slash_command(raw)
            if slash_result == "exit":
                _print_system_message(
                    "Leaving Bench Worker mode.",
                    str(getattr(session.engine, "current_agent_name", "system") or "system"),
                )
                return
            if slash_result == "handled":
                continue

        bench.run_turn(raw)


def _repl(
    session,
    *,
    show_trace: bool,
    watch_mode: bool = False,
    allow_bias_redirect: bool = False,
    auto_approve: bool = False,
) -> int:
    _print_main_banner(
        session,
        show_trace=show_trace,
        watch_mode=watch_mode,
        allow_bias_redirect=allow_bias_redirect,
    )
    while True:
        try:
            raw = input("\n\033[1;32m>\033[0m ").strip()
        except KeyboardInterrupt:
            print("\nExiting.")
            return 0

        if not raw:
            continue
        low = raw.lower()

        if low == "/":
            picked = _pick_main_slash_command()
            if not picked:
                _print_system_message(
                    "Slash menu canceled.",
                    str(getattr(session.engine, "current_agent_name", "system") or "system"),
                )
                continue
            raw = picked
            low = raw.lower()

        if low in {"/exit", "/quit", "exit", "quit"}:
            return 0
        if low in {"/help", "help", "?"}:
            print("\033[96m[slash commands]\033[0m")
            print("  /status       Show current console status")
            print("  /pending      Show the current pending action")
            print("  /approve      Approve the current pending action")
            print("  /decline      Decline the current pending action")
            print("  /agent        Switch the main chat personality")
            print("  /worker       Switch the bench worker schema")
            print("  /backend      Show or set backend")
            print("  /model        Show or set local Ollama model")
            print("  /models       List local Ollama models")
            print("  /workspace    Change active workspace")
            print("  /bench        Optional dedicated worker channel or '/bench <task>'")
            print("  /confirm      Toggle bench execution confirmation")
            print("  /plan         Toggle bench plan preview")
            print("  /raw          Toggle bench raw output")
            print("  /memory       Toggle or clear bench memory")
            print("  /unstick      Reset bench worker repetition state")
            print("  /trace-log    Set bench trace log path")
            print("  chat turns    Engine-first. Use /bench or /bench <task> for worker handoff")
            print("  /tools        List registered tools")
            print("  /trace on|off Toggle tool trace printing")
            print("  /watch on|off Toggle live tool-call watch")
            print("  /keep on|off  Keep dynamic tools after use")
            print("  /promote      Promote a dynamic tool")
            print("  /doctor       Show system health")
            print("  /hosts        List host templates")
            print("  /init host    Create a new host")
            print("  /exit         Exit the console")
            continue

        if low == "/status":
            _print_main_status(
                session,
                show_trace=show_trace,
                watch_mode=watch_mode,
                allow_bias_redirect=allow_bias_redirect,
            )
            continue

        if low == "/pending":
            pending = _get_pending_action_snapshot(session)
            if pending is None:
                _print_system_message(
                    "No pending action.",
                    str(getattr(session.engine, "current_agent_name", "system") or "system"),
                )
            else:
                _print_pending_action(pending)
            continue

        if low.startswith("/approve") or low.startswith("/decline") or low.startswith("/deny"):
            pending = _get_pending_action_snapshot(session)
            if pending is None:
                _print_system_message(
                    "No pending action.",
                    str(getattr(session.engine, "current_agent_name", "system") or "system"),
                )
                continue
            confirmer = getattr(session, "confirm_pending_action", None)
            if not callable(confirmer):
                print("Pending action approvals are not supported in this session.")
                continue
            parts = raw.split(maxsplit=1)
            note = parts[1].strip() if len(parts) == 2 else ""
            approved = low.startswith("/approve")
            result = confirmer(str(pending.get("id") or ""), approved=approved, note=note)
            _render_result_output(
                result,
                show_trace=show_trace,
                speaker_tag=str(getattr(session.engine, "current_agent_name", "reply") or "reply"),
            )
            continue

        if low.startswith("/trace"):
            parsed = _parse_on_off_command(raw)
            if parsed is not None:
                show_trace = parsed
                print(f"trace={'on' if show_trace else 'off'}")
            else:
                print("Usage: /trace on|off")
            continue

        if low.startswith("/watch"):
            parsed = _parse_on_off_command(raw)
            if parsed is not None:
                watch_mode = parsed
                print(f"watch mode={'on' if watch_mode else 'off'}")
                if watch_mode:
                    print("Agent thinking will be shown in real-time...\n")
            else:
                print("Usage: /watch on|off")
            continue

        if low.startswith("/backend"):
            parts = raw.split()
            if len(parts) == 1:
                _print_backends()
                continue
            if len(parts) >= 3 and parts[1] in {"brain", "tool"}:
                backend_type = parts[1]
                backend_id = parts[2]
                _configure_backends(
                    brain_id=backend_id if backend_type == "brain" else None,
                    tool_id=backend_id if backend_type == "tool" else None,
                )
                _print_system_message(
                    f"{backend_type} backend set to: {backend_id}",
                    str(getattr(session.engine, "current_agent_name", "system") or "system"),
                )
                continue
            if len(parts) == 2:
                backend_id = parts[1].strip()
                _configure_backends(brain_id=backend_id, tool_id=backend_id)
                bench = getattr(session, "_bench_executor", None)
                if bench is not None:
                    setattr(bench, "backend_id", backend_id)
                    try:
                        bench.request_timeout = bench._initial_timeout_for_backend(backend_id)
                    except Exception:
                        pass
                _print_system_message(
                    f"Backend set to: {backend_id}",
                    str(getattr(session.engine, "current_agent_name", "system") or "system"),
                )
                continue
            print("Usage: /backend <id> or /backend brain <id> or /backend tool <id>")
            continue

        if low == "/models":
            _print_ollama_models()
            continue

        if low.startswith("/model"):
            parts = raw.split(maxsplit=1)
            if len(parts) == 1:
                _print_system_message(
                    f"Ollama model: {_current_ollama_model_name()}",
                    str(getattr(session.engine, "current_agent_name", "system") or "system"),
                )
                _print_ollama_models()
                continue
            model_name = parts[1].strip()
            if model_name:
                _set_ollama_model(model_name)
                _print_system_message(
                    f"Ollama model set to: {model_name}",
                    str(getattr(session.engine, "current_agent_name", "system") or "system"),
                )
            continue

        if low.startswith("/agent"):
            parts = raw.split(maxsplit=1)
            name = parts[1].strip() if len(parts) == 2 else ""
            if not name:
                name = _pick_main_agent(session.engine) or ""
            if not name:
                _print_system_message(
                    "Agent selection canceled.",
                    str(getattr(session.engine, "current_agent_name", "system") or "system"),
                )
                continue
            try:
                session.engine.set_agent(name)
                _sync_bench_worker_to_agent(session, str(session.engine.current_agent_name))
                _print_system_message(
                    f"Agent set to: {session.engine.current_agent_name}",
                    str(getattr(session.engine, "current_agent_name", "system") or "system"),
                )
            except Exception as exc:
                print(f"Failed to set agent: {exc}")
            continue

        if low.startswith("/worker"):
            bench = _ensure_bench_executor(session, sync_selected_agent=True)
            if bench is None:
                continue
            parts = raw.split(maxsplit=1)
            selection = parts[1].strip() if len(parts) == 2 else ""
            if not selection:
                try:
                    selection = bench._pick_worker_agent() or ""
                except Exception:
                    selection = ""
            if not selection:
                _print_system_message(
                    "Worker selection canceled.",
                    str(getattr(session.engine, "current_agent_name", "system") or "system"),
                )
                continue
            try:
                if not bench._set_worker_agent(selection):
                    _print_system_message(
                        f"Worker agent not found: {selection}",
                        str(getattr(session.engine, "current_agent_name", "system") or "system"),
                    )
                    continue
            except Exception as exc:
                print(f"Failed to set worker agent: {exc}")
                continue
            _print_system_message(
                f"Bench worker set to: {getattr(bench, 'active_worker_agent_name', selection)}",
                str(getattr(session.engine, "current_agent_name", "system") or "system"),
            )
            continue

        if low.startswith("/workspace"):
            bench = _ensure_bench_executor(session, sync_selected_agent=False)
            if bench is None:
                continue
            bench._handle_slash_command(raw)
            continue

        if low.startswith("/confirm") or low.startswith("/plan") or low.startswith("/raw"):
            bench = _ensure_bench_executor(session, sync_selected_agent=False)
            if bench is None:
                continue
            bench._handle_slash_command(raw)
            continue

        if low.startswith("/memory") or low == "/unstick":
            bench = _ensure_bench_executor(session, sync_selected_agent=False)
            if bench is None:
                continue
            bench._handle_slash_command(raw)
            continue

        if low.startswith("/trace-log"):
            bench = _ensure_bench_executor(session, sync_selected_agent=False)
            if bench is None:
                continue
            parts = raw.split(maxsplit=1)
            bench._handle_slash_command("/trace" if len(parts) == 1 else f"/trace {parts[1]}")
            continue

        if low == "/tools":
            _print_tools(session)
            continue

        if low.startswith("/keep"):
            if not getattr(session, "memory_forge", None):
                print("No in-memory forge active.")
                continue
            parsed = _parse_on_off_command(raw)
            if parsed is not None:
                keep = parsed
                session.memory_forge._delete_after_use = not keep
                _print_system_message(
                    f"keep_dynamic_tools={'on' if keep else 'off'}",
                    str(getattr(session.engine, "current_agent_name", "system") or "system"),
                )
            else:
                print("Usage: /keep on|off")
            continue

        if low.startswith("/promote"):
            if not getattr(session, "memory_forge", None):
                print("No in-memory forge active.")
                continue
            parts = raw.split(maxsplit=1)
            if len(parts) != 2 or not parts[1].strip():
                print("Usage: /promote <tool_name>")
                continue
            name = parts[1].strip()
            res = session.memory_forge.promote_tool(name)
            print(json.dumps(res, indent=2))
            continue

        if low == "/doctor":
            try:
                from jl_platform.core.safety import ALLOW_NETWORK
                from jl_platform.sdk.client import HOST_REGISTRY
                from pathlib import Path

                print("\n[ SYSTEM HEALTH ]")
                print(f"  network_allowed: {ALLOW_NETWORK}")
                print(f"  available_hosts: {', '.join(sorted(HOST_REGISTRY.keys()))}")
                print(f"  cwd: {Path.cwd()}")
                print()
            except Exception as e:
                print(f"Doctor check failed: {e}")
            continue

        if low == "/hosts":
            try:
                from jl_platform.sdk.client import HOST_REGISTRY

                print("\n[ AVAILABLE HOSTS ]")
                for name in sorted(HOST_REGISTRY.keys()):
                    print(f"  - {name}")
                print()
            except Exception as e:
                print(f"Failed to list hosts: {e}")
            continue

        if low.startswith("/init host"):
            parts = raw.split(maxsplit=2)
            if len(parts) < 3:
                print("Usage: /init host <name>")
                continue
            host_name = parts[2].strip()
            try:
                from jl_platform.cli.main import init_host as _init_host

                _init_host(host_name)
            except Exception as e:
                print(f"Failed to init host: {e}")
            continue

        if low.startswith("/bench "):
            bench = _ensure_bench_executor(session, sync_selected_agent=True)
            if bench is None:
                continue
            bench.run_turn(raw.split(maxsplit=1)[1].strip())
            continue

        if low in {"/bench", "/heal", "/healing"}:
            _run_bench_mode(session)
            continue

        result = session.run(raw, context=_build_turn_context(allow_bias_redirect=allow_bias_redirect))
        result = _resolve_confirmation_flow(session, result, auto_approve=auto_approve)

        if watch_mode:
            trace = result.get("tool_trace") or []
            if trace:
                thinking_tag = str(getattr(session.engine, "current_agent_name", "agent") or "agent")
                print(f"\n[{thinking_tag} thinking]")
                for t in trace:
                    tool_name = t.get("tool", "?")
                    print(f"\033[90m[{thinking_tag} thinking]\033[0m calling tool: {tool_name}")
                print()

        speaker_tag = str(
            (result.get("telemetry") or {}).get("agent")
            or getattr(session.engine, "current_agent_name", "reply")
            or "reply"
        )
        _render_result_output(result, show_trace=show_trace, speaker_tag=speaker_tag)


def _load_platform() -> tuple[type, type]:
    interpreter_mod = importlib.import_module("jl_platform.core.interpreter")
    forge_mod = importlib.import_module("jl_platform.core.tools.PrivilegedMemoryForge")
    return (
        getattr(interpreter_mod, "InterpreterSession"),
        getattr(forge_mod, "PrivilegedMemoryForge"),
    )


def _configure_backends(brain_id: str | None, tool_id: str | None) -> None:
    try:
        backends_mod = importlib.import_module("jl_engine_core.backends")
        if brain_id:
            getattr(backends_mod, "set_brain_backend_id")(brain_id)
        if tool_id:
            getattr(backends_mod, "set_tool_backend_id")(tool_id)
    except Exception:
        pass


def _print_backends() -> None:
    try:
        backends_mod = importlib.import_module("jl_engine_core.backends")
        registry = getattr(backends_mod, "BACKEND_REGISTRY", {})
        brain_id = getattr(backends_mod, "brain_backend_id", None)
        tool_id = getattr(backends_mod, "tool_backend_id", None)
        print("\nAvailable backends:")
        for bid, cfg in registry.items():
            label = cfg.get("label", bid)
            markers = []
            if bid == brain_id:
                markers.append("brain")
            if bid == tool_id:
                markers.append("tool")
            mark = f" ({', '.join(markers)})" if markers else ""
            print(f"  {bid}: {label}{mark}")
        print()
    except Exception as e:
        print(f"Could not load backends: {e}\n")


def _print_ollama_models() -> None:
    """List available models from local Ollama."""
    try:
        import requests
        resp = requests.get("http://127.0.0.1:11434/api/tags", timeout=5)
        resp.raise_for_status()
        data = resp.json()
        models = data.get("models", [])
        if not models:
            print("No Ollama models found.")
            return
        
        # Get current model from backend config
        current_model = None
        try:
            backends_mod = importlib.import_module("jl_engine_core.backends")
            backend = getattr(backends_mod, "get_brain_backend", lambda: None)()
            if backend:
                current_model = backend._model_name() if hasattr(backend, '_model_name') else None
        except Exception:
            pass
        
        print("\nAvailable Ollama models:")
        for m in models:
            name = m.get("name", "?")
            marker = " (current)" if name == current_model else ""
            size_mb = m.get("size", 0) // (1024*1024)
            print(f"  {name}{marker}  ({size_mb} MB)")
        print()
    except Exception as e:
        print(f"Could not fetch Ollama models: {e}\n")


def _set_ollama_model(model_name: str) -> None:
    """Set the Ollama model for brain and tool backends."""
    try:
        backends_mod = importlib.import_module("jl_engine_core.backends")
        registry = getattr(backends_mod, "BACKEND_REGISTRY", {})
        
        # Find ollama-local backend config
        ollama_cfg = registry.get("ollama-local", {})
        if not ollama_cfg:
            print("Ollama backend not found.")
            return
        
        # Update model in config
        ollama_cfg = dict(ollama_cfg)
        ollama_cfg["modelName"] = model_name
        
        # Re-register with new model
        registry["ollama-local"] = ollama_cfg
        
        # Reconfigure
        getattr(backends_mod, "configure_backends")(
            brain_id="ollama-local",
            tool_id="ollama-local"
        )
    except Exception as e:
        print(f"Failed to set Ollama model: {e}")


def _main_cli(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        prog="j-engine",
        description="Agentic CLI on top of J_engine Core (agents + tool-calling).",
    )
    parser.add_argument("--config", help="Optional path to JSON/YAML config overrides")
    parser.add_argument("--agent", help="Initial agent name (MPF display name)")
    parser.add_argument("--list-agents", action="store_true", help="List agents and exit")
    parser.add_argument("--max-steps", type=int, default=6, help="Max tool-call steps per turn")
    parser.add_argument("--trace", action="store_true", help="Print tool trace after each turn")
    parser.add_argument("--watch", action="store_true", help="Show agent thinking in real-time")
    parser.add_argument("--auto-approve", action="store_true", help="Auto-approve all tool calls without prompting")
    parser.add_argument(
        "--allow-bias-redirect",
        action="store_true",
        help="Allow TQA to redirect away from the selected agent during CLI turns",
    )
    parser.add_argument("--unsafe-tools", action="store_true", help="Enable shell/fs/subprocess tools")
    parser.add_argument("--no-forge", action="store_true", help="Disable dynamic in-memory tools")
    parser.add_argument("--brain-backend", help="Set brain backend (e.g., ollama-local, openrouter, google-gemini)")
    parser.add_argument("--tool-backend", help="Set tool backend (e.g., ollama-local, openrouter, google-gemini)")
    parser.add_argument("--model", help="Set Ollama model (e.g., dolphin3:latest, qwen2.5-coder:3b)")
    parser.add_argument("--version", action="store_true", help="Show installed version")
    parser.add_argument(
        "--verbose-engine-logs",
        action="store_true",
        help="Show raw engine INFO logs in the CLI",
    )

    args = parser.parse_args(argv)
    if args.version:
        print(f"J_engine Core v{__version__}")
        return 0

    _configure_cli_streams()
    _configure_backends(args.brain_backend, args.tool_backend)
    _configure_cli_logging(verbose=bool(args.verbose_engine_logs))
    if args.model:
        _set_ollama_model(args.model)

    engine = _build_engine(args.config)
    selected_agent = args.agent
    if selected_agent:
        engine.set_agent(selected_agent)

    if args.list_agents:
        _print_agents(engine)
        return 0

    try:
        InterpreterSession, PrivilegedMemoryForge = _load_platform()
    except Exception:
        repo_src = Path(__file__).resolve().parents[2] / "src"
        if repo_src.exists():
            sys.path.insert(0, str(repo_src))
        InterpreterSession, PrivilegedMemoryForge = _load_platform()

    memory_forge = None if args.no_forge else PrivilegedMemoryForge()
    allow_unsafe = bool(args.unsafe_tools) if args.unsafe_tools else default_allow_unsafe_tools()
    session = InterpreterSession(
        engine=engine,
        max_steps=max(1, int(args.max_steps)),
        memory_forge=memory_forge,
        allow_unsafe_tools=allow_unsafe,
        allow_direct_action_fallback=allow_unsafe,
    )
    if not allow_unsafe:
        print("Unsafe tools are disabled. Re-run with --unsafe-tools to enable shell/fs/subprocess.\n")
    return _repl(
        session,
        show_trace=bool(args.trace),
        watch_mode=bool(args.watch),
        allow_bias_redirect=bool(args.allow_bias_redirect),
        auto_approve=bool(args.auto_approve),
    )


def main(argv: Optional[list[str]] = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if args and args[0] == "launch":
        return _launch_entry(args[1:])
    return _main_cli(args)


if __name__ == "__main__":
    raise SystemExit(main())
