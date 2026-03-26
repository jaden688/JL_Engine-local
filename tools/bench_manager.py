"""Simple bench/watchdog runner for this repository.

This script watches source, UI, docs, config, and support files for changes and re-runs the test suite.
It is intended as a lightweight "bench manager" / "silent watchdog" to keep the
repo in a ship-ready state while you work.

Usage:
  python tools/bench_manager.py          # watch and rerun tests on any change
  python tools/bench_manager.py --once  # run tests once and exit

Options:
  --watch=PATH [PATH ...]       Paths to watch (defaults to the main source, UI, docs, config, and support trees)
  --interval SECONDS            Polling interval when watching (default: 1.0)
  --pytest-args ARGS            Extra args to pass to pytest (e.g. "-q --maxfail=1")
  --no-pytest                   Do not run pytest; just watch for changes.
  --quiet                       Minimize output.

If a test run fails, the failure output is printed so you can fix it immediately.
"""

from __future__ import annotations

import argparse
import hashlib
import subprocess
import sys
import time
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Tuple

WATCHABLE_EXTENSIONS = {
    ".bat",
    ".css",
    ".html",
    ".htm",
    ".js",
    ".json",
    ".md",
    ".ps1",
    ".py",
    ".toml",
    ".txt",
    ".yaml",
    ".yml",
}
WATCHABLE_FILENAMES = {
    ".env.example",
    ".gitignore",
    "ARCHITECTURE.md",
    "CONTRIBUTING.md",
    "LICENSE.md",
    "ONBOARDING.md",
    "README.md",
    "SECURITY.md",
    "TROUBLESHOOTING.md",
    "VERSION",
    "launcher.bat",
    "legacy_launchers",
    "pyproject.toml",
    "requirements.txt",
}
WATCH_SKIP_DIRS = {
    ".git",
    ".mypy_cache",
    ".pytest_cache",
    ".self_edit_lab",
    ".self_edit_lab_test",
    ".self_edit_lab_ui_test",
    ".venv",
    ".playwright-cli",
    "__pycache__",
    "human_guidance",
    "j_engine.egg-info",
    "logs",
    "node_modules",
    "tools_runtime",
}


def _iter_watchable_files(paths: Iterable[Path]) -> Iterable[Path]:
    for root in paths:
        if not root.exists():
            continue
        if root.is_file():
            if root.name in WATCHABLE_FILENAMES or root.suffix.lower() in WATCHABLE_EXTENSIONS:
                yield root
            continue
        for p in root.rglob("*"):
            if not p.is_file():
                continue
            if any(part in WATCH_SKIP_DIRS for part in p.parts):
                continue
            if p.name in WATCHABLE_FILENAMES or p.suffix.lower() in WATCHABLE_EXTENSIONS:
                yield p


def _compute_snapshot(paths: Iterable[Path]) -> Dict[Path, float]:
    snapshot: Dict[Path, float] = {}
    for p in _iter_watchable_files(paths):
        try:
            snapshot[p] = p.stat().st_mtime
        except OSError:
            continue
    return snapshot


def _get_changed_files(snapshot: Dict[Path, float], new_snapshot: Dict[Path, float]) -> list[Path]:
    """Return a list of files that were added or modified between snapshots."""
    changed: list[Path] = []
    for p, mtime in new_snapshot.items():
        if snapshot.get(p) != mtime:
            changed.append(p)
    return changed


def _changed(snapshot: Dict[Path, float], new_snapshot: Dict[Path, float]) -> bool:
    if set(snapshot.keys()) != set(new_snapshot.keys()):
        return True
    for p, mtime in new_snapshot.items():
        if snapshot.get(p) != mtime:
            return True
    return False


def _run_pytest(pytest_args: List[str], quiet: bool) -> bool:
    command = [sys.executable, "-m", "pytest"] + pytest_args
    if not quiet:
        print("\n[bench_manager] Running: %s" % " ".join(command))
    proc = subprocess.run(command, capture_output=True, text=True)
    if not quiet:
        sys.stdout.write(proc.stdout)
        sys.stderr.write(proc.stderr)
    return proc.returncode == 0


