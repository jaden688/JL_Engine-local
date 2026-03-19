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


def _validate_baseline_shape(payload: Dict[str, Any]) -> None:
    """Keep the runtime honest even when the JSON schema is unavailable."""
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
        raise ValidationError("Agent identity requires a non-empty 'role' (or core_identity.title).")


@lru_cache(maxsize=1)
def _load_schema(schema_path: str | Path | None = None) -> Dict[str, Any] | None:
    path = _resolve_schema_path(schema_path)
    try:
        raw = path.read_text(encoding="utf-8").lstrip("\ufeff")
        return json.loads(raw)
    except FileNotFoundError:
        logger.warning(
            "[AgentValidation] Agent schema file is missing at %s; falling back to baseline validation.",
            path,
        )
        return None
    except json.JSONDecodeError as exc:
        logger.warning(
            "[AgentValidation] Agent schema file at %s is invalid JSON; falling back to baseline validation: %s",
            path,
            exc,
        )
        return None
    except OSError as exc:
        logger.warning(
            "[AgentValidation] Could not read agent schema at %s; falling back to baseline validation: %s",
            path,
            exc,
        )
        return None


def validate_agent(payload: Dict[str, Any], schema_path: str | Path | None = None) -> None:
    """Validate agent JSON against the configured schema."""
    if not isinstance(payload, dict):
        raise ValidationError("Agent payload must be an object.")
    _validate_baseline_shape(payload)
    if Draft7Validator is None:
        return

    schema = _load_schema(schema_path)
    if schema is None:
        return
    validator = Draft7Validator(schema)
    errors = sorted(validator.iter_errors(payload), key=lambda e: e.path)
    if errors:
        message = "; ".join(f"{'/'.join(map(str, err.path))}: {err.message}" for err in errors)
        raise ValidationError(message)
