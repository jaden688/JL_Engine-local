#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import shlex
import subprocess
import sys
import time
from typing import Any


def run_command(
    cmd: str | list[str],
    *,
    cwd: str | None = None,
    timeout: float | None = None,
    shell: bool = True,
) -> dict[str, Any]:
    start = time.perf_counter()
    try:
        completed = subprocess.run(
            cmd,
            cwd=cwd or None,
            capture_output=True,
            text=True,
            timeout=timeout,
            shell=shell,
        )
        duration_ms = round((time.perf_counter() - start) * 1000.0, 2)
        return {
            "ok": completed.returncode == 0,
            "returncode": completed.returncode,
            "stdout": completed.stdout or "",
            "stderr": completed.stderr or "",
            "duration_ms": duration_ms,
            "cwd": os.path.abspath(cwd or os.getcwd()),
            "command": cmd,
        }
    except subprocess.TimeoutExpired as exc:
        duration_ms = round((time.perf_counter() - start) * 1000.0, 2)
        return {
            "ok": False,
            "returncode": None,
            "stdout": exc.stdout or "",
            "stderr": exc.stderr or f"Timed out after {timeout}s",
            "duration_ms": duration_ms,
            "cwd": os.path.abspath(cwd or os.getcwd()),
            "command": cmd,
            "error": "timeout",
        }
    except Exception as exc:
        duration_ms = round((time.perf_counter() - start) * 1000.0, 2)
        return {
            "ok": False,
            "returncode": None,
            "stdout": "",
            "stderr": str(exc),
            "duration_ms": duration_ms,
            "cwd": os.path.abspath(cwd or os.getcwd()),
            "command": cmd,
            "error": "exception",
        }


def print_result(result: dict[str, Any], as_json: bool) -> None:
    if as_json:
        print(json.dumps(result, indent=2, ensure_ascii=False))
        return
    if result.get("stdout"):
        print(result["stdout"], end="" if result["stdout"].endswith("\n") else "\n")
    if result.get("stderr"):
        print(result["stderr"], end="" if result["stderr"].endswith("\n") else "\n", file=sys.stderr)
    print(
        f"[CC] rc={result.get('returncode')} "
        f"ok={result.get('ok')} "
        f"duration_ms={result.get('duration_ms')}"
    )


def repl(cwd: str | None, timeout: float | None, as_json: bool, shell: bool) -> int:
    print("CC REPL mode. Type 'exit' or 'quit' to stop.")
    while True:
        try:
            line = input("CC> ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            return 0
        if not line:
            continue
        if line.lower() in {"exit", "quit"}:
            return 0
        cmd = line if shell else shlex.split(line)
        result = run_command(cmd, cwd=cwd, timeout=timeout, shell=shell)
        print_result(result, as_json)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="CC",
        description="Local command runner for computer control.",
    )
    parser.add_argument(
        "command",
        nargs=argparse.REMAINDER,
        help="Command to execute. Example: python CC.py git status",
    )
    parser.add_argument("--cwd", default=None, help="Working directory for command execution.")
    parser.add_argument(
        "--timeout",
        type=float,
        default=None,
        help="Timeout in seconds.",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Print structured JSON output.",
    )
    parser.add_argument(
        "--repl",
        action="store_true",
        help="Interactive command mode.",
    )
    parser.add_argument(
        "--no-shell",
        action="store_true",
        help="Disable shell execution (uses tokenized argv).",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    shell = not args.no_shell

    if args.repl:
        return repl(args.cwd, args.timeout, args.json, shell=shell)

    if not args.command:
        parser.print_help()
        return 1

    cmd_str = " ".join(args.command).strip()
    if not cmd_str:
        parser.print_help()
        return 1
    cmd: str | list[str] = cmd_str if shell else shlex.split(cmd_str)

    result = run_command(cmd, cwd=args.cwd, timeout=args.timeout, shell=shell)
    print_result(result, args.json)
    if result.get("ok"):
        return 0
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
