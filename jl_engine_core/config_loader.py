from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, Optional

try:
    from dotenv import load_dotenv
except Exception:  # pragma: no cover - optional dependency
    def load_dotenv(*_args, **_kwargs):
        return False

from .logging_setup import get_logger

logger = get_logger(__name__)

try:  # Optional dependency for YAML configs
    import yaml
except Exception:  # pragma: no cover - optional import
    yaml = None


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


def load_config(config_path: Optional[str] = None) -> Dict[str, Any]:
    """
    Load environment variables and optional JSON/YAML configuration.

    Args:
        config_path: Path to a JSON or YAML file with additional settings.

    Returns:
        A dictionary of parsed settings (may be empty on failure).
    """

    load_dotenv()
    settings: Dict[str, Any] = {}

    if not config_path:
        return settings

    path = Path(config_path)
    if not path.exists():
        logger.warning("Config file not found: %s", path)
        return settings

    try:
        text = path.read_text(encoding="utf-8").lstrip("\ufeff")
        if not text.strip():
            return settings

        suffix = path.suffix.lower()
        if suffix in {".yaml", ".yml"}:
            if yaml is None:
                raise RuntimeError("PyYAML is required to load YAML configs")
            parsed = yaml.safe_load(text) or {}
        else:
            parsed = json.loads(text)
        if isinstance(parsed, dict):
            settings.update(parsed)
        elif parsed is not None:
            logger.warning("Config file %s did not parse to a dict; ignoring.", path)
    except Exception as exc:  # pragma: no cover - defensive
        logger.warning("Failed to load config %s: %s", path, exc)

    return settings
