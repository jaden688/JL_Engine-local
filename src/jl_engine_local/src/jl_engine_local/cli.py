from __future__ import annotations

import argparse
import os
from pathlib import Path
from typing import Sequence

from . import __version__


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="jl-engine-local",
        description="Run the JL Engine local MCP server.",
    )
    parser.add_argument(
        "--engine-root",
        type=Path,
        help="Override the JL Engine repo root used by the server runtime.",
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"%(prog)s {__version__}",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.engine_root:
        os.environ["JL_ENGINE_ROOT"] = str(args.engine_root.expanduser().resolve())

    from .server import run

    run()
    return 0
