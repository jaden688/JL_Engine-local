from __future__ import annotations

from jl_platform.core.models import ToolSpec


def _action_tool(payload: dict) -> dict:
    target = payload.get("target", "player")
    action = payload.get("action", "respond")
    return {"performed": f"{action} at {target}", "status": "ok"}


def register_local_tools(registry) -> None:
    registry.register(
        ToolSpec(
            name="local_action",
            description="Dispatch a local action against the world state.",
            input_schema={
                "type": "object",
                "properties": {"action": {"type": "string"}, "target": {"type": "string"}},
            },
            output_schema={
                "type": "object",
                "properties": {"performed": {"type": "string"}, "status": {"type": "string"}},
            },
        ),
        _action_tool,
    )


register_jl_agent_tools = register_local_tools
