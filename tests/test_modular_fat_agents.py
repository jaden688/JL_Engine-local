from __future__ import annotations

import json
from pathlib import Path

from jl_engine_core.engine_core import JLEngineCore
from jl_engine_core.modular_agents import get_modular_agent_summary, resolve_modular_agent_payload
from jl_platform.core.quest_runtime import FatQuestRuntime


def test_resolve_modular_sparkbyte_pack_into_runtime_payload() -> None:
    pack_root = Path(__file__).resolve().parents[1] / "jl_engine_core" / "data" / "modular_fat_agent_pack"
    shell_path = pack_root / "fat_agents" / "SparkByte_Full.json"
    payload = json.loads(shell_path.read_text(encoding="utf-8"))

    resolved = resolve_modular_agent_payload(payload, agent_path=shell_path)

    assert resolved["identity"]["name"] == "SparkByte"
    assert resolved["modular"]["loadout_id"] == "default_assistant"
    assert resolved["modular"]["profile_ids"]["tone"] == "sassy_light"
    assert resolved["llm_profiles"]["generic_llm"]["boot_prompt"].startswith("You are SparkByte")
    assert resolved["helpers"][0]["helper_id"] == "option_generator"


def test_engine_can_set_modular_sparkbyte_from_registry() -> None:
    engine = JLEngineCore()

    engine.set_agent("SparkByte Modular")

    summary = get_modular_agent_summary(engine.current_agent_data)
    assert summary is not None
    assert summary["loadout_id"] == "default_assistant"
    assert summary["profile_ids"]["behavior"] == "practical_support"
    assert engine.current_agent_data["identity"]["name"] == "SparkByte"


def test_runtime_lists_modular_agent_summary() -> None:
    runtime = FatQuestRuntime()

    agents = runtime.list_mpf_agents()

    sparkbyte_modular = next(agent for agent in agents if agent["agent_name"] == "SparkByte Modular")
    assert sparkbyte_modular["profile_type"] == "modular_fat_agent"
    assert sparkbyte_modular["modular_summary"]["loadout_id"] == "default_assistant"
