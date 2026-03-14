#!/usr/bin/env python3
from __future__ import annotations

# Legacy import shim. Canonical implementation now lives in modules/cc.py.
from modules.cc import build_parser, main, print_result, repl, run_command


if __name__ == "__main__":
    raise SystemExit(main())
