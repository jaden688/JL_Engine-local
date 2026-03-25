from __future__ import annotations

import importlib.util
from functools import lru_cache
from pathlib import Path
from types import ModuleType

PACKAGE_ROOT = Path(__file__).resolve().parents[2]
LEGACY_SERVER_PATH = PACKAGE_ROOT / "JL-Engine-local.py"


def _load_module(module_name: str, path: Path) -> ModuleType:
    spec = importlib.util.spec_from_file_location(module_name, path)
    if spec is None or spec.loader is None:
        raise ImportError(f"Could not load module spec for '{path}'.")

    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@lru_cache(maxsize=1)
def load_legacy_server() -> ModuleType:
    if not LEGACY_SERVER_PATH.exists():
        raise FileNotFoundError(
            f"Legacy MCP server script not found at '{LEGACY_SERVER_PATH}'."
        )
    return _load_module("_jl_engine_local_legacy_server", LEGACY_SERVER_PATH)
