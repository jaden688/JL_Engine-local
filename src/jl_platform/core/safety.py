from __future__ import annotations

import os
from contextlib import contextmanager

from jl_platform.core.util.logging import get_logger

logger = get_logger(__name__)

ALLOW_NETWORK = os.getenv("JL_PLATFORM_ALLOW_NETWORK", "1").lower() in {"1", "true", "yes", "on"}


def assert_network_allowed(reason: str | None = None) -> None:
    if not ALLOW_NETWORK:
        extra = f" ({reason})" if reason else ""
        raise RuntimeError(
            f"Network access blocked by default{extra}. Enable JL_PLATFORM_ALLOW_NETWORK=1 to override."
        )


@contextmanager
def network_guard(reason: str | None = None):
    if not ALLOW_NETWORK:
        logger.debug(
            "Network guard active; outbound calls are blocked% s",
            f" for {reason}" if reason else "",
        )
    try:
        yield
    finally:
        pass
