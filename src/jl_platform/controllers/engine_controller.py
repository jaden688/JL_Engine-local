"""Engine controller for JL Platform UI orchestration."""

from __future__ import annotations

from jl_engine_core.engine_core import EngineConfig, JLEngineCore
from jl_platform.core.util.logging import get_logger

logger = get_logger(__name__)


class EngineController:
    """Controller for initializing and accessing the core engine."""

    def __init__(self, config: EngineConfig | None = None) -> None:
        self.config = config or EngineConfig()
        self._engine: JLEngineCore | None = None

    def build_engine(self) -> JLEngineCore:
        """Instantiate the engine core and cache it."""
        if self._engine is None:
            logger.info("[EngineController] Initializing JL Engine core.")
            self._engine = JLEngineCore(self.config)
        return self._engine

    def get_engine(self) -> JLEngineCore:
        """Return the cached engine instance (building if needed)."""
        return self.build_engine()
