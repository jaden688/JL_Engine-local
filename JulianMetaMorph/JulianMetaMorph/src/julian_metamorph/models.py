from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass(frozen=True, slots=True)
class RepoFile:
    path: str
    content: str
    language: str = ""
    sha: str = ""
    size: int = 0
    symbols: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class RepoSnapshot:
    full_name: str
    description: str = ""
    homepage: str = ""
    language: str = ""
    stars: int = 0
    forks: int = 0
    topics: tuple[str, ...] = ()
    license_spdx: str = "UNKNOWN"
    default_branch: str = "main"
    pushed_at: str = ""
    html_url: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class ScoutHit:
    repo_full_name: str
    path: str
    language: str
    license_spdx: str
    allowed: bool
    score: float
    preview: str
    symbols: tuple[str, ...]
    why: str
    source: str = ""
    source_url: str = ""


@dataclass(frozen=True, slots=True)
class ForgedSkill:
    name: str
    task: str
    description: str
    module_path: Path
    manifest_path: Path
    source: str
