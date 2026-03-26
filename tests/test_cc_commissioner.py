from __future__ import annotations

from pathlib import Path

from jl_platform.core.tools.cc import run_cc_command


def test_cc_commissioner_searches_files(tmp_path: Path) -> None:
    target = tmp_path / "nested" / "notes.txt"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("alpha\nbeta keyword gamma\n", encoding="utf-8")

    result = run_cc_command(
        {
            "action": "search_files",
            "cwd": str(tmp_path),
            "root": ".",
            "query": "keyword",
            "recursive": True,
        }
    )

    assert result["status"] == "ok"
    assert result["action"] == "search_files"
    assert result["count"] >= 1
    assert any(match["path"].endswith("notes.txt") for match in result["matches"])


def test_cc_commissioner_handles_fs_write_and_read(tmp_path: Path) -> None:
    target = tmp_path / "scratch" / "message.txt"

    write_result = run_cc_command(
        {
            "action": "fs_write",
            "cwd": str(tmp_path),
            "path": "scratch/message.txt",
            "content": "hello from CC",
        }
    )
    read_result = run_cc_command(
        {
            "action": "fs_read",
            "cwd": str(tmp_path),
            "path": "scratch/message.txt",
        }
    )

    assert write_result["status"] == "ok"
    assert read_result["status"] == "ok"
    assert read_result["content"] == "hello from CC"
