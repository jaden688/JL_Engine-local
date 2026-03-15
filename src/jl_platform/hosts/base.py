from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Dict, List

from jl_platform.core.models import CoreInput, HostContext, ToolSpec
from jl_platform.core.tools.registry import ToolRegistry


class HostAdapter(ABC):
    name: str

    @abstractmethod
    def build_context(self, config: Dict, tool_specs: List[ToolSpec]) -> HostContext: ...

    @abstractmethod
    def map_input(self, agent_id: str, text=None, events=None, context=None) -> CoreInput: ...

    @abstractmethod
    def register_tools(self, registry: ToolRegistry) -> None: ...

    @abstractmethod
    def postprocess(self, output) -> Dict: ...
