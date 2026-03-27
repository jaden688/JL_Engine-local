from __future__ import annotations

import json
import os
import sys
from types import SimpleNamespace

from ui.pyside_ui import Main, REPO_ROOT, SRC_DIR


class FakeProcessHandle:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    def start(self, cmd: list[str], cwd: str | None = None, env: dict | None = None) -> None:
        self.calls.append({"cmd": cmd, "cwd": cwd, "env": env})

    def is_running(self) -> bool:
        return False


def _make_main() -> Main:
    main = Main.__new__(Main)
    main._runtime_env = lambda: {"PYTHONPATH": "pinned"}
    main._append_chat = lambda *args: None
    return main


def test_start_platform_api_uses_current_interpreter() -> None:
    main = _make_main()
    main.proc_platform_api = FakeProcessHandle()
    main._platform_api_url = lambda: "http://127.0.0.1:8000"
    main._platform_api_health_url = lambda: "http://127.0.0.1:8000/health"
    main._service_host_port = lambda _url, _default: ("127.0.0.1", 8000)
    main._is_http_ready = lambda _url: False
    main._is_port_in_use = lambda _host, _port: False
    main._kill_stale_listener = lambda _host, _port: False

    Main._start_platform_api(main)

    assert len(main.proc_platform_api.calls) == 1
    call = main.proc_platform_api.calls[0]
    assert call["cmd"] == [
        sys.executable,
        "-m",
        "uvicorn",
        "jl_platform.services.api.main:app",
        "--host",
        "127.0.0.1",
        "--port",
        "8000",
        "--log-level",
        "warning",
    ]


def test_start_engine_api_uses_current_interpreter() -> None:
    main = _make_main()
    main.proc_engine_api = FakeProcessHandle()
    main._engine_api_url = lambda: "http://127.0.0.1:8001"
    main._engine_api_health_url = lambda: "http://127.0.0.1:8001/health"
    main._service_host_port = lambda _url, _default: ("127.0.0.1", 8001)
    main._is_http_ready = lambda _url: False
    main._is_port_in_use = lambda _host, _port: False
    main._kill_stale_listener = lambda _host, _port: False

    Main._start_engine_api(main)

    assert len(main.proc_engine_api.calls) == 1
    call = main.proc_engine_api.calls[0]
    assert call["cmd"] == [
        sys.executable,
        "-m",
        "uvicorn",
        "jl_engine_core.api_app:app",
        "--host",
        "127.0.0.1",
        "--port",
        "8001",
        "--log-level",
        "warning",
    ]


def test_launch_engine_cli_uses_current_interpreter(monkeypatch) -> None:
    import ui.pyside_ui as pyside_ui

    main = _make_main()
    captured: dict[str, object] = {}

    def fake_popen(cmd, cwd=None, env=None, creationflags=0):
        captured["cmd"] = cmd
        captured["cwd"] = cwd
        captured["env"] = env
        captured["creationflags"] = creationflags
        return SimpleNamespace()

    monkeypatch.setattr(pyside_ui.platform, "system", lambda: "Linux")
    monkeypatch.setattr(pyside_ui.subprocess, "Popen", fake_popen)

    Main._launch_engine_cli(main)

    assert captured["cmd"] == [sys.executable, "-m", "jl_engine_cli.main"]


def test_open_platform_web_ui_opens_ui_route(monkeypatch) -> None:
    import ui.pyside_ui as pyside_ui

    main = _make_main()
    opened: list[str] = []
    main._platform_api_url = lambda: "http://127.0.0.1:8000"
    main._platform_api_health_url = lambda: "http://127.0.0.1:8000/health"
    main._is_http_ready = lambda _url: True

    monkeypatch.setattr(pyside_ui.webbrowser, "open", lambda url: opened.append(url))

    Main._open_platform_web_ui(main)

    assert opened == ["http://127.0.0.1:8000/ui"]


def test_open_platform_web_ui_starts_api_before_opening(monkeypatch) -> None:
    import ui.pyside_ui as pyside_ui

    main = _make_main()
    opened: list[str] = []
    started: list[bool] = []
    main._platform_api_url = lambda: "http://127.0.0.1:8000"
    main._platform_api_health_url = lambda: "http://127.0.0.1:8000/health"
    main._is_http_ready = lambda _url: False
    main._start_platform_api = lambda: started.append(True)

    monkeypatch.setattr(pyside_ui.webbrowser, "open", lambda url: opened.append(url))
    monkeypatch.setattr(pyside_ui.QTimer, "singleShot", lambda _delay, callback: callback())

    Main._open_platform_web_ui(main)

    assert started == [True]
    assert opened == ["http://127.0.0.1:8000/ui"]


