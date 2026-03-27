from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))

from jl_engine_cli import main as modern_cli
from jl_engine_core import agent_cli as legacy_cli


class StubSession:
    def __init__(self, telemetry: dict | None = None) -> None:
        self.calls: list[dict] = []
        self.engine = SimpleNamespace(current_agent_name="SparkByte", set_agent=lambda agent: None)
        self._telemetry = telemetry or {}

    def run(self, message: str, context: dict | None = None) -> dict:
        self.calls.append({"message": message, "context": dict(context or {})})
        return {
            "status": "ok",
            "final": "Reply text",
            "tool_trace": [],
            "telemetry": dict(self._telemetry),
        }


class ConfirmingSession(StubSession):
    def __init__(self) -> None:
        super().__init__()
        self.pending = {
            "id": "pending-1",
            "summary": "run shell command `Get-ComputerInfo`",
            "tool": "run_shell",
            "risk_level": "high",
        }
        self.confirm_calls: list[dict] = []

    def run(self, message: str, context: dict | None = None) -> dict:
        self.calls.append({"message": message, "context": dict(context or {})})
        return {
            "status": "confirmation_required",
            "final": "Awaiting confirmation: run shell command `Get-ComputerInfo`.",
            "reply": "Awaiting confirmation: run shell command `Get-ComputerInfo`.",
            "pending_action": dict(self.pending),
            "tool_trace": [],
            "telemetry": {},
        }

    def get_pending_action(self) -> dict | None:
        return dict(self.pending) if self.pending else None

    def confirm_pending_action(self, pending_action_id: str, *, approved: bool, note: str = "") -> dict:
        self.confirm_calls.append(
            {"pending_action_id": pending_action_id, "approved": approved, "note": note}
        )
        self.pending = None
        if approved:
            return {
                "status": "ok",
                "final": "System info check complete.",
                "reply": "System info check complete.",
                "tool_trace": [],
                "telemetry": {},
            }
        return {
            "status": "ok",
            "final": "Cancelled pending action: run shell command `Get-ComputerInfo`.",
            "reply": "Cancelled pending action: run shell command `Get-ComputerInfo`.",
            "tool_trace": [],
            "telemetry": {},
            "cancelled": True,
        }


class FakeBench:
    def __init__(self) -> None:
        self.active_worker_agent_name = "Bench Worker"
        self.backend_id = "ollama-local"
        self.session_workdir = Path.cwd()
        self.trace_log_path = Path.cwd() / "bench-trace.log"
        self.human_verification = False
        self.show_plan = False
        self.show_raw_output = False
        self.clear_memory_each_turn = True
        self.request_timeout = 30.0
        self.turns: list[str] = []
        self.commands: list[str] = []
        self.selected_agents: list[str] = []

    def _backend_label(self, backend_id: str) -> str:
        return backend_id

    def _initial_timeout_for_backend(self, _backend_id: str) -> float:
        return 30.0

    def _set_worker_agent(self, agent_name: str) -> bool:
        self.selected_agents.append(agent_name)
        self.active_worker_agent_name = agent_name
        return True

    def _pick_worker_agent(self) -> str:
        return "Bench Worker"

    def _handle_slash_command(self, raw_input: str) -> str:
        self.commands.append(raw_input)
        return "handled"

    def run_turn(self, user_input: str) -> None:
        self.turns.append(user_input)


class TraceSession(StubSession):
    def run(self, message: str, context: dict | None = None) -> dict:
        self.calls.append({"message": message, "context": dict(context or {})})
        return {
            "status": "ok",
            "final": "Reply text",
            "tool_trace": [{"tool": "run_shell"}],
            "telemetry": {"agent": self.engine.current_agent_name},
        }


class SwitchingSession(StubSession):
    def __init__(self) -> None:
        super().__init__()
        self.engine = SimpleNamespace(current_agent_name="SparkByte", set_agent=self._set_agent)

    def _set_agent(self, agent: str) -> None:
        self.engine.current_agent_name = agent

    def run(self, message: str, context: dict | None = None) -> dict:
        self.calls.append({"message": message, "context": dict(context or {})})
        return {
            "status": "ok",
            "final": f"{self.engine.current_agent_name} reply",
            "tool_trace": [],
            "telemetry": {"agent": self.engine.current_agent_name},
        }


def test_modern_cli_locks_selected_agent_by_default(monkeypatch):
    session = StubSession()
    prompts = iter(["hello", "quit"])
    monkeypatch.setattr("builtins.input", lambda _prompt="": next(prompts))

    result = modern_cli._repl(session, show_trace=False)

    assert result == 0
    assert session.calls[0]["context"]["respect_selected_agent"] is True


def test_legacy_cli_locks_selected_agent_by_default(monkeypatch):
    session = StubSession()
    prompts = iter(["hello", "quit"])
    monkeypatch.setattr("builtins.input", lambda _prompt="": next(prompts))

    result = legacy_cli._repl(session, show_trace=False)

    assert result == 0
    assert session.calls[0]["context"]["respect_selected_agent"] is True


