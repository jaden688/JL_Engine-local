from __future__ import annotations

import argparse
import os
import shutil
from pathlib import Path

from jl_platform.core.safety import ALLOW_NETWORK
from jl_platform.core.util.logging import get_logger
from jl_platform.sdk.client import HOST_REGISTRY

logger = get_logger(__name__)

ROOT = Path(__file__).resolve().parents[2]
HOSTS_DIR = ROOT / "jl_platform" / "hosts"
TEMPLATE_DIR = HOSTS_DIR / "templates" / "host_skeleton"


def list_hosts():
    for name in sorted(HOST_REGISTRY.keys()):
        print(name)


def doctor():
    print("JL Platform Doctor")
    print(f"- network_allowed: {ALLOW_NETWORK}")
    print(f"- available_hosts: {', '.join(sorted(HOST_REGISTRY.keys()))}")
    print(f"- cwd: {Path.cwd()}")


def init_host(name: str):
    target = HOSTS_DIR / name
    if target.exists():
        raise SystemExit(f"Host '{name}' already exists at {target}")
    shutil.copytree(TEMPLATE_DIR, target)
    for path in target.rglob("*"):
        if path.is_file():
            text = path.read_text()
            text = text.replace("host_skeleton", name)
            path.write_text(text)
    print(f"Initialized host '{name}' at {target}")


def run_interpreter(argv=None):
    from jl_engine_cli.main import main as unified_main

    print("Forwarding to the unified JL Engine console.")
    return unified_main(argv)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="jl", description="JL Platform CLI")
    sub = parser.add_subparsers(dest="command")

    sub.add_parser("list", help="List resources").add_argument("resource", choices=["hosts"])

    sub.add_parser("doctor", help="Verify installation")

    init_p = sub.add_parser("init", help="Scaffold a new host")
    init_p.add_argument("resource", choices=["host"])
    init_p.add_argument("name")

    sub.add_parser("interpreter", help="Start local interpreter loop")

    return parser


def main(argv=None):
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command == "list" and args.resource == "hosts":
        list_hosts()
        return
    if args.command == "doctor":
        doctor()
        return
    if args.command == "init" and args.resource == "host":
        init_host(args.name)
        return
    if args.command == "interpreter":
        return run_interpreter()
    parser.print_help()


if __name__ == "__main__":
    main()
