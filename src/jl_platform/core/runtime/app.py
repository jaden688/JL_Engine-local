"""Licensed under the Apache License, Version 2.0. See LICENSE.md and NOTICE."""

from __future__ import annotations

from typing import Any, Dict, Optional

from jl_platform.core.engine import CoreEngine
from jl_platform.core.models import CoreInput, CoreOutput, HostContext
from jl_platform.core.tools.registry import ToolRegistry
from jl_platform.core.util.logging import get_logger

logger = get_logger(__name__)


class PlatformApp:
    """
    PlatformApp wires a CoreEngine instance to a specific host adapter and tool registry.
    """

    def __init__(self, host_adapter, engine: Optional[CoreEngine] = None):
        self.host_adapter = host_adapter
        self.engine = engine or CoreEngine()
        self.registry = ToolRegistry()
        from jl_platform.core.tools.builtin import register_core_tools

        register_core_tools(self.registry)
        self.host_adapter.register_tools(self.registry)
        host_tool_specs = self.registry.list_specs()
        self.host_context = self.host_adapter.build_context({}, host_tool_specs)

    # Public API ------------------------------------------------------- #
    def register_agent(
        self, agent_id: str, agent: Any, initial_state: Optional[Dict[str, Any]] = None
    ):
        self.engine.register_agent(agent_id, agent, initial_state=initial_state)

    def process(
        self, agent_id: str, text: str | None = None, events=None, context=None
    ) -> CoreOutput:
        core_input = CoreInput(agent_id=agent_id, text=text, events=events, context=context)
        return self.engine.process(core_input, self.host_context, self.registry)

    def process_host(self, agent_id: str, text: str | None = None, events=None, context=None):
        output = self.process(agent_id, text=text, events=events, context=context)
        return self.host_adapter.postprocess(output)

    def tick(self, dt: float = 0.1):
        return self.engine.tick(dt, self.host_context, self.registry)

    def get_state(self, agent_id: str) -> Dict[str, Any]:
        return self.engine.get_state(agent_id)