def test_modern_cli_hud_uses_engine_telemetry_fields(monkeypatch, capsys):
    telemetry = {
        "agent": "SparkByte",
        "behavior_state": {"name": "Engaged-Loose"},
        "cognitive_mode": "balanced",
        "thinking_scene": "curious banter",
        "thinking_facet": "playful intrigue",
        "temporal_sampling_ready": True,
        "rhythm": {"mode": "idle", "gait": "walk", "index": 0.25},
        "aperture_dynamic": {"mode": "OPEN"},
        "aperture_state": {"score": 0.48, "mode": "OPEN"},
        "stability_score": 0.55,
        "drift": {"pressure": 0.03},
        "novelty_pressure": 0.1,
        "loop_pressure": 0.2,
    }
    session = StubSession(telemetry=telemetry)
    prompts = iter(["hello", "quit"])
    monkeypatch.setattr("builtins.input", lambda _prompt="": next(prompts))

    modern_cli._repl(session, show_trace=False)
    output = capsys.readouterr().out

    assert "THE HEALING BENCH" in output
    assert "[SparkByte]" in output
    assert "Supervisor:   Unified Console // Engine-first Chat" in output
    assert "Trace Log:" in output
    assert "[ ENGINE HUD ]" in output
    assert "SparkByte | Engaged-Loose | gait=walk | rhythm=idle | aperture=OPEN" in output
    assert "scene=curious banter | emotion=playful intrigue | mind=balanced | sampling=hot" in output
    assert "Stability" in output
    assert "Rhythm" in output
    assert output.index("[ ENGINE HUD ]") < output.rindex("[SparkByte]")


def test_modern_cli_bench_mode_runs_inline_and_returns(monkeypatch, capsys):
    session = StubSession()
    bench = FakeBench()
    prompts = iter(["/bench", "hello bench", "/back", "quit"])
    monkeypatch.setattr("builtins.input", lambda _prompt="": next(prompts))
    monkeypatch.setattr(modern_cli, "_load_healing_bench_executor", lambda: (lambda: bench))

    result = modern_cli._repl(session, show_trace=False)
    output = capsys.readouterr().out

    assert result == 0
    assert bench.selected_agents == ["SparkByte"]
    assert bench.turns == ["hello bench"]
    assert "THE HEALING BENCH :: WORKER CHANNEL" in output
    assert "Leaving Bench Worker mode." in output


def test_modern_cli_worker_command_uses_bench_executor(monkeypatch, capsys):
    session = StubSession()
    bench = FakeBench()
    prompts = iter(["/worker The Gremlin", "quit"])
    monkeypatch.setattr("builtins.input", lambda _prompt="": next(prompts))
    monkeypatch.setattr(modern_cli, "_load_healing_bench_executor", lambda: (lambda: bench))

    result = modern_cli._repl(session, show_trace=False)
    output = capsys.readouterr().out

    assert result == 0
    assert bench.selected_agents == ["SparkByte", "The Gremlin"]
    assert "Bench worker set to: The Gremlin" in output


def test_modern_cli_bench_one_shot_runs_without_switching_modes(monkeypatch, capsys):
    session = StubSession()
    bench = FakeBench()
    prompts = iter(["/bench patch the code", "quit"])
    monkeypatch.setattr("builtins.input", lambda _prompt="": next(prompts))
    monkeypatch.setattr(modern_cli, "_load_healing_bench_executor", lambda: (lambda: bench))

    result = modern_cli._repl(session, show_trace=False)
    output = capsys.readouterr().out

    assert result == 0
    assert bench.selected_agents == ["SparkByte"]
    assert bench.turns == ["patch the code"]
    assert "WORKER CHANNEL" not in output


def test_modern_cli_engine_first_keeps_task_requests_in_main_session(monkeypatch, capsys):
    session = StubSession()
    bench = FakeBench()
    prompts = iter(["build a plan to patch the repo", "quit"])
    monkeypatch.setattr("builtins.input", lambda _prompt="": next(prompts))
    monkeypatch.setattr(modern_cli, "_load_healing_bench_executor", lambda: (lambda: bench))

    result = modern_cli._repl(session, show_trace=False)
    output = capsys.readouterr().out

    assert result == 0
    assert session.calls[0]["message"] == "build a plan to patch the repo"
    assert bench.selected_agents == []
    assert bench.turns == []
    assert "Task detected. Handing execution" not in output


def test_modern_cli_launch_forwards_cli_surface_args(monkeypatch):
    calls: list[list[str]] = []

    def fake_main_cli(argv=None):
        calls.append(list(argv or []))
        return 41

    monkeypatch.setattr(modern_cli, "_main_cli", fake_main_cli)

    result = modern_cli.main(["launch", "--ui", "cli", "--agent", "Slappy", "--trace"])

    assert result == 41
    assert calls == [["--agent", "Slappy", "--trace"]]


