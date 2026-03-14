from __future__ import annotations

import os
from jl_platform.core.util.logging import get_logger

logger = get_logger(__name__)

_printed = False
_banner_text = "Why have you summoned me to your realm, mortal?"


def suppress_by_default() -> bool:
    if os.getenv("PYTEST_CURRENT_TEST"):
        return True
    disabled = os.getenv("JL_PLATFORM_DISABLE_BANNER", "").lower()
    return disabled in {"1", "true", "yes", "on"}


def print_banner_once(force: bool = False) -> None:
    global _printed
    if _printed:
        return
    if suppress_by_default() and not force:
        logger.debug("Banner suppressed by environment.")
        _printed = True
        return
    print(_banner_text)
    _printed = True


def reset_banner_state() -> None:
    global _printed
    _printed = False
