from jl_platform.core.models import ToolSpec


def register_tools(registry) -> None:
    registry.register(
        ToolSpec(
            name="echo",
            description="Echoes input text for quick smoke tests.",
            input_schema={"type": "object", "properties": {"text": {"type": "string"}}},
            output_schema={"type": "object", "properties": {"echo": {"type": "string"}}},
        ),
        lambda payload: {"echo": payload.get("text", "")},
    )
