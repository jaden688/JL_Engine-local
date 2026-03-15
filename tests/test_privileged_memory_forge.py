from __future__ import annotations

import jl_platform.core.tools.PrivilegedMemoryForge as memory_forge_module
from jl_platform.core.tools.PrivilegedMemoryForge import PrivilegedMemoryForge


def _install_fake_clock(monkeypatch, start: float = 100.0) -> dict[str, float]:
    state = {"now": float(start)}

    def fake_time() -> float:
        return float(state["now"])

    monkeypatch.setattr(memory_forge_module.time, "time", fake_time)
    return state


def test_memory_forge_deletes_tool_after_single_use(monkeypatch):
    monkeypatch.setenv("JL_RAM_TOOL_UNUSED_TTL_SECONDS", "0")
    forge = PrivilegedMemoryForge()

    created = forge.create_tool(
        "tmp_math",
        "def run(payload):\n    return {'sum': payload.get('a', 0) + payload.get('b', 0)}",
        description="temporary adder",
    )
    result = forge.run_tool("tmp_math", {"a": 2, "b": 3})
    listed = forge.list_tools()

    assert created["status"] == "ok"
    assert result["status"] == "ok"
    assert result["result"] == {"sum": 5}
    assert result["lifecycle"]["deleted_after_use"] is True
    assert listed["tools"] == []
    assert "tmp_math" in listed["recently_deleted"]


def test_memory_forge_expires_unused_tools_on_listing(monkeypatch):
    monkeypatch.setenv("JL_RAM_TOOL_UNUSED_TTL_SECONDS", "5")
    monkeypatch.setenv("JL_RAM_TOOL_MAX_ACTIVE", "8")
    clock = _install_fake_clock(monkeypatch)
    forge = PrivilegedMemoryForge()

    created = forge.create_tool(
        "tmp_idle",
        "def run(payload):\n    return payload",
        description="idle tool",
    )
    clock["now"] = 106.0
    listed = forge.list_tools()

    assert created["status"] == "ok"
    assert listed["tools"] == []
    assert listed["expired_unused"] == ["tmp_idle"]
    assert "tmp_idle" in listed["recently_deleted"]
    assert forge._recently_deleted["tmp_idle"]["reason"] == "expired_unused"


def test_memory_forge_evicts_oldest_tool_when_over_cap(monkeypatch):
    monkeypatch.setenv("JL_RAM_TOOL_UNUSED_TTL_SECONDS", "0")
    monkeypatch.setenv("JL_RAM_TOOL_MAX_ACTIVE", "2")
    clock = _install_fake_clock(monkeypatch)
    forge = PrivilegedMemoryForge()

    forge.create_tool("tmp_one", "def run(payload):\n    return 1")
    clock["now"] = 101.0
    forge.create_tool("tmp_two", "def run(payload):\n    return 2")
    clock["now"] = 102.0
    created = forge.create_tool("tmp_three", "def run(payload):\n    return 3")
    listed = forge.list_tools()

    assert created["status"] == "ok"
    assert created["lifecycle"]["evicted_for_capacity"] == ["tmp_one"]
    assert sorted(tool["name"] for tool in listed["tools"]) == ["tmp_three", "tmp_two"]
    assert "tmp_one" in listed["recently_deleted"]
    assert forge._recently_deleted["tmp_one"]["reason"] == "capacity_eviction"


def test_memory_forge_trims_recently_deleted_history(monkeypatch):
    monkeypatch.setenv("JL_RAM_TOOL_UNUSED_TTL_SECONDS", "0")
    monkeypatch.setenv("JL_RAM_TOOL_MAX_RECENTLY_DELETED", "1")
    clock = _install_fake_clock(monkeypatch)
    forge = PrivilegedMemoryForge()

    forge.create_tool("tmp_old", "def run(payload):\n    return 'old'")
    forge.run_tool("tmp_old", {})
    clock["now"] = 101.0
    forge.create_tool("tmp_new", "def run(payload):\n    return 'new'")
    forge.run_tool("tmp_new", {})
    listed = forge.list_tools()

    assert listed["recently_deleted"] == ["tmp_new"]
    assert "tmp_old" not in listed["recently_deleted"]
    assert len(forge._recently_deleted) == 1
