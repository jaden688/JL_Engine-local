from __future__ import annotations

from typing import Any, Callable, Dict, List, Optional

from pydantic import BaseModel, Field


class CoreInput(BaseModel):
    agent_id: str
    text: Optional[str] = None
    events: Optional[List[Dict[str, Any]]] = None
    context: Optional[Dict[str, Any]] = None
    media_refs: Optional[List[Dict[str, Any]]] = None


class ToolSpec(BaseModel):
    name: str
    description: str
    input_schema: Dict[str, Any] = Field(default_factory=dict)
    output_schema: Dict[str, Any] = Field(default_factory=dict)


class HostContext(BaseModel):
    host_type: str
    capabilities: Dict[str, Any] = Field(default_factory=dict)
    tool_specs: List[ToolSpec] = Field(default_factory=list)
    policies: Dict[str, Any] = Field(default_factory=dict)
    deterministic_mode: bool = False
    seed: Optional[int] = None
    privacy_mode: str = "local"


class CoreOutput(BaseModel):
    agent_id: str
    type: str
    payload: Dict[str, Any]
    memory_writes: List[Dict[str, Any]] = Field(default_factory=list)
    state_delta: Dict[str, Any] = Field(default_factory=dict)
    trace_id: str
    warnings: List[str] = Field(default_factory=list)


# Convenience type alias for tool handlers
ToolHandler = Callable[[Dict[str, Any]], Dict[str, Any]]