def test_modern_cli_launch_web_dispatches_platform_api(monkeypatch):
    captured: dict[str, object] = {}

    def fake_launch_platform_api(**kwargs):
        captured.update(kwargs)
        return 11

    monkeypatch.setattr(modern_cli, "_launch_platform_api", fake_launch_platform_api)

    result = modern_cli.main(
        [
            "launch",
            "--ui",
            "web",
            "--host",
            "127.0.0.1",
            "--port",
            "8123",
            "--ui-path",
            "/ui/",
            "--no-open-browser",
        ]
    )

    assert result == 11
    assert captured["host"] == "127.0.0.1"
    assert captured["port"] == 8123
    assert captured["ui_path"] == "/ui/"
    assert captured["open_browser"] is False


def test_modern_cli_launch_desktop_dispatches_pyside(monkeypatch):
    calls: list[bool | None] = []

    monkeypatch.setattr(
        modern_cli,
        "_launch_desktop_ui",
        lambda *, chat_only_mode=None: calls.append(chat_only_mode) or 7,
    )

    result = modern_cli.main(["launch", "--ui", "desktop", "--chat-window"])

    assert result == 7
    assert calls == [True]


def test_modern_cli_launch_api_skips_browser_open(monkeypatch):
    captured: dict[str, object] = {}

    def fake_launch_platform_api(**kwargs):
        captured.update(kwargs)
        return 19

    monkeypatch.setattr(modern_cli, "_launch_platform_api", fake_launch_platform_api)

    result = modern_cli.main(["launch", "--ui", "api"])

    assert result == 19
    assert captured["open_browser"] is False


def test_worker_task_detection_uses_real_word_boundaries() -> None:
    assert modern_cli._looks_like_worker_task("list the files on my desktop") is True
    assert (
        modern_cli._looks_like_worker_task(
            "You ain't supposed to be a vibe honey you supposed to be running right through that engine coming out like a cute little fruit roll up"
        )
        is False
    )


def test_modern_cli_inline_confirmation_prompt_approves_pending_action(monkeypatch, capsys):
    session = ConfirmingSession()
    prompts = iter(["tell me about yourself", "y", "quit"])
    monkeypatch.setattr("builtins.input", lambda _prompt="": next(prompts))

    result = modern_cli._repl(session, show_trace=False)
    output = capsys.readouterr().out

    assert result == 0
    assert session.confirm_calls == [
        {"pending_action_id": "pending-1", "approved": True, "note": ""}
    ]
    assert "[pending action]" in output
    assert "System info check complete." in output


def test_modern_cli_inline_confirmation_prompt_declines_by_default(monkeypatch, capsys):
    session = ConfirmingSession()
    prompts = iter(["tell me about yourself", "", "quit"])
    monkeypatch.setattr("builtins.input", lambda _prompt="": next(prompts))

    result = modern_cli._repl(session, show_trace=False)
    output = capsys.readouterr().out

    assert result == 0
    assert session.confirm_calls == [
        {"pending_action_id": "pending-1", "approved": False, "note": ""}
    ]
    assert "Cancelled pending action" in output


def test_modern_cli_uses_selected_agent_name_for_reply_and_thinking(monkeypatch, capsys):
    session = TraceSession()
    session.engine.current_agent_name = "The Gremlin"
    prompts = iter(["hello", "quit"])
    monkeypatch.setattr("builtins.input", lambda _prompt="": next(prompts))

    result = modern_cli._repl(session, show_trace=False, watch_mode=True)
    output = capsys.readouterr().out

    assert result == 0
    assert "[The Gremlin thinking]" in output
    assert "[The Gremlin]" in output


def test_modern_cli_uses_agent_specific_boot_line(monkeypatch, capsys):
    session = StubSession()
    session.engine.current_agent_name = "SparkByte"
    prompts = iter(["quit"])
    monkeypatch.setattr("builtins.input", lambda _prompt="": next(prompts))

    result = modern_cli._repl(session, show_trace=False)
    output = capsys.readouterr().out

    assert result == 0
    assert "SparkByte hotwired and humming. Talk to me." in output


def test_modern_cli_direct_agent_switches_cover_gremlin_and_slappy(monkeypatch, capsys):
    session = SwitchingSession()
    prompts = iter(["/agent The Gremlin", "hello", "/agent Slappy", "hello again", "quit"])
    monkeypatch.setattr("builtins.input", lambda _prompt="": next(prompts))

    result = modern_cli._repl(session, show_trace=False)
    output = capsys.readouterr().out

    assert result == 0
    assert "Agent set to: The Gremlin" in output
    assert "[The Gremlin]" in output
    assert "The Gremlin reply" in output
    assert "Agent set to: Slappy" in output
    assert "[Slappy]" in output
    assert "Slappy reply" in output
