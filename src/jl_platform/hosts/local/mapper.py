from __future__ import annotations

import os
from typing import Any, Dict, List, Optional

from jl_platform.core.models import CoreInput, HostContext, ToolSpec
from jl_platform.core.util.logging import get_logger
from jl_platform.hosts.base import HostAdapter

logger = get_logger(__name__)


def map_to_core(
    agent_id: str, text: Optional[str], events: Optional[List[Dict[str, Any]]] = None, context=None
) -> CoreInput:
    return CoreInput(
        agent_id=agent_id,
        text=text,
        events=events or [],
        context=context or {},
    )


class LocalHostAdapter(HostAdapter):
    name = os.environ.get("COMPUTERNAME", "my-computer").strip() or "my-computer"

    def build_context(self, config: Dict, tool_specs: List[ToolSpec]) -> HostContext:
        capabilities = {"mode": "offline", "tools": [spec.name for spec in tool_specs]}
        return HostContext(
            host_type=self.name,
            capabilities=capabilities,
            tool_specs=tool_specs,
            policies={"network": "disabled"},
            privacy_mode="local",
        )

    def map_input(self, agent_id: str, text=None, events=None, context=None) -> CoreInput:
        return map_to_core(agent_id, text=text, events=events, context=context)

    def register_tools(self, registry) -> None:
        from jl_platform.hosts.local.tools import register_local_tools

        register_local_tools(registry)

    def postprocess(self, output) -> Dict[str, Any]:
        from jl_platform.hosts.local.outputs import to_local_decision

        return to_local_decision(output).dict()
