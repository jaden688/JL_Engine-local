import json
from pathlib import Path
from typing import Union

from .types import JsonDict


def load_personality(path: Union[str, Path]) -> JsonDict:
    """
    Load a personality JSON file from disk and return it as a dict.

    This function does not perform validation by itself; call
    `validate_personality` from `validator.py` if you want to enforce
    schema correctness.
    """
    p = Path(path)
    if not p.is_file():
        raise FileNotFoundError(f"Personality file not found: {p}")

    text = p.read_text(encoding="utf-8")
    try:
        data: JsonDict = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ValueError(f"Invalid JSON in personality file {p}: {exc}") from exc

    return data
