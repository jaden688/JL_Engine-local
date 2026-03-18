from __future__ import annotations

from pydantic import BaseModel, Field

from jl_platform.core.models import CoreOutput
from jl_platform.core.util.validation import ensure_json_dict


class LocalDecision(BaseModel):
    dialogue: str | None = None
    action: str | None = None
    confidence: float = 0.5
    state_delta: dict = Field(default_factory=dict)
    memory_writes: list = Field(default_factory=list)
    trace_id: str


def to_local_decision(core_output: CoreOutput) -> LocalDecision:
    payload = ensure_json_dict(core_output.payload)
    return LocalDecision(
        dialogue=payload.get("text"),
        action=payload.get("suggested_action") or "talk",
        confidence=payload.get("confidence", 0.7),
        state_delta=core_output.state_delta,
        memory_writes=core_output.memory_writes,
        trace_id=core_output.trace_id,
    )
