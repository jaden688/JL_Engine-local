from __future__ import annotations

import os
from pathlib import Path


def test_sandbox_blocks_escape(tmp_path, monkeypatch):
    # Point workspace to a temp dir
    monkeypatch.setenv("JL_WORKSPACE_ROOT", str(tmp_path))

    from tools.coding.tool_sandbox import resolve_sandbox_path

    (tmp_path / "ok.txt").write_text("hi", encoding="utf-8")

    p = resolve_sandbox_path("ok.txt")
    assert p.name == "ok.txt"

    # Attempt escape
    try:
        resolve_sandbox_path("../nope.txt")
        assert False, "should have raised"
    except PermissionError:
        assert True
