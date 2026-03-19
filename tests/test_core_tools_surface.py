from __future__ import annotations

from jl_platform.core.tools.builtin import register_core_tools
from jl_platform.core.tools.registry import ToolRegistry


def test_core_tools_expose_shell_and_commissioner() -> None:
    registry = ToolRegistry()

    register_core_tools(registry, allow_unsafe=True)

    tool_names = {spec.name for spec in registry.list_specs()}
    assert "run_shell" in tool_names
    assert "bridge_local" in tool_names
    assert "run_cc_command" in tool_names
