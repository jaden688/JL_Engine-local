from __future__ import annotations

from pathlib import Path

from jl_platform.core.tools.forge import ToolForge


def test_tool_forge_starts_clean_without_index(tmp_path: Path):
    runtime_dir = tmp_path / "tools_runtime"

    forge = ToolForge(runtime_dir)
    listed = forge.list_tools()

    assert runtime_dir.exists()
    assert listed["status"] == "ok"
    assert listed["tools"] == []
    assert not (runtime_dir / "index.json").exists()


def test_tool_forge_recovers_from_corrupt_index(tmp_path: Path):
    runtime_dir = tmp_path / "tools_runtime"
    runtime_dir.mkdir(parents=True, exist_ok=True)
    (runtime_dir / "index.json").write_text("{not valid json", encoding="utf-8")

    forge = ToolForge(runtime_dir)
    listed = forge.list_tools()

    assert listed["status"] == "ok"
    assert listed["tools"] == []


def test_tool_forge_can_create_run_and_delete_from_empty_runtime(tmp_path: Path):
    runtime_dir = tmp_path / "tools_runtime"
    forge = ToolForge(runtime_dir)

    created = forge.create_tool(
        "tmp_echo",
        "def run(payload):\n    return {'echo': payload.get('value')}",
        description="echo test tool",
    )
    listed = forge.list_tools()
    result = forge.run_tool("tmp_echo", {"value": "ok"})
    deleted = forge.delete_tool("tmp_echo")

    assert created["status"] == "ok"
    assert (runtime_dir / "index.json").exists()
    assert [tool["name"] for tool in listed["tools"]] == ["tmp_echo"]
    assert result["status"] == "ok"
    assert result["result"] == {"echo": "ok"}
    assert deleted == {"status": "ok", "deleted": "tmp_echo"}
