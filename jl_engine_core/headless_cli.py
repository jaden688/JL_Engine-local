from __future__ import annotations

from typing import Optional


def main(argv: Optional[list[str]] = None) -> int:
    from jl_engine_cli.main import main as unified_main

    print("Forwarding legacy jl_engine_core.headless_cli to the unified JL Engine console.")
    return unified_main(list(argv or []))


if __name__ == "__main__":
    raise SystemExit(main())
