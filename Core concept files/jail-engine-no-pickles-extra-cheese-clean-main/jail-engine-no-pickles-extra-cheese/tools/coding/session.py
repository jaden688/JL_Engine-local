from __future__ import annotations

import json
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Optional

from .tool_sandbox import get_workspace_root


def sessions_root() -> Path:
    root = get_workspace_root() / ".jl_sessions"
    root.mkdir(parents=True, exist_ok=True)
    return root


@dataclass
class Session:
    id: str
    path: Path

    def write_json(self, name: str, obj: Any) -> Path:
        p = self.path / name
        p.write_text(json.dumps(obj, indent=2, ensure_ascii=False), encoding="utf-8")
        return p

    def append_jsonl(self, name: str, obj: Any) -> Path:
        p = self.path / name
        with p.open("a", encoding="utf-8") as f:
            f.write(json.dumps(obj, ensure_ascii=False) + "\n")
        return p

    def append_text(self, name: str, text: str) -> Path:
        p = self.path / name
        with p.open("a", encoding="utf-8") as f:
            f.write(text)
            if not text.endswith("\n"):
                f.write("\n")
        return p


def new_session() -> Session:
    sid = time.strftime("%Y%m%d_%H%M%S")
    sp = sessions_root() / sid
    sp.mkdir(parents=True, exist_ok=True)
    return Session(id=sid, path=sp)


def latest_session() -> Optional[Session]:
    root = sessions_root()
    dirs = [p for p in root.iterdir() if p.is_dir()]
    if not dirs:
        return None
    dirs.sort(key=lambda p: p.name, reverse=True)
    p = dirs[0]
    return Session(id=p.name, path=p)
