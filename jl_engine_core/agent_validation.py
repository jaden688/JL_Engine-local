"""Agent JSON schema validation utilities."""

from __future__ import annotations

import json
import os
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict

try:
    from jsonschema import Draft7Validator, ValidationError  # type: ignore
except Exception:  # pragma: no cover - optional dependency fallback
    Draft7Validator = None

    class ValidationError(Exception):
        """Fallback validation error when jsonschema is unavailable."""

from .logging_setup import get_logger

logger = get_logger(__name__)

PACKAGE_ROOT = Path(__file__).resolve().parent
REPO_ROOT = PACKAGE_ROOT.parent
DEFAULT_AGENT_SCHEMA_PATH = Path(
    os.getenv("JL_AGENT_SCHEMA_PATH") or (REPO_ROOT / "config" / "agent_schema.json")
)


def _resolve_schema_path(schema_path: str | Path | None = None) -> Path:
    if schema_path:
        return Path(schema_path).expanduser()
    return DEFAULT_AGENT_SCHEMA_PATH


@lru_cache(maxsize=1)
def _load_schema(schema_path: str | Path | None = None) -> Dict[str, Any]:
    path = _resolve_schema_path(schema_path)
    try:
        raw = path.read_text(encoding="utf-8").lstrip("\ufeff")
        return json.loads(raw)
    except (OSError, json.JSONDecodeError) as exc:
        logger.warning(
            "[AgentValidation] Failed to load agent schema at %s; using permissive fallback: %s",
            path,
            exc,
        )
        # Capability-first fallback: keep runtime unblocked when schema file is absent.
        return {"type": "object"}


def validate_agent(payload: Dict[str, Any], schema_path: str | Path | None = None) -> None:
    """Validate agent JSON against the configured schema."""
    if not isinstance(payload, dict):
        raise ValidationError("Agent payload must be an object.")
    if Draft7Validator is None:
        # Capability-first fallback for environments missing jsonschema.
        identity = payload.get("identity")
        core_identity = payload.get("core_identity")
        if not isinstance(identity, dict):
            if not isinstance(core_identity, dict):
                raise ValidationError("Agent requires either 'identity' or 'core_identity'.")
            if not str(core_identity.get("title", "")).strip():
                raise ValidationError(
                    "Agent core_identity requires a non-empty 'title' when identity is absent."
                )
            return
        if not str(identity.get("name", "")).strip():
            raise ValidationError("Agent identity requires a non-empty 'name'.")
        role = str(identity.get("role", "")).strip()
        if not role and isinstance(core_identity, dict):
            role = str(core_identity.get("title", "")).strip()
        if not role:
            raise ValidationError(
                "Agent identity requires a non-empty 'role' (or core_identity.title)."
            )
        return

    schema = _load_schema(schema_path)
    validator = Draft7Validator(schema)
    errors = sorted(validator.iter_errors(payload), key=lambda e: e.path)
    if errors:
        message = "; ".join(f"{'/'.join(map(str, err.path))}: {err.message}" for err in errors)
        raise ValidationError(message)
