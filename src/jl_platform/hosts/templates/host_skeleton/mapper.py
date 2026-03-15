from jl_platform.core.models import CoreInput, HostContext, ToolSpec
from jl_platform.hosts.base import HostAdapter


class SkeletonHostAdapter(HostAdapter):
    name = "host_skeleton"

    def build_context(self, config, tool_specs: list[ToolSpec]) -> HostContext:
        return HostContext(
            host_type=config.get("name", self.name),
            capabilities={"mode": "offline"},
            tool_specs=tool_specs,
            policies={},
        )

    def map_input(self, agent_id: str, text=None, events=None, context=None) -> CoreInput:
        return CoreInput(
            agent_id=agent_id, text=text or "", events=events or [], context=context or {}
        )

    def register_tools(self, registry) -> None:
        from .tools import register_tools as _register_tools

        _register_tools(registry)

    def postprocess(self, output):
        from .outputs import format_output

        return format_output(output)