def test_runtime_env_strips_conda_state(monkeypatch) -> None:
    monkeypatch.setenv("CONDA_PREFIX", r"C:\Users\J_lin\miniconda3")
    monkeypatch.setenv("CONDA_DEFAULT_ENV", "base")
    monkeypatch.setenv(
        "PATH",
        os.pathsep.join(
            [
                r"C:\Users\J_lin\miniconda3\Scripts",
                r"C:\Tools",
                r"C:\Users\J_lin\miniconda3\Library\bin",
            ]
        ),
    )

    main = Main.__new__(Main)
    main._append_chat = lambda *args: None
    env = Main._runtime_env(main)

    assert "CONDA_PREFIX" not in env
    assert "CONDA_DEFAULT_ENV" not in env
    path_key = next(key for key in env if key.lower() == "path")
    assert all("miniconda" not in part.lower() for part in env[path_key].split(os.pathsep))
    expected_prefix = os.pathsep.join([str(REPO_ROOT), str(SRC_DIR)])
    assert env["PYTHONPATH"].startswith(expected_prefix)


def test_kill_stale_listener_windows_returns_true_on_success(monkeypatch) -> None:
    import ui.pyside_ui as pyside_ui

    main = _make_main()
    captured: dict[str, object] = {}

    class _Result:
        returncode = 0

    def fake_run(cmd, cwd=None, stdout=None, stderr=None, check=False):
        captured["cmd"] = cmd
        captured["cwd"] = cwd
        captured["check"] = check
        return _Result()

    monkeypatch.setattr(pyside_ui.platform, "system", lambda: "Windows")
    monkeypatch.setattr(pyside_ui.subprocess, "run", fake_run)

    ok = Main._kill_stale_listener(main, "127.0.0.1", 8000)

    assert ok is True
    assert isinstance(captured.get("cmd"), list)
    assert captured["cmd"][:3] == ["powershell", "-NoProfile", "-Command"]
    assert "Get-NetTCPConnection" in str(captured["cmd"][3])
    assert "{ exit 0 }" in str(captured["cmd"][3])


def test_save_service_config_omits_default_ollama_base_url(tmp_path, monkeypatch) -> None:
    import ui.pyside_ui as pyside_ui

    service_path = tmp_path / "gemini_config.json"
    monkeypatch.setattr(pyside_ui, "SERVICE_CONFIG_PATH", service_path)

    pyside_ui.save_service_config(
        {
            "ollama_model": "gemma3:4b",
            "ollama_base_url": "http://127.0.0.1:11434",
        }
    )

    saved = json.loads(service_path.read_text(encoding="utf-8"))
    assert saved["ollama_model"] == "gemma3:4b"
    assert "ollama_base_url" not in saved


def test_apply_workspace_dock_preset_uses_ide_lanes() -> None:
    class _FakeDock:
        def __init__(self, name: str) -> None:
            self.name = name
            self.visible = True
            self.min_width: int | None = None
            self.min_height: int | None = None
            self.raised = False

        def setVisible(self, value: bool) -> None:
            self.visible = value

        def isVisible(self) -> bool:
            return self.visible

        def setMinimumWidth(self, value: int) -> None:
            self.min_width = value

        def setMinimumHeight(self, value: int) -> None:
            self.min_height = value

        def raise_(self) -> None:
            self.raised = True

    main = Main.__new__(Main)
    main.dock_explorer = _FakeDock("Explorer")
    main.dock_ops = _FakeDock("Ops")
    main.dock_supervisor = _FakeDock("Supervisor")
    main.dock_monitor = _FakeDock("Monitor")
    main.dock_hud = _FakeDock("Command")
    main.dock_engine = _FakeDock("Engine")
    main.dock_cnc = _FakeDock("CNC")
    main.dock_services = _FakeDock("Services")
    main.dock_business = _FakeDock("Builder")
    main.dock_commander = _FakeDock("Commander")
    main.dock_terminal = _FakeDock("Terminal")
    main.dock_diagnostics = _FakeDock("Diagnostics")
    main.dock_benchmarks = _FakeDock("Benchmarks")
    main.dock_construction = _FakeDock("Construction")
    main._layout_metrics = {
        "left_min": 140,
        "right_min": 190,
        "bottom_min": 120,
        "left_size": 170,
        "right_size": 240,
        "bottom_size": 180,
    }

    calls: dict[str, list[object]] = {
        "add": [],
        "tabify": [],
        "resize": [],
        "tabs": [],
        "corners": [],
    }

    main.addDockWidget = lambda area, dock: calls["add"].append((area, dock.name))
    main.tabifyDockWidget = lambda left, right: calls["tabify"].append((left.name, right.name))
    main.resizeDocks = lambda docks, sizes, orientation: calls["resize"].append(
        ([dock.name for dock in docks], list(sizes), orientation)
    )
    main.setTabPosition = lambda area, position: calls["tabs"].append((area, position))
    main.setCorner = lambda corner, area: calls["corners"].append((corner, area))
    main._polish_tab_bars = lambda: None

    Main._apply_workspace_dock_preset(main)

    assert any(name == "Explorer" for _area, name in calls["add"])
    assert any(name == "Command" for _area, name in calls["add"])
    assert any(name == "Terminal" for _area, name in calls["add"])
    assert ("Explorer", "Ops") in calls["tabify"]
    assert ("Command", "Engine") in calls["tabify"]
    assert ("Terminal", "Diagnostics") in calls["tabify"]
    assert main.dock_explorer.min_width == 140
    assert main.dock_hud.min_width == 190
    assert main.dock_terminal.min_height == 120
    assert any(docks == ["Explorer", "Command"] for docks, _sizes, _orientation in calls["resize"])
