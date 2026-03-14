from __future__ import annotations

from jl_platform.core.tools import audit as audit_module


def test_audit_tool_skips_git_checks_by_default(monkeypatch) -> None:
    git_calls: list[list[str]] = []

    def fake_run_git(args: list[str]) -> dict:
        git_calls.append(list(args))
        return {"ok": True, "stdout": "", "stderr": "", "code": 0}

    monkeypatch.setattr(audit_module, "_run_git", fake_run_git)

    result = audit_module.run_audit_tool({"code": "print('hello')", "output": "hello"})

    assert result["status"] == "ok"
    assert result["hashes"]["code_sha256"]
    assert result["git"]["status"]["skipped"] is True
    assert result["git"]["diff"]["skipped"] is True
    assert result["git"]["log"]["skipped"] is True
    assert git_calls == []


def test_audit_tool_can_opt_into_git_checks(monkeypatch) -> None:
    git_calls: list[list[str]] = []

    def fake_run_git(args: list[str]) -> dict:
        git_calls.append(list(args))
        return {"ok": True, "stdout": "ok", "stderr": "", "code": 0}

    monkeypatch.setattr(audit_module, "_run_git", fake_run_git)

    result = audit_module.run_audit_tool(
        {"code": "print('hello')", "output": "hello", "include_git": True}
    )

    assert result["status"] == "ok"
    assert result["git"]["status"]["ok"] is True
    assert git_calls == [
        ["status", "--porcelain"],
        ["diff"],
        ["log", "-n", "5", "--oneline"],
    ]
