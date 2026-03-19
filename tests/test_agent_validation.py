from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from jl_engine_core import agent_validation
from jl_engine_core.agent_validation import ValidationError, validate_agent


@pytest.fixture(autouse=True)
def _clear_schema_cache() -> None:
    agent_validation._load_schema.cache_clear()
    yield
    agent_validation._load_schema.cache_clear()


def test_validate_agent_accepts_baseline_payload_when_schema_missing(tmp_path) -> None:
    schema_path = tmp_path / "agent_schema.json"

    validate_agent(
        {"identity": {"name": "SparkByte", "role": "Assistant"}},
        schema_path=schema_path,
    )


def test_validate_agent_rejects_garbage_payload_when_schema_missing(tmp_path) -> None:
    schema_path = tmp_path / "agent_schema.json"

    with pytest.raises(ValidationError, match="identity"):
        validate_agent({"foo": "bar"}, schema_path=schema_path)


def test_validate_agent_falls_back_to_baseline_validation_when_schema_is_invalid(tmp_path) -> None:
    schema_path = tmp_path / "agent_schema.json"
    schema_path.write_text("{not valid json", encoding="utf-8")

    validate_agent(
        {"identity": {"name": "SparkByte", "role": "Assistant"}},
        schema_path=schema_path,
    )


def test_validate_agent_uses_loaded_schema_when_available(monkeypatch, tmp_path) -> None:
    captured: dict[str, object] = {}

    class StubValidator:
        def __init__(self, schema):
            captured["schema"] = schema

        def iter_errors(self, payload):
            if "must_have" not in payload:
                yield SimpleNamespace(path=["must_have"], message="'must_have' is required")

    monkeypatch.setattr(agent_validation, "Draft7Validator", StubValidator)

    schema_path = tmp_path / "agent_schema.json"
    schema_path.write_text(json.dumps({"required": ["must_have"]}), encoding="utf-8")

    with pytest.raises(ValidationError, match="must_have"):
        validate_agent(
            {"identity": {"name": "SparkByte", "role": "Assistant"}},
            schema_path=schema_path,
        )

    assert captured["schema"] == {"required": ["must_have"]}
