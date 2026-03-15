from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


def _forward_to_unified_cli(argv: Optional[list[str]] = None) -> int:
    from jl_engine_cli.main import main as unified_main

    print("Forwarding legacy jl_engine_core.cli to the unified JL Engine console.")
    return unified_main(list(argv or []))


@dataclass
class HeadlessConsole:
    """Compatibility wrapper around the unified chat-first console."""

    config_path: Optional[str] = None

    def run(self) -> int:
        argv: list[str] = []
        if self.config_path:
            argv.extend(["--config", self.config_path])
        return _forward_to_unified_cli(argv)


def main(argv: Optional[list[str]] = None) -> int:
    return _forward_to_unified_cli(argv)


if __name__ == "__main__":  # pragma: no cover - CLI entrypoint
    raise SystemExit(main())
