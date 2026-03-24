import json
from pathlib import Path
from typing import Any, Dict

import jsonschema

from .schema_version import SCHEMA_VERSION
from .types import JsonDict


def _schema_file() -> Path:
    """Locate the JSON Schema file relative to the package."""
    return Path(__file__).resolve().parents[2] / "schema" / "mpf-jl-extensions-v1.json"


def _load_schema() -> Dict[str, Any]:
    """Load the JSON Schema for the current SCHEMA_VERSION."""
    schema_path = _schema_file()
    if not schema_path.is_file():
        raise FileNotFoundError(f"Schema file not found: {schema_path}")
    with schema_path.open("r", encoding="utf-8") as f:
        return json.load(f)


def validate_personality(data: JsonDict) -> None:
    """
    Validate a personality dict against the JSON Schema.

    Raises jsonschema.ValidationError if the data is invalid.
    """
    if not isinstance(data, dict):
        raise TypeError("Personality data must be a JSON object (dict).")

    schema = _load_schema()

    version = data.get("schema_version")
    if version != SCHEMA_VERSION:
        raise ValueError(
            f"Unexpected schema_version '{version}'. Expected '{SCHEMA_VERSION}'."
        )

    jsonschema.validate(instance=data, schema=schema)
