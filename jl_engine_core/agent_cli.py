from __future__ import annotations

import argparse
import json
from typing import Any, Dict, Optional

from . import __version__
from .config_loader import load_config
from .engine_core import EngineConfig, JLEngineCore


def _merge_config_overrides(overrides: Dict[str, Any]) -> EngineConfig:
    """Apply only known EngineConfig keys from an override mapping."""
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


def _build_turn_context(*, allow_bias_redirect: bool) -> Dict[str, Any]:
    if allow_bias_redirect:
        return {}
    return {"respect_selected_agent": True}


def _repl(session, *, show_trace: bool, allow_bias_redirect: bool = False, auto_approve: bool = False) -> int:
    print("J_engine Agent (tool-calling) ready. Type /help for commands, Ctrl+C to exit.\n")
    while True:
        try:
            agent = getattr(session.engine, "current_agent_name", "agent")
            raw = input(f"({agent})> ").strip()
        except KeyboardInterrupt:
            print("\nExiting.")
            return 0

        if not raw:
            continue
        low = raw.lower()

        if low in {"/exit", "/quit", "exit", "quit"}:
            return 0
        if low in {"/help", "help", "?"}:
            print(
                "\nCommands:\n"
                "  /agent                List agents\n"
                "  /agent <name>         Set agent\n"
                "  /tools                  List available tools\n"
                "  /trace on|off           Toggle tool trace printing\n"
                "  /keep on|off            Keep dynamic tools after use\n"
                "  /promote <tool_name>    Promote a dynamic tool to disk + core\n"
                "  /exit                   Exit\n"
            )
            continue

        if low.startswith("/agent"):
            parts = raw.split(maxsplit=1)
            if len(parts) == 1:
                _print_agents(session.engine)
                continue
            name = parts[1].strip()
            if not name:
                _print_agents(session.engine)
                continue
            try:
                session.engine.set_agent(name)
                print(f"Agent set: {session.engine.current_agent_name}")
            except Exception as exc:
                print(f"Failed to set agent: {exc}")
            continue

        if low == "/tools":
            _print_tools(session)
            continue

        if low.startswith("/trace"):
            parts = raw.split(maxsplit=1)
            if len(parts) == 2 and parts[1].strip().lower() in {"on", "off"}:
                show_trace = parts[1].strip().lower() == "on"
                print(f"trace={'on' if show_trace else 'off'}")
            else:
                print("Usage: /trace on|off")
            continue

        if low.startswith("/keep"):
            if not getattr(session, "memory_forge", None):
                print("No in-memory forge active.")
                continue
            parts = raw.split(maxsplit=1)
            if len(parts) == 2 and parts[1].strip().lower() in {"on", "off"}:
                keep = parts[1].strip().lower() == "on"
                session.memory_forge._delete_after_use = not keep
                print(f"keep_dynamic_tools={'on' if keep else 'off'}")
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

        result = session.run(raw, context=_build_turn_context(allow_bias_redirect=allow_bias_redirect))
        
        while result.get("status") == "confirmation_required":
            pending = session.get_pending_action()
            if not pending:
                break
                
            summary = pending.get("summary", "unknown action")
            print(f"\n[Agent wants to: {summary}]")
            
            if auto_approve:
                print("[*] Auto-approving action...")
                approved = True
            else:
                try:
                    ans = input("Approve? [Y/n] ").strip().lower()
                except KeyboardInterrupt:
                    print("\nCancelled.")
                    approved = False
                approved = ans in {"", "y", "yes"}

            print()
            result = session.confirm_pending_action(pending["id"], approved=approved)

        final = result.get("final")
        if final:
            print(final)
        else:
            print(json.dumps(result, indent=2))

        trace = result.get("tool_trace") or []
        if show_trace and trace:
            print("\n[tool_trace]")
            print(json.dumps(trace, indent=2))
            print()


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        prog="j-agent",
        description="Agentic CLI on top of J_engine Core (agents + tool-calling).",
    )
    parser.add_argument("--config", help="Optional path to JSON/YAML config overrides")
    parser.add_argument("--agent", help="Initial agent name (MPF display name)")
    parser.add_argument("--list-agents", action="store_true", help="List agents and exit")
    parser.add_argument("--max-steps", type=int, default=15, help="Max tool-call steps per turn")
    parser.add_argument("--trace", action="store_true", help="Print tool trace after each turn")
    parser.add_argument("--auto-approve", action="store_true", help="Auto-approve all tool calls without prompting")
    parser.add_argument(
        "--allow-bias-redirect",
        action="store_true",
        help="Allow TQA to redirect away from the selected agent during CLI turns",
    )
    parser.add_argument("--no-forge", action="store_true", help="Disable dynamic in-memory tools")
    parser.add_argument("--version", action="store_true", help="Show installed version")

    args = parser.parse_args(argv)
    if args.version:
        print(f"J_engine Core v{__version__}")
        return 0

    engine = _build_engine(args.config)
    if args.agent:
        engine.set_agent(args.agent)

    if args.list_agents:
        _print_agents(engine)
        return 0

    # Local import: keeps this CLI isolated from platform unless used.
    import importlib

    def _load_platform():
        interpreter_mod = importlib.import_module("jl_platform.core.interpreter")
        forge_mod = importlib.import_module("jl_platform.core.tools.PrivilegedMemoryForge")
        return (
            getattr(interpreter_mod, "InterpreterSession"),
            getattr(forge_mod, "PrivilegedMemoryForge"),
        )

    try:
        InterpreterSession, PrivilegedMemoryForge = _load_platform()
    except Exception:
        # Support running from a source checkout without requiring users to set PYTHONPATH.
        import sys
        from pathlib import Path

        repo_src = Path(__file__).resolve().parent.parent / "src"
        if repo_src.exists():
            sys.path.insert(0, str(repo_src))
        InterpreterSession, PrivilegedMemoryForge = _load_platform()

    memory_forge = None if args.no_forge else PrivilegedMemoryForge()
    session = InterpreterSession(
        engine=engine,
        max_steps=max(1, int(args.max_steps)),
        memory_forge=memory_forge,
    )
    return _repl(
        session,
        show_trace=bool(args.trace),
        allow_bias_redirect=bool(args.allow_bias_redirect),
        auto_approve=bool(args.auto_approve),
    )


if __name__ == "__main__":
    raise SystemExit(main())
