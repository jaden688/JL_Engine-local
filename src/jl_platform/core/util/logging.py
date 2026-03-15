from __future__ import annotations

import logging
import os
import sys
import uuid
from typing import Optional


def new_trace_id() -> str:
    return uuid.uuid4().hex


def _default_level() -> int:
    level = os.getenv("JL_PLATFORM_LOG_LEVEL", "INFO").upper()
    return getattr(logging, level, logging.INFO)


def get_logger(name: Optional[str] = None) -> logging.Logger:
    logger = logging.getLogger(name or "jl_platform")
    if not logger.handlers:
        handler = logging.StreamHandler(stream=sys.stdout)
        fmt = logging.Formatter(
            "[%(asctime)s] [%(levelname)s] %(name)s %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )
        handler.setFormatter(fmt)
        logger.addHandler(handler)
        logger.setLevel(_default_level())
        logger.propagate = False
    return logger