def _load_signal_patterns(signal_path: Optional[Path]) -> list[str]:
    if not signal_path:
        return []
    try:
        text = signal_path.read_text(encoding="utf-8")
    except Exception:
        return []

    lines = [line.strip() for line in text.splitlines() if line.strip() and not line.strip().startswith("#")]
    return lines


def _scan_for_dangerous_patterns(paths: list[Path], patterns: list[str]) -> list[tuple[Path, str]]:
    hits: list[tuple[Path, str]] = []
    if not patterns:
        return hits

    for p in paths:
        try:
            content = p.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            continue
        for pattern in patterns:
            if pattern in content:
                hits.append((p, pattern))
    return hits


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Bench/watchdog runner for JL Engine")
    parser.add_argument(
        "--watch",
        nargs="*",
        default=[
            "src",
            "jl_engine_core",
            "tests",
            "ui_web",
            "tools",
            "docs",
            "game_integrations",
            "modules",
            "data",
            "README.md",
            "ARCHITECTURE.md",
            "CONTRIBUTING.md",
            "ONBOARDING.md",
            "SECURITY.md",
            "TROUBLESHOOTING.md",
            "LICENSE.md",
            "VERSION",
            ".env.example",
            "pyproject.toml",
            "requirements.txt",
            ".gitignore",
            "launcher.bat",
            "legacy_launchers",
        ],
        help="Paths to watch for changes.",
    )
    parser.add_argument(
        "--interval",
        type=float,
        default=1.0,
        help="Polling interval in seconds when watching.",
    )
    parser.add_argument(
        "--pytest-args",
        default=["-q", "--maxfail=1"],
        nargs="*",
        help="Arguments to pass to pytest.",
    )
    parser.add_argument(
        "--once",
        action="store_true",
        help="Run once and exit (no watching).",
    )
    parser.add_argument(
        "--no-pytest",
        action="store_true",
        help="Only watch for changes without running pytest.",
    )
    parser.add_argument(
        "--stop-on-danger",
        action="store_true",
        help="If a changed file contains a danger pattern, pause and require confirmation before continuing.",
    )
    parser.add_argument(
        "--signal-file",
        type=str,
        default="",
        help="Path to a file containing danger patterns (one per line).",
    )
    parser.add_argument(
        "--quiet",
        action="store_true",
        help="Minimize output.",
    )

    args = parser.parse_args(argv)

    watch_dirs = [Path(p) for p in args.watch]
    if not args.quiet:
        print("[bench_manager] watching", ", ".join(str(p) for p in watch_dirs))

    danger_patterns = _load_signal_patterns(Path(args.signal_file)) if args.signal_file else []

    snapshot = _compute_snapshot(watch_dirs)

    if not args.no_pytest:
        ok = _run_pytest(args.pytest_args, quiet=args.quiet)
        if not ok and args.once:
            return 1

    if args.once:
        return 0

    if args.no_pytest and not args.quiet:
        print("[bench_manager] watching for changes (pytest disabled)")

    try:
        while True:
            time.sleep(args.interval)
            new_snapshot = _compute_snapshot(watch_dirs)
            if _changed(snapshot, new_snapshot):
                changed_files = _get_changed_files(snapshot, new_snapshot)
                snapshot = new_snapshot

                if danger_patterns:
                    hits = _scan_for_dangerous_patterns(changed_files, danger_patterns)
                    if hits:
                        print("\n[bench_manager] DANGER PATTERNS DETECTED in changed files:")
                        for path, pattern in hits:
                            print(f"  - {path}: contains '{pattern}'")
                        if args.stop_on_danger:
                            input("[bench_manager] Press Enter to continue (danger detected)...")

                if not args.quiet:
                    print("\n[bench_manager] change detected, running tests...")
                if not args.no_pytest:
                    _run_pytest(args.pytest_args, quiet=args.quiet)
    except KeyboardInterrupt:
        if not args.quiet:
            print("\n[bench_manager] stopped by user")
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
