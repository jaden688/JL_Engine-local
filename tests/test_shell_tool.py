from __future__ import annotations

from jl_platform.core.tools import shell as shell_module


def test_run_shell_routes_windows_commands_through_powershell(monkeypatch) -> None:
    captured: dict = {}

    def fake_run_cc_command(payload: dict) -> dict:
        captured.update(payload)
        return {"stdout": "ok", "stderr": "", "returncode": 0, "ok": True, "duration_ms": 1.0}

    monkeypatch.setattr(shell_module, "run_cc_command", fake_run_cc_command)

    result = shell_module.run_shell({"command": "Get-Process -Name 'powershell'"})

    assert result["ok"] is True
    assert captured["shell"] is False
    assert isinstance(captured["command"], list)
    assert any(str(part).lower() == "-command" for part in captured["command"])
    assert str(captured["command"][-1]) == "Get-Process -Name 'powershell'"


def test_run_shell_normalizes_bad_select_format_power_shell_pattern(monkeypatch) -> None:
    captured: dict = {}

    def fake_run_cc_command(payload: dict) -> dict:
        captured.update(payload)
        return {"stdout": "ok", "stderr": "", "returncode": 0, "ok": True, "duration_ms": 1.0}

    monkeypatch.setattr(shell_module, "run_cc_command", fake_run_cc_command)

    shell_module.run_shell(
        {
            "command": "Get-Process -Name 'powershell.exe' -ErrorAction SilentlyContinue | Select -Format \"Name, CPU, WorkingSet, PM, StartTime\""
        }
    )

    assert str(captured["command"][-1]) == (
        "Get-Process -Name 'powershell' -ErrorAction SilentlyContinue | "
        "Select-Object Name, CPU, WorkingSet, PM, StartTime"
    )
