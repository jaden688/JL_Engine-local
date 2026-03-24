import json
from pathlib import Path

from .logging_setup import get_logger

logger = get_logger(__name__)


def load_json_safely(path) -> dict:
    """
    Load JSON from disk with UTF-8, stripping any BOM.
    Always returns a dict; falls back to {} on missing/corrupt files.
    """
    p = Path(path)
    if not p.exists():
        logger.warning("[JL Engine] Using default config; file missing: %s", p)
        return {}

    try:
        with open(p, "r", encoding="utf-8") as reader:
            text = reader.read()
        text = text.lstrip("\ufeff")
        if not text.strip():
            return {}
        return json.loads(text)
    except Exception as exc:  # pragma: no cover - safety net
        logger.warning("[JL Engine] Using default config; failed to load %s: %s", p, exc)
        return {}
