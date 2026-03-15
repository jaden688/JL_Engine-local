from __future__ import annotations

import json
from typing import Any, Callable, Optional, Type

from pydantic import BaseModel, ValidationError

from jl_platform.core.util.logging import get_logger

logger = get_logger(__name__)


def _loads_safe(raw: str) -> Optional[dict]:
    try:
        return json.loads(raw)
    except Exception:
        return None


def validate_with_model(model: Type[BaseModel], payload: Any) -> BaseModel:
    """Validate payload against a Pydantic model with a one-time JSON parsing retry."""
    try:
        return model.parse_obj(payload)
    except ValidationError as first_err:
        if isinstance(payload, str):
            parsed = _loads_safe(payload)
            if parsed is not None:
                return model.parse_obj(parsed)
        logger.debug("Validation failed: %s", first_err)
        raise


def ensure_json_dict(payload: Any) -> dict:
    """Guarantee a dictionary for downstream consumption."""
    if isinstance(payload, dict):
        return payload
    if isinstance(payload, str):
        parsed = _loads_safe(payload)
        if isinstance(parsed, dict):
            return parsed
        return {"text": payload}
    return {"value": payload}
