from __future__ import annotations

import importlib
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))


def test_legacy_import_shims_resolve():
    agent_cli = importlib.import_module("jl_engine_core.agent_cli")
    api_app = importlib.import_module("jl_engine_core.api_app")
    engine_core = importlib.import_module("jl_engine_core.engine_core")
    legacy_cli = importlib.import_module("jl_engine_core.cli")
    headless_cli = importlib.import_module("jl_engine_core.headless_cli")
    forge_module = importlib.import_module("jl_platform.core.tools.PrivilegedMemoryForge")

    assert callable(agent_cli.main)
    assert callable(api_app.create_app)
    assert engine_core.JLEngineCore is not None
    assert callable(legacy_cli.main)
    assert legacy_cli.HeadlessConsole is not None
    assert callable(headless_cli.main)
    assert forge_module.PrivilegedMemoryForge is not None


def test_new_package_imports_resolve():
    api_app = importlib.import_module("jl_engine.api_app")
    agent_cli = importlib.import_module("jl_engine.cli.agent_cli")

    assert api_app.app is not None
    assert callable(agent_cli.main)


def test_engine_uses_bundled_defaults():
    from jl_engine_core import JLEngineCore

    engine = JLEngineCore()

    assert engine.current_agent_name in engine.mpf_profiles
    assert len(engine.mpf_profiles) > 0
