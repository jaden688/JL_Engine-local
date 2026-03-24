"""
CLI entrypoints for JL Engine.
- jl-engine-gui: launches Tkinter UI
- jl-engine-api: launches FastAPI backend
"""

from __future__ import annotations

import argparse
import json
import os


def _run_code(goal: str, model: str | None = None) -> None:
    from tools.tool_registry import get_interpreter_runner
    from tools.coding.coordinator import run_coding_task

    runner = get_interpreter_runner()
    result = run_coding_task(user_goal=goal, backend_runner=runner, model=model)
    print(json.dumps(result, indent=2))


def _resume() -> None:
    from tools.coding.session import latest_session
    s = latest_session()
    if not s:
        print("No sessions found.")
        return
    print(f"Latest session: {s.id} -> {s.path}")
    score = (s.path / "scorecard.json")
    if score.exists():
        print(score.read_text(encoding="utf-8"))


def _status() -> None:
    from tools.coding.session import latest_session
    s = latest_session()
    if not s:
        print("No sessions found.")
        return
    score = (s.path / "scorecard.json")
    print(f"Session: {s.id}")
    print(score.read_text(encoding="utf-8") if score.exists() else "(no scorecard)")


def _explain() -> None:
    from tools.coding.search_tool import repo_map
    from tools.coding.deps_tool import deps_detect
    print(json.dumps({"repo": repo_map({}), "deps": deps_detect({})}, indent=2))


def run_api() -> None:
    """Start the FastAPI server for the persona API."""
    import uvicorn

    port = int(os.environ.get("PORT", "8080"))
    uvicorn.run("JL_Engine.api_server:app", host="0.0.0.0", port=port, reload=False)


def run_gui() -> None:
    """Start the desktop GUI."""
    from JL_Engine.main_app import main

    main()


def main() -> None:
    parser = argparse.ArgumentParser(prog="jl", description="JL Engine CLI")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_api = sub.add_parser("api", help="Run FastAPI backend")
    p_api.set_defaults(fn=lambda args: run_api())

    p_gui = sub.add_parser("gui", help="Run desktop GUI")
    p_gui.set_defaults(fn=lambda args: run_gui())

    p_code = sub.add_parser("code", help="Run Tier-1 coding harness")
    p_code.add_argument("goal", type=str, help="Goal/instruction for the coding harness")
    p_code.add_argument("--model", type=str, default=None, help="Optional model override")
    p_code.set_defaults(fn=lambda args: _run_code(args.goal, args.model))

    p_resume = sub.add_parser("resume", help="Show latest session")
    p_resume.set_defaults(fn=lambda args: _resume())

    p_status = sub.add_parser("status", help="Show latest scorecard")
    p_status.set_defaults(fn=lambda args: _status())

    p_explain = sub.add_parser("explain", help="Show repo map + tool availability")
    p_explain.set_defaults(fn=lambda args: _explain())

    args = parser.parse_args()
    args.fn(args)


if __name__ == "__main__":
    main()
