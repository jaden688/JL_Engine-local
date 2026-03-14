from __future__ import annotations

import importlib


def test_legacy_core_cli_forwards_to_unified_console(monkeypatch) -> None:
    legacy_cli = importlib.import_module("jl_engine_core.cli")
    unified_cli = importlib.import_module("jl_engine_cli.main")
    calls: list[list[str]] = []

    def fake_main(argv=None):
        calls.append(list(argv or []))
        return 17

    monkeypatch.setattr(unified_cli, "main", fake_main)

    assert legacy_cli.main(["--version"]) == 17
    assert calls == [["--version"]]

    calls.clear()
    console = legacy_cli.HeadlessConsole(config_path="demo.json")
    assert console.run() == 17
    assert calls == [["--config", "demo.json"]]


def test_legacy_headless_cli_forwards_to_unified_console(monkeypatch) -> None:
    headless_cli = importlib.import_module("jl_engine_core.headless_cli")
    unified_cli = importlib.import_module("jl_engine_cli.main")
    calls: list[list[str]] = []

    def fake_main(argv=None):
        calls.append(list(argv or []))
        return 23

    monkeypatch.setattr(unified_cli, "main", fake_main)

    assert headless_cli.main(["--agent", "Slappy"]) == 23
    assert calls == [["--agent", "Slappy"]]
