from __future__ import annotations

from pathlib import Path

from tools import bench_manager


def test_bench_manager_watches_non_python_repo_artifacts(tmp_path: Path):
    (tmp_path / "ui_web").mkdir()
    (tmp_path / "docs").mkdir()
    (tmp_path / "ui_web" / "app.js").write_text("console.log('ok')", encoding="utf-8")
    (tmp_path / "docs" / "notes.md").write_text("# notes", encoding="utf-8")
    (tmp_path / "VERSION").write_text("1.2.3", encoding="utf-8")
    (tmp_path / "ignored.log").write_text("skip me", encoding="utf-8")

    snapshot = bench_manager._compute_snapshot([tmp_path])
    watched = {path.relative_to(tmp_path).as_posix() for path in snapshot}

    assert "ui_web/app.js" in watched
    assert "docs/notes.md" in watched
    assert "VERSION" in watched
    assert "ignored.log" not in watched
