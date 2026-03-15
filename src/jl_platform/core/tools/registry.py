from __future__ import annotations

import json
from typing import Callable, Dict, List

from jl_platform.core.models import ToolHandler, ToolSpec
from jl_platform.core.util.logging import get_logger, new_trace_id

logger = get_logger(__name__)


class ToolRegistry:
    """Lightweight registry used by hosts to expose actions to the core."""

    def __init__(self) -> None:
        self._specs: Dict[str, ToolSpec] = {}
        self._handlers: Dict[str, ToolHandler] = {}

    def register(self, spec: ToolSpec, handler: ToolHandler) -> None:
        self._specs[spec.name] = spec
        self._handlers[spec.name] = handler
        logger.debug("Registered tool %s", spec.name)

    def list_specs(self) -> List[ToolSpec]:
        return list(self._specs.values())

    def call(self, name: str, payload: Dict) -> Dict:
        if name not in self._handlers:
            raise KeyError(f"Tool '{name}' not registered")
        handler = self._handlers[name]
        trace = new_trace_id()
        logger.debug("Calling tool %s trace=%s payload=%s", name, trace, json.dumps(payload))
        result = handler(payload)
        logger.debug("Tool %s trace=%s result=%s", name, trace, json.dumps(result))
        return result
