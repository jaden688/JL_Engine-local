from __future__ import annotations

import json
from pathlib import Path

from jl_platform.core.quest_runtime import FatQuestRuntime


def test_persist_agent_writes_generated_folder_and_registry_entry(tmp_path: Path):
    runtime = FatQuestRuntime()
    runtime._agents_dir = tmp_path / "agents"
    runtime._generated_agents_dir = runtime._agents_dir / "generated"
    runtime._registry_path = runtime._agents_dir / "JL_Agents.mpf.json"

    payload = {
        "identity": {
            "name": "Generated Test Agent",
            "tags": ["generated", "test"],
        }
    }

    path = runtime._persist_agent("Generated Test Agent", payload)

    assert path == runtime._generated_agents_dir / "Generated_Test_Agent.json"
    assert path.exists()

    registry = json.loads(runtime._registry_path.read_text(encoding="utf-8"))
    entry = registry["Generated Test Agent"]
    assert entry["jl_agent_file"] == "generated/Generated_Test_Agent.json"
    assert entry["classification"] == "generated"
    assert entry["tags"] == ["generated", "test"]


def test_list_mpf_agents_exposes_classification(tmp_path: Path):
    agents_dir = tmp_path / "agents"
    generated_dir = agents_dir / "generated"
    generated_dir.mkdir(parents=True, exist_ok=True)
    registry_path = agents_dir / "JL_Agents.mpf.json"
    registry_path.write_text(
        json.dumps(
            {
                "Generated Test Agent": {
                    "jl_agent_file": "generated/Generated_Test_Agent.json",
                    "default_memory_mode": "HYBRID",
                    "default_backend_id": "ollama-local",
                    "drive_type": None,
                    "classification": "generated",
                    "tags": ["generated", "test"],
                }
            },
            indent=2,
            ensure_ascii=True,
        ),
        encoding="utf-8",
    )
    (generated_dir / "Generated_Test_Agent.json").write_text("{}", encoding="utf-8")

    runtime = FatQuestRuntime()
    runtime._agents_dir = agents_dir
    runtime._generated_agents_dir = generated_dir
    runtime._registry_path = registry_path

    agents = runtime.list_mpf_agents()

    assert len(agents) == 1
    assert agents[0]["classification"] == "generated"
    assert Path(agents[0]["path"]).name == "Generated_Test_Agent.json"
    assert Path(agents[0]["path"]).parent.name == "generated"


def test_load_registry_supports_jl_agents_mpf_variant(tmp_path: Path):
    runtime = FatQuestRuntime()
    runtime._agents_dir = tmp_path / "agents"
    runtime._generated_agents_dir = runtime._agents_dir / "generated"
    runtime._registry_path = runtime._agents_dir / "JL_Agents.mpf.json"
    runtime._registry_path_alt = runtime._agents_dir / "JL_Agents.mpf"
    runtime._agents_dir.mkdir(parents=True, exist_ok=True)

    runtime._registry_path_alt.write_text(
        json.dumps({"SparkByte": {"jl_agent_file": "SparkByte.json"}}, indent=2),
        encoding="utf-8",
    )

    registry = runtime._load_registry()
    assert registry["SparkByte"]["jl_agent_file"] == "SparkByte.json"


def test_persist_writes_both_registry_formats(tmp_path: Path):
    runtime = FatQuestRuntime()
    runtime._agents_dir = tmp_path / "agents"
    runtime._generated_agents_dir = runtime._agents_dir / "generated"
    runtime._registry_path = runtime._agents_dir / "JL_Agents.mpf.json"
    runtime._registry_path_alt = runtime._agents_dir / "JL_Agents.mpf"

    runtime._persist_agent("Generated Test Agent", {"identity": {"name": "Generated Test Agent"}})

    assert runtime._registry_path.exists()
    assert runtime._registry_path_alt.exists()
