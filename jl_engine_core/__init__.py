"""J_engine Core package."""

from __future__ import annotations

from importlib import metadata
from pathlib import Path
import re

__all__ = ["__version__", "get_version", "EngineConfig", "JLEngineCore"]


_DEF_VERSION = "1.0.0"


def _read_version() -> str:
    """Read the engine version from the repo or package metadata."""
    package_root = Path(__file__).resolve().parent
    candidates = [
        package_root / "VERSION",
        package_root.parent / "JL_Engine_Headless" / "VERSION",
        package_root.parent / "VERSION",
    ]
    for path in candidates:
        try:
            if path.exists():
                return path.read_text(encoding="utf-8").strip()
        except OSError:
            continue
    pyproject_path = package_root.parent / "pyproject.toml"
    try:
        if pyproject_path.exists():
            raw_pyproject = pyproject_path.read_text(encoding="utf-8")
            match = re.search(
                r"(?ms)^\\[project\\].*?^version\\s*=\\s*[\"']([^\"']+)[\"']\\s*$",
                raw_pyproject,
            )
            if match and match.group(1).strip():
                return match.group(1).strip()
    except OSError:
        pass
    for dist_name in ("j_engine", "jl-engine-core"):
        try:
            resolved = metadata.version(dist_name)
            if resolved:
                return resolved
        except (metadata.PackageNotFoundError, KeyError):
            continue
    return _DEF_VERSION


__version__ = _read_version()


def get_version() -> str:
    return __version__


from .engine_core import EngineConfig, JLEngineCore
