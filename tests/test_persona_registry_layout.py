from __future__ import annotations

import json
from pathlib import Path

from jl_engine_core.engine_core import EngineConfig
from jl_platform.core.quest_runtime import FatQuestRuntime


def test_engine_config_uses_agents_registry_path():
    registry_path = Path(EngineConfig().mpf_registry_file).resolve()

    assert registry_path.as_posix().endswith("/jl_engine_core/data/agents/JL_Agents.mpf.json")


def test_root_personas_mirror_is_gone():
    root_personas = Path(__file__).resolve().parents[1] / "personas"

    assert not root_personas.exists()


def test_registry_marks_mothership_agents_as_fat_agents():
    registry_path = (
        Path(__file__).resolve().parents[1]
        / "jl_engine_core"
        / "data"
        / "agents"
        / "JL_Agents.mpf.json"
    )
    registry = json.loads(registry_path.read_text(encoding="utf-8"))

    for agent_name, relative_path in (
        ("SparkByte", "fat_agents/SparkByte_Full.json"),
        ("Slappy", "fat_agents/Slappy_Full.json"),
        ("The Gremlin", "fat_agents/The_Gremlin_Full.json"),
        ("Supervisor", "fat_agents/SparkByte_Full.json"),
    ):
        entry = registry[agent_name]
        assert entry["jl_agent_file"] == relative_path
        assert entry["classification"] == "fat_agent"


def test_runtime_lists_fat_agent_classification():
    runtime = FatQuestRuntime()
    agents = {entry["name"]: entry for entry in runtime.list_mpf_agents()}

    assert agents["SparkByte"]["classification"] == "fat_agent"
    assert agents["SparkByte"]["jl_agent_file"] == "fat_agents/SparkByte_Full.json"
    assert agents["Slappy"]["classification"] == "fat_agent"
    assert agents["The Gremlin"]["classification"] == "fat_agent"


def test_registry_marks_jl_agents_as_jl_agents():
    registry_path = (
        Path(__file__).resolve().parents[1]
        / "jl_engine_core"
        / "data"
        / "agents"
        / "JL_Agents.mpf.json"
    )
    registry = json.loads(registry_path.read_text(encoding="utf-8"))

    for agent_name, relative_path in (
        ("Cold Outreach Assistant", "jl_agents/Cold_Outreach_Assistant_Full.json"),
        ("SaaS Copywriter", "jl_agents/SaaS_Copywriter_Full.json"),
        ("Brand Voice Generator", "jl_agents/Brand_Voice_Generator_Full.json"),
        ("Startup Pitch Writer", "jl_agents/Startup_Pitch_Writer_Full.json"),
        ("YouTube Scriptwriter", "jl_agents/YouTube_Scriptwriter_Full.json"),
        ("Forgebinder", "jl_agents/Forgebinder.json"),
        ("ForgeWorks", "jl_agents/ForgeWorks.json"),
    ):
        entry = registry[agent_name]
        assert entry["jl_agent_file"] == relative_path
        assert entry["classification"] == "jl_agent"
