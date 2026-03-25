from __future__ import annotations

import json
import sys
from pathlib import Path
from types import SimpleNamespace

import requests

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))
for module_name in list(sys.modules):
    if module_name == "jl_platform" or module_name.startswith("jl_platform."):
        del sys.modules[module_name]

from jl_platform.core import quest_runtime as quest_runtime_module
from jl_platform.core import interpreter as interpreter_module
from jl_platform.core.interpreter import InterpreterSession
from jl_platform.core.quest_runtime import FatQuestRuntime, QuestAgent
from jl_platform.core.tools.PrivilegedMemoryForge import PrivilegedMemoryForge
from jl_platform.core.tools import bridge as bridge_module
from jl_platform.services.api import main as api_main


def _json_reply(payload: dict) -> str:
    return json.dumps(payload)


class FakeEngine:
    def __init__(self, replies: list[str]) -> None:
        self._replies = list(replies)
        self.calls: list[dict] = []

    def generate_response(self, user_message: str, agent_name: str | None = None, context: dict | None = None):
        self.calls.append(
            {
                "user_message": user_message,
                "agent_name": agent_name,
                "context": dict(context or {}),
            }
        )
        if not self._replies:
            raise AssertionError("No fake engine replies remaining.")
        return self._replies.pop(0), {"fake": True}, {}


class StubSession:
    def __init__(self) -> None:
        self.calls: list[dict] = []
        self.engine = SimpleNamespace(set_agent=lambda agent: None)

    def run(self, message: str, context: dict | None = None) -> dict:
        self.calls.append({"message": message, "context": dict(context or {})})
        return {"status": "ok", "final": "Auto mode handled this normally.", "tool_trace": []}

    def get_pending_action(self):
        return None


class RecordingEngine:
    def __init__(self, current_agent_name: str = "Forgebinder") -> None:
        self.current_agent_name = current_agent_name
        self.set_calls: list[str] = []

    def set_agent(self, agent: str) -> None:
        self.set_calls.append(agent)
        self.current_agent_name = agent


class DummyQuestEngine:
    def __init__(self, replies: list[str] | None = None, current_agent_name: str = "SparkByte") -> None:
        self.current_agent_name = current_agent_name
        self.set_calls: list[str] = []
        self._replies = list(replies or [])
        self.behavior_profile_name = "expressive"
        self.current_gait = "walk"
        self.current_rhythm_mode = "idle"
        self.emotional_aperture = SimpleNamespace(get_state=lambda: {"mode": "OPEN", "score": 0.5})

    def set_agent(self, agent: str) -> None:
        self.set_calls.append(agent)
        self.current_agent_name = agent

    def generate_response(self, user_message: str, agent_name: str | None = None, context: dict | None = None):
        if agent_name:
            self.current_agent_name = agent_name
        reply = self._replies.pop(0) if self._replies else f"{self.current_agent_name} handled it."
        telemetry = {
            "behavior_profile": self.behavior_profile_name,
            "cognitive_mode": "balanced",
            "active_gait_state": self.current_gait,
            "active_rhythm_pattern": self.current_rhythm_mode,
            "aperture_state": {"mode": "OPEN", "score": 0.5},
            "rhythm": {"mode": self.current_rhythm_mode, "index": 0.25},
        }
        return reply, telemetry, {}


def test_interpreter_plain_chat_returns_direct_final():
    session = InterpreterSession(
        engine=FakeEngine([_json_reply({"final": "Hello there."})]),
    )

    result = session.run("hello")

    assert result["status"] == "ok"
    assert result["final"] == "Hello there."
    assert result["tool_trace"] == []
    assert session.get_pending_action() is None


def test_action_detection_uses_latest_user_segment_in_transcript():
    session = InterpreterSession(engine=FakeEngine([_json_reply({"final": "ok"})]))
    transcript = (
        "SYSTEM: Attached context from MAIN_LOG\n"
        "USER: Were you able to execute this?\n"
        "ENGINE: Created file at C:\\Users\\J_lin\\Downloads\\reg\\JL_Engine-local-main\\artifacts\\fs_write_fallbacks\\new_file\n"
        "USER: Hello"
    )

    focused = session._action_detection_text(transcript)

    assert focused == "Hello"
    assert session._looks_like_action_request(transcript) is False


def test_interpreter_transcript_greeting_does_not_trigger_action_fallback():
    session = InterpreterSession(
        engine=FakeEngine([_json_reply({"final": "Hey there."})]),
        allow_direct_action_fallback=True,
    )
    transcript = (
        "SYSTEM: Attached context from MAIN_LOG\n"
        "USER: What can you tell me about the healing bench\n"
        "ENGINE: Created file at C:\\Users\\J_lin\\Downloads\\reg\\JL_Engine-local-main\\artifacts\\fs_write_fallbacks\\new_file\n"
        "USER: Hello"
    )

    result = session.run(transcript)

    assert result["status"] == "ok"
    assert result["final"] == "Hey there."
    assert result["tool_trace"] == []


def test_interpreter_action_request_errors_when_direct_fallback_disabled():
    session = InterpreterSession(
        engine=FakeEngine([_json_reply({"final": "Acknowledged."})]),
        allow_direct_action_fallback=False,
    )

    result = session.run("create a file called notes.txt")

    assert result["status"] == "error"
    assert result["error"] == "action_request_not_executed_no_fallback"


def test_interpreter_risky_tool_requires_confirmation_without_chat_fallback():
    session = InterpreterSession(
        engine=FakeEngine([_json_reply({"tool": "run_shell", "input": {"command": "echo hello"}})]),
    )

    result = session.run("hello there")

    assert result["status"] == "confirmation_required"
    pending = session.get_pending_action()
    assert pending is not None
    assert pending["tool"] == "run_shell"


def test_interpreter_read_only_bridge_executes_without_confirmation():
    session = InterpreterSession(
        engine=FakeEngine(
            [
                _json_reply({"tool": "bridge_local", "input": {"mode": "fs_list", "data": {"path": "."}}}),
                _json_reply({"final": "Here are the current files."}),
            ]
        ),
    )
    tool_calls: list[tuple[str, dict]] = []

    def fake_call(tool_name: str, payload: dict) -> dict:
        tool_calls.append((tool_name, payload))
        return {"status": "ok", "entries": [{"name": "notes.txt"}]}

    session._call_tool = fake_call  # type: ignore[method-assign]

    result = session.run("show me the current files")

    assert result["status"] == "ok"
    assert result["final"] == "Here are the current files."
    assert len(result["tool_trace"]) == 1
    assert result["tool_trace"][0]["tool"] == "bridge_local"
    assert tool_calls == [("bridge_local", {"mode": "fs_list", "data": {"path": "."}})]
    assert session.get_pending_action() is None


def test_interpreter_browser_inspect_executes_without_confirmation():
    session = InterpreterSession(
        engine=FakeEngine(
            [
                _json_reply(
                    {
                        "tool": "bridge_local",
                        "input": {"mode": "browser_inspect", "data": {"url": "https://example.com"}},
                    }
                ),
                _json_reply({"final": "I inspected the page."}),
            ]
        ),
    )
    tool_calls: list[tuple[str, dict]] = []

    def fake_call(tool_name: str, payload: dict) -> dict:
        tool_calls.append((tool_name, payload))
        return {
            "status": "ok",
            "result": {"status": "ok", "title": "Example Domain", "url": "https://example.com"},
        }

    session._call_tool = fake_call  # type: ignore[method-assign]

    result = session.run("inspect the current browser page")

    assert result["status"] == "ok"
    assert result["final"] == "I inspected the page."
    assert len(result["tool_trace"]) == 1
    assert tool_calls == [
        ("bridge_local", {"mode": "browser_inspect", "data": {"url": "https://example.com"}})
    ]
    assert session.get_pending_action() is None


def test_interpreter_browser_inspect_falls_back_to_tool_summary_when_model_drifts():
    session = InterpreterSession(
        engine=FakeEngine(
            [
                _json_reply(
                    {
                        "tool": "bridge_local",
                        "input": {"mode": "browser_inspect", "data": {"url": "https://example.com"}},
                    }
                ),
                _json_reply({"final": "flatMap({ weird nonsense })"}),
            ]
        ),
    )

    def fake_call(tool_name: str, payload: dict) -> dict:
        return {
            "status": "ok",
            "result": {
                "status": "ok",
                "title": "Example Domain",
                "url": "https://example.com/",
                "visible_text": "Example Domain This domain is for use in documentation examples.",
            },
        }

    session._call_tool = fake_call  # type: ignore[method-assign]

    result = session.run("Inspect https://example.com and tell me the page title in one sentence.")

    assert result["status"] == "ok"
    assert result["final"] == "The page title is Example Domain."
    assert len(result["tool_trace"]) == 1


def test_interpreter_fs_list_falls_back_to_file_summary_when_model_drifts():
    session = InterpreterSession(
        engine=FakeEngine(
            [
                _json_reply(
                    {
                        "tool": "bridge_local",
                        "input": {"mode": "fs_list", "data": {"path": "."}},
                    }
                ),
                _json_reply({"final": "<unused2526>"}),
            ]
        ),
    )

    def fake_call(tool_name: str, payload: dict) -> dict:
        return {
            "status": "ok",
            "result": {
                "status": "ok",
                "path": ".",
                "entries": [{"name": "README.md"}, {"name": "src"}, {"name": "tests"}],
            },
        }

    session._call_tool = fake_call  # type: ignore[method-assign]

    result = session.run("show me the current files")

    assert result["status"] == "ok"
    assert result["final"] == "Here are the current files: README.md, src, tests."
    assert len(result["tool_trace"]) == 1


def test_interpreter_preamble_lists_real_bridge_modes_and_windows_shell_rules():
    preamble = interpreter_module.SYSTEM_PREAMBLE

    assert "browser_action" in preamble
    assert "browser_inspect" in preamble
    assert "fs_mkdir" in preamble
    assert "fs_write" in preamble
    assert "Valid `bridge_local` modes are exactly" in preamble


def test_interpreter_write_requires_confirmation_and_approval_executes_once():
    session = InterpreterSession(
        engine=FakeEngine(
            [
                _json_reply(
                    {
                        "tool": "bridge_local",
                        "input": {"mode": "fs_write", "data": {"path": "notes.txt", "content": "hello"}},
                    }
                ),
                _json_reply({"final": "Saved notes.txt."}),
            ]
        ),
    )
    tool_calls: list[tuple[str, dict]] = []

    def fake_call(tool_name: str, payload: dict) -> dict:
        tool_calls.append((tool_name, payload))
        return {"status": "ok", "path": payload["data"]["path"], "bytes": len(payload["data"]["content"])}

    session._call_tool = fake_call  # type: ignore[method-assign]

    first = session.run("write hello into notes.txt")

    assert first["status"] == "confirmation_required"
    pending = first["pending_action"]
    assert pending["tool"] == "bridge_local"
    assert pending["risk_level"] == "high"
    assert tool_calls == []
    assert session.get_pending_action()["id"] == pending["id"]

    reminder = session.run("do something else")
    assert reminder["status"] == "confirmation_required"
    assert reminder["pending_action"]["id"] == pending["id"]
    assert tool_calls == []

    approved = session.confirm_pending_action(pending["id"], approved=True)

    assert approved["status"] == "ok"
    assert approved["final"] == "Saved notes.txt."
    assert len(tool_calls) == 1
    assert tool_calls[0] == (
        "bridge_local",
        {"mode": "fs_write", "data": {"path": "notes.txt", "content": "hello"}},
    )
    assert session.get_pending_action() is None


def test_confirm_pending_action_replays_original_request_with_tool_result():
    engine = FakeEngine(
        [
            _json_reply(
                {
                    "tool": "bridge_local",
                    "input": {"mode": "fs_write", "data": {"path": "notes.txt", "content": "hello"}},
                }
            ),
            _json_reply({"final": "Saved notes.txt."}),
        ]
    )
    session = InterpreterSession(engine=engine)
    session._call_tool = lambda tool_name, payload: {"status": "ok", "path": "notes.txt", "bytes": 5}  # type: ignore[assignment]

    first = session.run("write hello into notes.txt")
    session.confirm_pending_action(first["pending_action"]["id"], approved=True)

    assert len(engine.calls) == 2
    resumed_prompt = engine.calls[1]["user_message"]
    assert "ORIGINAL USER REQUEST:" in resumed_prompt
    assert "write hello into notes.txt" in resumed_prompt
    assert "TOOL_RESULT for bridge_local:" in resumed_prompt


def test_interpreter_run_cc_write_requires_confirmation():
    session = InterpreterSession(
        engine=FakeEngine(
            [
                _json_reply(
                    {
                        "tool": "run_cc_command",
                        "input": {
                            "action": "fs_write",
                            "path": "notes.txt",
                            "content": "hello",
                        },
                    }
                )
            ]
        ),
    )

    result = session.run("create notes.txt with hello")

    assert result["status"] == "confirmation_required"
    pending = session.get_pending_action()
    assert pending is not None
    assert pending["tool"] == "run_cc_command"
    assert pending["risk_level"] == "high"


def test_confirm_pending_action_falls_back_to_clean_folder_result_when_model_drifts(monkeypatch, tmp_path: Path):
    desktop = tmp_path / "Desktop"
    desktop.mkdir()
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    session = InterpreterSession(
        engine=FakeEngine(
            [
                _json_reply(
                    {
                        "tool": "bridge_local",
                        "input": {
                            "mode": "fs_create",
                            "data": {
                                "path": "C:\\Users\\YourUsername\\Desktop\\Squishy_drift",
                                "name": "Squishy_drift",
                            },
                        },
                    }
                ),
                _json_reply({"final": "TOUCHING: src/jl_platform/core/interpreter.py"}),
            ]
        ),
    )
    session._call_tool = lambda tool_name, payload: {  # type: ignore[assignment]
        "status": "ok",
        "result": {"path": payload["data"]["path"], "exists": True, "is_dir": True},
    }

    first = session.run("Create a folder on my desktop called Squishy_drift")
    approved = session.confirm_pending_action(first["pending_action"]["id"], approved=True)

    assert approved["status"] == "ok"
    assert approved["final"].endswith("\\Desktop\\Squishy_drift.")
    assert approved["reply"] == approved["final"]


def test_confirm_pending_action_collapses_repeated_shell_confirmation_into_completed_reply():
    session = InterpreterSession(
        engine=FakeEngine(
            [
                _json_reply(
                    {
                        "tool": "run_shell",
                        "input": {"command": "Get-Location", "cwd": "."},
                    }
                ),
                _json_reply(
                    {
                        "tool": "run_shell",
                        "input": {"command": "Get-Location", "cwd": "."},
                    }
                ),
            ]
        ),
    )
    session._call_tool = lambda tool_name, payload: {  # type: ignore[assignment]
        "stdout": "C:\\repo\\path\n",
        "stderr": "",
        "returncode": 0,
        "ok": True,
    }

    first = session.run("Run a PowerShell command that prints the current location using Get-Location.")
    approved = session.confirm_pending_action(first["pending_action"]["id"], approved=True)

    assert approved["status"] == "ok"
    assert approved["final"] == "C:\\repo\\path"
    assert approved["reply"] == approved["final"]
    assert session.get_pending_action() is None


def test_interpreter_conversational_meta_request_requires_confirmation_for_high_risk_tool():
    session = InterpreterSession(
        engine=FakeEngine(
            [
                _json_reply(
                    {
                        "tool": "run_shell",
                        "input": {"command": "Get-ComputerInfo", "cwd": "."},
                    }
                ),
                "I'm SparkByte, running in the JL Engine local console. If you want exact machine specs, ask me to inspect the system and I'll check it directly.",
            ]
        )
    )

    result = session.run("Tell me what you are and what system this is.")

    assert result["status"] == "confirmation_required"
    pending = session.get_pending_action()
    assert pending is not None
    assert pending["tool"] == "run_shell"


def test_interpreter_greeting_requires_confirmation_for_high_risk_tool():
    session = InterpreterSession(
        engine=FakeEngine(
            [
                _json_reply(
                    {
                        "tool": "run_shell",
                        "input": {"command": "Get-ComputerInfo", "cwd": "."},
                    }
                ),
                "All good over here. I'm upright, awake, and ready to roll.",
            ]
        )
    )

    result = session.run("hey how goes it?")

    assert result["status"] == "confirmation_required"
    pending = session.get_pending_action()
    assert pending is not None
    assert pending["tool"] == "run_shell"


def test_interpreter_folder_create_aliases_fs_create_to_real_mkdir(monkeypatch, tmp_path: Path):
    desktop = tmp_path / "Desktop"
    desktop.mkdir()
    monkeypatch.setenv("USERPROFILE", str(tmp_path))

    session = InterpreterSession(
        engine=FakeEngine(
            [
                _json_reply(
                    {
                        "tool": "bridge_local",
                        "input": {
                            "mode": "fs_create",
                            "data": {
                                "path": "C:\\Users\\YourUsername\\Desktop\\Squishy2",
                                "name": "Squishy2",
                            },
                        },
                    }
                ),
                _json_reply({"final": "Squishy2 is on your desktop."}),
            ]
        ),
    )
    tool_calls: list[tuple[str, dict]] = []

    def fake_call(tool_name: str, payload: dict) -> dict:
        tool_calls.append((tool_name, payload))
        return {"status": "ok", "path": payload["data"]["path"], "exists": True, "is_dir": True}

    session._call_tool = fake_call  # type: ignore[method-assign]

    first = session.run("Create a folder on my desktop called Squishy2")

    assert first["status"] == "confirmation_required"
    pending = first["pending_action"]
    assert pending["tool"] == "bridge_local"
    assert pending["input"]["mode"] == "fs_mkdir"
    assert pending["input"]["data"]["path"].endswith("\\Desktop\\Squishy2")
    assert pending["summary"] == f"create folder `{pending['input']['data']['path']}`"

    approved = session.confirm_pending_action(pending["id"], approved=True)

    assert approved["status"] == "ok"
    assert approved["final"] == "Squishy2 is on your desktop."
    assert tool_calls == [
        (
            "bridge_local",
            {"mode": "fs_mkdir", "data": {"path": pending["input"]["data"]["path"], "name": "Squishy2"}},
        )
    ]
    assert session.get_pending_action() is None


def test_interpreter_normalizes_placeholder_desktop_path_in_pending_action(monkeypatch, tmp_path: Path):
    desktop = tmp_path / "Desktop"
    desktop.mkdir()
    monkeypatch.setenv("USERPROFILE", str(tmp_path))

    session = InterpreterSession(
        engine=FakeEngine(
            [
                _json_reply(
                    {
                        "tool": "bridge_local",
                        "input": {
                            "mode": "fs_write",
                            "data": {
                                "path": "C:\\Users\\YourUsername\\Desktop\\jl_test_note.txt",
                                "content": "hello from JL Engine",
                            },
                        },
                    }
                )
            ]
        ),
    )

    result = session.run("Create a text file named jl_test_note.txt on my desktop containing hello from JL Engine")

    assert result["status"] == "confirmation_required"
    pending = result["pending_action"]
    normalized_path = str(pending["input"]["data"]["path"])
    assert "YourUsername" not in normalized_path
    assert normalized_path.endswith("\\Desktop\\jl_test_note.txt")
    assert pending["summary"] == f"write `{normalized_path}`"


def test_interpreter_normalizes_unixish_desktop_path_into_local_desktop(monkeypatch, tmp_path: Path):
    desktop = tmp_path / "Desktop"
    desktop.mkdir(parents=True)
    monkeypatch.setenv("USERPROFILE", str(tmp_path))

    session = InterpreterSession(engine=FakeEngine([_json_reply({"final": "ok"})]))

    normalized = session._normalize_placeholder_fs_path(
        "//Users/admin/Desktop/Squishy 2",
        "Put a folder on my desktop named Squishy 2",
    )

    assert normalized.endswith("\\Desktop\\Squishy 2")


def test_extract_folder_name_prefers_actual_name_over_sentence_noise():
    session = InterpreterSession(engine=FakeEngine([_json_reply({"final": "ok"})]))

    assert (
        session._extract_folder_name("on my desktop just a new folder empty you can call it squishy")
        == "squishy"
    )
    assert session._extract_folder_name("make a folder called squishy on my desktop") == "squishy"


def test_interpreter_reject_clears_pending_action_without_running_tool():
    session = InterpreterSession(
        engine=FakeEngine(
            [
                _json_reply(
                    {
                        "tool": "bridge_local",
                        "input": {"mode": "fs_write", "data": {"path": "draft.txt", "content": "stop"}},
                    }
                )
            ]
        ),
    )
    tool_calls: list[tuple[str, dict]] = []
    session._call_tool = lambda tool_name, payload: tool_calls.append((tool_name, payload))  # type: ignore[assignment]

    first = session.run("write draft.txt")
    rejected = session.confirm_pending_action(first["pending_action"]["id"], approved=False, note="not yet")

    assert rejected["status"] == "ok"
    assert rejected["cancelled"] is True
    assert "Cancelled pending action" in rejected["final"]
    assert "not yet" in rejected["final"]
    assert tool_calls == []
    assert session.get_pending_action() is None


def test_interpreter_synthetic_turn_preserves_suppression_flags():
    engine = FakeEngine([_json_reply({"final": "Loop turn ok."})])
    session = InterpreterSession(engine=engine)

    result = session.run(
        "Continue assisting the user using the current session context when helpful.",
        context={"synthetic_turn": True, "suppress_feedback_log": True},
    )

    assert result["status"] == "ok"
    assert engine.calls[0]["context"]["synthetic_turn"] is True
    assert engine.calls[0]["context"]["suppress_memory_write"] is True
    assert engine.calls[0]["context"]["suppress_feedback_log"] is True


def test_interpreter_tool_planning_turn_suppresses_memory_write():
    engine = FakeEngine(
        [
            _json_reply(
                {
                    "tool": "run_shell",
                    "input": {"command": "Get-ChildItem -Force", "cwd": "."},
                }
            ),
            _json_reply({"final": "Here are the current files."}),
        ]
    )
    session = InterpreterSession(engine=engine)

    result = session.run("show me the files")

    assert result["status"] == "ok"
    assert engine.calls[0]["context"]["interpreter_mode"] is True
    assert engine.calls[0]["context"]["suppress_memory_write"] is True


def test_interpreter_coerces_safe_shell_file_listing_into_bridge_read_only():
    session = InterpreterSession(
        engine=FakeEngine(
            [
                _json_reply(
                    {
                        "tool": "run_shell",
                        "input": {"command": "Get-ChildItem -Force", "cwd": "."},
                    }
                ),
                _json_reply({"final": "Here are the current files."}),
            ]
        ),
    )
    tool_calls: list[tuple[str, dict]] = []

    def fake_call(tool_name: str, payload: dict) -> dict:
        tool_calls.append((tool_name, payload))
        return {"status": "ok", "entries": [{"name": "README.md"}]}

    session._call_tool = fake_call  # type: ignore[method-assign]

    result = session.run("show me the current files")

    assert result["status"] == "ok"
    assert result["final"] == "Here are the current files."
    assert tool_calls == [("bridge_local", {"mode": "fs_list", "data": {"path": "."}})]
    assert session.get_pending_action() is None


def test_chat_auto_uses_interpreter_path_even_for_normal_messages(monkeypatch):
    runtime = FatQuestRuntime()
    session = StubSession()
    agent = QuestAgent(
        agent_id="jl_fat_agent",
        agent="SparkByte",
        session=session,
        forge=PrivilegedMemoryForge(),
    )
    runtime._agents[agent.agent_id] = agent
    monkeypatch.setattr(runtime, "_activate_engine", lambda engine: None)

    result = runtime._chat_impl(
        agent_id=agent.agent_id,
        message="hello there",
        agent="SparkByte",
        context={"ui_surface": "chat_tab"},
        execution_mode="auto",
        return_trace=True,
        allow_clone=False,
    )

    assert result["status"] == "ok"
    assert result["mode_used"] == "auto"
    assert result["reply"] == "Auto mode handled this normally."
    assert len(session.calls) == 1
    assert session.calls[0]["message"] == "hello there"
    assert session.calls[0]["context"]["quest_mode"] == "main_chat_auto"


def test_chat_impl_auto_approves_confirmation_required_when_enabled(monkeypatch):
    runtime = FatQuestRuntime()

    class AutoApproveSession:
        def __init__(self) -> None:
            self.engine = SimpleNamespace(
                set_agent=lambda _agent: None,
                current_agent_name="SparkByte",
            )
            self.pending_id = "pending-1"

        def run(self, message: str, context: dict | None = None, event_sink=None) -> dict:
            return {
                "status": "confirmation_required",
                "final": "Awaiting confirmation: run shell command `echo hello`.",
                "pending_action": {
                    "id": self.pending_id,
                    "tool": "run_shell",
                    "input": {"command": "echo hello"},
                    "summary": "run shell command `echo hello`",
                    "risk_level": "high",
                },
                "tool_trace": [],
            }

        def confirm_pending_action(
            self,
            pending_action_id: str,
            *,
            approved: bool,
            note: str = "",
            event_sink=None,
        ) -> dict:
            assert approved is True
            assert pending_action_id == self.pending_id
            return {
                "status": "ok",
                "final": "Executed `echo hello`.",
                "tool_trace": [{"tool": "run_shell", "input": {"command": "echo hello"}}],
            }

        def get_pending_action(self):
            return None

    agent = QuestAgent(
        agent_id="jl_fat_agent",
        agent="SparkByte",
        session=AutoApproveSession(),
        forge=PrivilegedMemoryForge(),
    )
    runtime._agents[agent.agent_id] = agent
    monkeypatch.setattr(runtime, "_activate_engine", lambda engine: None)

    result = runtime._chat_impl(
        agent_id=agent.agent_id,
        message="say hello",
        agent="SparkByte",
        context={"auto_approve_actions": True},
        execution_mode="execute",
        return_trace=True,
        allow_clone=False,
    )

    assert result["status"] == "ok"
    assert result["reply"] == "Executed `echo hello`."
    assert result["auto_approved"] is True
    assert result["auto_approve_count"] == 1


def test_sync_agent_agent_reasserts_selected_agent_on_engine(monkeypatch):
    runtime = FatQuestRuntime()
    engine = RecordingEngine()
    session = SimpleNamespace(engine=engine)
    agent = QuestAgent(
        agent_id="jl_fat_agent",
        agent="SparkByte",
        session=session,
        forge=PrivilegedMemoryForge(),
    )
    monkeypatch.setattr(runtime, "_activate_engine", lambda current_engine: None)

    runtime._sync_agent_agent(agent, "SparkByte")

    assert agent.agent == "SparkByte"
    assert engine.current_agent_name == "SparkByte"
    assert engine.set_calls == ["SparkByte"]


def test_main_chat_context_respects_selected_agent():
    runtime = FatQuestRuntime()

    auto_context = runtime._sharp_context({}, mode="main_chat_auto")
    chat_context = runtime._sharp_context({}, mode="main_chat")
    execute_context = runtime._sharp_context({}, mode="main_chat_execute")

    assert auto_context["respect_selected_agent"] is True
    assert chat_context["respect_selected_agent"] is True
    assert execute_context["respect_selected_agent"] is True


def test_register_mpf_agent_agent_uses_registry_binding(tmp_path: Path, monkeypatch):
    agents_dir = tmp_path / "agents"
    agents_dir.mkdir()
    registry_path = agents_dir / "JL_Agents.mpf.json"
    agent_path = agents_dir / "SparkByte.json"
    agent_path.write_text(json.dumps({"identity": {"name": "SparkByte"}}), encoding="utf-8")
    registry_path.write_text(
        json.dumps({"SparkByte": {"jl_agent_file": "SparkByte.json"}}, indent=2),
        encoding="utf-8",
    )

    runtime = FatQuestRuntime()
    runtime._agents_dir = agents_dir
    runtime._registry_path = registry_path
    captured: dict[str, str] = {}

    def fake_register_agent(
        agent_id: str,
        agent_name: str = "SparkByte",
        parent_agent_id: str | None = None,
    ):
        captured["agent_id"] = agent_id
        captured["agent"] = agent_name
        return {"status": "ok", "agent": {"agent_id": agent_id, "agent": agent_name}}

    monkeypatch.setattr(runtime, "register_agent", fake_register_agent)
    monkeypatch.setattr(runtime, "_set_agent_loop_persistent", lambda agent_id, value: None)
    monkeypatch.setattr(runtime, "_ensure_agent_loop", lambda agent_id: None)

    result = runtime.register_mpf_agent_agent("jl_fat_agent", "sparkbyte")

    assert result["status"] == "ok"
    assert captured == {"agent_id": "jl_fat_agent", "agent": "SparkByte"}
    assert result["agent_name"] == "SparkByte"
    assert result["jl_agent_file"] == "SparkByte.json"
    assert result["path"] == str(agent_path)


def test_start_agent_loop_uses_agent_name(monkeypatch):
    runtime = FatQuestRuntime()
    captured: dict[str, str] = {}

    def fake_ensure_agent(agent_id: str, agent_name: str = "SparkByte"):
        captured["agent_id"] = agent_id
        captured["agent_name"] = agent_name
        return SimpleNamespace()

    monkeypatch.setattr(runtime, "ensure_agent", fake_ensure_agent)
    monkeypatch.setattr(runtime, "_ensure_agent_loop", lambda agent_id: captured.setdefault("loop_id", agent_id))
    monkeypatch.setattr(runtime, "_loop_snapshot", lambda agent_id: {"agent_id": agent_id, "running": True})

    result = runtime.start_agent_loop("agent-1", agent_name="SparkByte")

    assert result["status"] == "ok"
    assert captured["agent_id"] == "agent-1"
    assert captured["agent_name"] == "SparkByte"
    assert captured["loop_id"] == "agent-1"


def test_loop_start_api_paths_pass_agent_name(monkeypatch):
    captured: dict[str, tuple[str, str]] = {}

    def fake_start_agent_loop(agent_id: str, agent_name: str | None = None):
        captured["quest_loop"] = (agent_id, agent_name or "")
        return {"status": "ok", "agent_id": agent_id, "loop": {"agent_id": agent_id, "running": True}}

    def fake_ensure_agent(agent_id: str, agent_name: str = "SparkByte"):
        captured["chat_loop"] = (agent_id, agent_name)
        return SimpleNamespace(session=SimpleNamespace(get_pending_action=lambda: None))

    class DummyThread:
        def __init__(self, *args, **kwargs) -> None:
            self._alive = False

        def start(self) -> None:
            self._alive = False

        def is_alive(self) -> bool:
            return self._alive

    monkeypatch.setattr(api_main, "_CHAT_LOOP_THREADS", {})
    monkeypatch.setattr(api_main, "_CHAT_LOOP_STOPS", {})
    monkeypatch.setattr(api_main, "_CHAT_LOOP_STATE", {})
    monkeypatch.setattr(api_main._QUEST_RUNTIME, "start_agent_loop", fake_start_agent_loop)
    monkeypatch.setattr(api_main._QUEST_RUNTIME, "ensure_agent", fake_ensure_agent)
    monkeypatch.setattr(api_main, "Thread", DummyThread)

    quest_result = api_main.quest_loop_start(api_main.QuestLoopStartRequest(agent="SparkByte"))
    chat_result = api_main._start_chat_loop(
        api_main.ChatLoopStartRequest(agent="SparkByte", autostart_agent_loop=False)
    )

    assert quest_result["status"] == "ok"
    assert captured["quest_loop"] == (api_main.JL_FAT_AGENT_ID, "SparkByte")
    assert chat_result["status"] == "ok"
    assert captured["chat_loop"] == (api_main.JL_FAT_AGENT_ID, "SparkByte")


def test_register_agent_api_path_passes_agent_name(monkeypatch):
    captured: dict[str, str] = {}

    def fake_register_agent(
        agent_id: str,
        agent_name: str = "SparkByte",
        parent_agent_id: str | None = None,
    ):
        captured["agent_id"] = agent_id
        captured["agent_name"] = agent_name
        return {"status": "ok", "agent": {"agent_id": agent_id, "agent": agent_name}}

    monkeypatch.setattr(api_main._QUEST_RUNTIME, "register_agent", fake_register_agent)

    result = api_main.quest_register_agent(api_main.QuestAgentRegisterRequest(agent="SparkByte"))

    assert result["status"] == "ok"
    assert captured == {"agent_id": api_main.JL_FAT_AGENT_ID, "agent_name": "SparkByte"}


def test_switchboard_exposes_three_lanes_with_three_children():
    runtime = FatQuestRuntime()

    result = runtime.get_switchboard()
    lanes = result["lanes"]

    assert result["status"] == "ok"
    assert result["default_lane"] == "fat_agent"
    assert sorted(lanes.keys()) == ["fat_agent", "generated", "jl_agent"]
    assert len(lanes["fat_agent"]["children"]) == 3
    assert len(lanes["jl_agent"]["children"]) == 3
    assert len(lanes["generated"]["children"]) == 3


def test_runtime_loop_timeout_defaults_for_local_machine(monkeypatch):
    monkeypatch.delenv("JL_AGENT_LOOP_TIMEOUT_SECONDS", raising=False)

    runtime = FatQuestRuntime()

    assert runtime._loop_task_timeout_seconds == 420.0


def test_runtime_loop_timeout_can_be_overridden(monkeypatch):
    monkeypatch.setenv("JL_AGENT_LOOP_TIMEOUT_SECONDS", "300")

    runtime = FatQuestRuntime()

    assert runtime._loop_task_timeout_seconds == 300.0


def test_switch_agent_updates_lane_and_child(monkeypatch):
    runtime = FatQuestRuntime()
    monkeypatch.setattr(runtime, "_activate_engine", lambda engine: None)
    monkeypatch.setattr(quest_runtime_module, "JLEngineCore", DummyQuestEngine)

    result = runtime.switch_agent(agent_id="agent-1", lane="jl_agent", child="Forgebinder")

    assert result["status"] == "ok"
    assert result["selection"]["lane"] == "jl_agent"
    assert result["selection"]["child"] == "Forgebinder"
    assert result["selection"]["agent_name"] == "Forgebinder"
    assert result["agent"]["active_lane"] == "jl_agent"
    assert result["agent"]["active_child"] == "Forgebinder"


def test_generated_switch_creates_and_reuses_instance(tmp_path: Path, monkeypatch):
    runtime = FatQuestRuntime()
    runtime._agents_dir = tmp_path / "agents"
    runtime._generated_agents_dir = runtime._agents_dir / "generated"
    runtime._registry_path = runtime._agents_dir / "JL_Agents.mpf.json"
    runtime._registry_path_alt = runtime._agents_dir / "JL_Agents.mpf"
    monkeypatch.setattr(runtime, "_activate_engine", lambda engine: None)
    monkeypatch.setattr(quest_runtime_module, "JLEngineCore", DummyQuestEngine)

    first = runtime.switch_agent(agent_id="main", lane="generated", child="Task Helper")
    second = runtime.switch_agent(agent_id="main", lane="generated", child="Task Helper")

    assert first["status"] == "ok"
    assert first["selection"]["lane"] == "generated"
    assert first["selection"]["generated_instance_id"]
    assert second["selection"]["generated_instance_id"] == first["selection"]["generated_instance_id"]

    registry = runtime._load_registry()
    entry = registry[first["selection"]["agent_name"]]
    assert entry["classification"] == "generated"
    assert entry["switchboard"]["child"] == "Task Helper"
    assert (runtime._agents_dir / entry["jl_agent_file"]).exists()
    assert not runtime._registry_path.exists()


def test_chat_delegation_merges_back_into_parent_reply(monkeypatch):
    runtime = FatQuestRuntime()
    monkeypatch.setattr(runtime, "_activate_engine", lambda engine: None)

    parent = QuestAgent(
        agent_id="main",
        agent="SparkByte",
        session=SimpleNamespace(engine=DummyQuestEngine(["Merged SparkByte reply."]), get_pending_action=lambda: None),
        forge=PrivilegedMemoryForge(),
    )
    helper = QuestAgent(
        agent_id="main__delegate__jl_agent__SaaS_Copywriter",
        agent="SaaS Copywriter",
        session=SimpleNamespace(
            engine=DummyQuestEngine(["Delegated SaaS specialist output."]),
            get_pending_action=lambda: None,
        ),
        forge=PrivilegedMemoryForge(),
    )

    def fake_ensure_agent(agent_id: str, agent_name: str = "SparkByte"):
        if agent_id.startswith("main__delegate__"):
            return helper
        return parent

    monkeypatch.setattr(runtime, "ensure_agent", fake_ensure_agent)

    result = runtime._chat_impl(
        agent_id="main",
        message="Help me write SaaS conversion copy for a landing page",
        execution_mode="chat",
        allow_clone=False,
    )

    assert result["status"] == "ok"
    assert result["reply"] == "Merged SparkByte reply."
    assert result["lane"] == "fat_agent"
    assert result["child"] == "SparkByte"
    assert result["delegated_class"] == "jl_agent"
    assert result["delegated_to"] == "SaaS Copywriter"


def test_chat_all_worker_mode_merges_multiple_delegates(monkeypatch):
    runtime = FatQuestRuntime()
    monkeypatch.setattr(runtime, "_activate_engine", lambda engine: None)

    parent = QuestAgent(
        agent_id="main",
        agent="SparkByte",
        session=SimpleNamespace(engine=DummyQuestEngine(["Merged crew reply."]), get_pending_action=lambda: None),
        forge=PrivilegedMemoryForge(),
    )
    helpers: dict[str, QuestAgent] = {}

    def fake_ensure_agent(agent_id: str, agent_name: str = "SparkByte"):
        if not agent_id.startswith("main__delegate__"):
            return parent
        helper = helpers.get(agent_id)
        if helper is None:
            helper = QuestAgent(
                agent_id=agent_id,
                agent=agent_name,
                session=SimpleNamespace(
                    engine=DummyQuestEngine([f"{agent_id} worker output."]),
                    get_pending_action=lambda: None,
                ),
                forge=PrivilegedMemoryForge(),
            )
            helpers[agent_id] = helper
        return helper

    monkeypatch.setattr(runtime, "ensure_agent", fake_ensure_agent)

    result = runtime._chat_impl(
        agent_id="main",
        message="Implement python tooling, draft SaaS copy, and produce a YouTube script outline",
        context={"delegation_mode": "all", "delegate_max_workers": 3},
        execution_mode="chat",
        allow_clone=False,
    )

    assert result["status"] == "ok"
    assert result["reply"] == "Merged crew reply."
    assert result["delegated_class"] == "multi"
    assert result["delegation_count"] == 3
    assert len(result["delegated_workers"]) == 3
    assert all(worker["agent_name"] for worker in result["delegated_workers"])


def test_delegated_workers_use_session_run_in_execute_mode(monkeypatch):
    runtime = FatQuestRuntime()
    monkeypatch.setattr(runtime, "_activate_engine", lambda engine: None)

    parent = QuestAgent(
        agent_id="main",
        agent="SparkByte",
        session=SimpleNamespace(engine=DummyQuestEngine(["Merged execution reply."]), get_pending_action=lambda: None),
        forge=PrivilegedMemoryForge(),
    )
    delegated_calls: list[dict[str, object]] = []

    class HelperSession:
        def __init__(self) -> None:
            self.engine = DummyQuestEngine(["helper chat fallback"])

        def run(self, message: str, context: dict | None = None):
            delegated_calls.append({"message": message, "context": dict(context or {})})
            return {
                "status": "ok",
                "final": "helper executed",
                "tool_trace": [{"tool": "run_shell"}],
            }

        def get_pending_action(self):
            return None

    helper = QuestAgent(
        agent_id="main__delegate__jl_agent__Forgebinder",
        agent="Forgebinder",
        session=HelperSession(),
        forge=PrivilegedMemoryForge(),
    )

    def fake_ensure_agent(agent_id: str, agent_name: str = "SparkByte"):
        if agent_id.startswith("main__delegate__"):
            return helper
        return parent

    monkeypatch.setattr(runtime, "ensure_agent", fake_ensure_agent)

    result = runtime._chat_impl(
        agent_id="main",
        message="debug this python error and run fixes",
        context={"delegation_mode": "all", "delegate_max_workers": 1, "delegated_execution_mode": "execute"},
        execution_mode="execute",
        allow_clone=False,
    )

    assert result["status"] == "ok"
    assert result["executed"] is True
    assert delegated_calls
    assert result["delegated_workers"][0]["executed"] is True
    assert result["delegated_workers"][0]["tool_trace_count"] == 1


def test_agentic_profile_reads_forge_first_with_external_fallback(monkeypatch):
    runtime = FatQuestRuntime()
    monkeypatch.setattr(
        runtime,
        "_load_agent_payload_by_name",
        lambda _name: {
            "meta": {
                "agentic": {
                    "tool_mode": "forge_first",
                    "external_fallback": True,
                    "execution_mode": "execute",
                    "delegated_execution_mode": "execute",
                    "delegation_mode": "all",
                    "delegate_max_workers": 4,
                    "allow_direct_action_fallback": True,
                }
            }
        },
    )

    profile = runtime._resolve_agentic_profile("SparkByte")

    assert profile["tool_mode"] == "forge_first"
    assert profile["external_fallback"] is True
    assert profile["execution_mode"] == "execute"
    assert profile["delegated_execution_mode"] == "execute"
    assert profile["delegation_mode"] == "all"
    assert profile["delegate_max_workers"] == 4
    assert profile["allow_direct_action_fallback"] is True


def test_agentic_profile_accepts_external_tool_fallback_alias(monkeypatch):
    runtime = FatQuestRuntime()
    monkeypatch.setattr(
        runtime,
        "_load_agent_payload_by_name",
        lambda _name: {
            "agentic": {
                "tool_mode": "forge_first",
                "external_tool_fallback": False,
            }
        },
    )

    profile = runtime._resolve_agentic_profile("SparkByte")

    assert profile["tool_mode"] == "forge_first"
    assert profile["external_fallback"] is False


def test_quest_chat_api_passes_lane_child_and_instance_flag(monkeypatch):
    captured: dict[str, object] = {}

    def fake_chat(
        *,
        agent_id: str,
        message: str,
        agent: str | None = None,
        lane: str | None = None,
        child: str | None = None,
        new_instance: bool = False,
        context: dict | None = None,
        execution_mode: str = "auto",
        return_trace: bool = True,
        allow_clone: bool = True,
    ):
        captured.update(
            {
                "agent_id": agent_id,
                "message": message,
                "agent": agent,
                "lane": lane,
                "child": child,
                "new_instance": new_instance,
                "context": dict(context or {}),
                "execution_mode": execution_mode,
            }
        )
        return {"status": "ok"}

    monkeypatch.setattr(api_main._QUEST_RUNTIME, "chat", fake_chat)

    result = api_main.quest_chat(
        api_main.QuestChatRequest(
            message="hello",
            lane="generated",
            child="Task Helper",
            new_instance=True,
        )
    )

    assert result["status"] == "ok"
    assert captured["agent_id"] == api_main.JL_FAT_AGENT_ID
    assert captured["lane"] == "generated"
    assert captured["child"] == "Task Helper"
    assert captured["new_instance"] is True
    assert captured["execution_mode"] == "execute"
    assert captured["context"]["tooling_mode"] == "forge_first"
    assert captured["context"]["external_tool_fallback"] is True
    assert captured["context"]["delegated_execution_mode"] == "execute"


def test_quest_chat_execute_mode_streams_events_from_session(monkeypatch):
    runtime = FatQuestRuntime()
    events: list[dict] = []

    class FakeSession:
        def __init__(self) -> None:
            self.engine = SimpleNamespace(
                current_agent_name="SparkByte",
                set_agent=lambda _agent: None,
            )

        def run(
            self,
            message: str,
            context: dict | None = None,
            event_sink=None,
        ) -> dict:
            if event_sink is not None:
                event_sink(
                    {
                        "type": "tool_call_started",
                        "tool": "run_shell",
                        "input": {"command": "echo hello"},
                    }
                )
            return {
                "status": "ok",
                "final": "Quest streamed reply.",
                "reply": "Quest streamed reply.",
                "tool_trace": [{"tool": "run_shell"}],
                "telemetry": {},
            }

    parent = QuestAgent(
        agent_id="main",
        agent="SparkByte",
        session=FakeSession(),
        forge=PrivilegedMemoryForge(),
    )

    monkeypatch.setattr(runtime, "ensure_agent", lambda agent_id, agent_name="SparkByte": parent)
    monkeypatch.setattr(runtime, "_choose_delegation", lambda **kwargs: None)

    result = runtime._chat_impl(
        agent_id="main",
        message="hello",
        execution_mode="execute",
        allow_clone=False,
        event_sink=events.append,
    )

    assert result["status"] == "ok"
    assert any(event.get("type") == "quest_chat_started" for event in events)
    assert any(event.get("type") == "tool_call_started" for event in events)
    assert any(event.get("type") == "turn_result" for event in events)


def test_quest_switch_api_passes_lane_child_and_instance_flag(monkeypatch):
    captured: dict[str, object] = {}

    def fake_switch_agent(*, agent_id: str, lane: str, child: str | None = None, new_instance: bool = False):
        captured.update(
            {
                "agent_id": agent_id,
                "lane": lane,
                "child": child,
                "new_instance": new_instance,
            }
        )
        return {"status": "ok"}

    monkeypatch.setattr(api_main._QUEST_RUNTIME, "switch_agent", fake_switch_agent)

    result = api_main.quest_switch(
        api_main.QuestSwitchRequest(
            agent_id="switcher",
            lane="generated",
            child="Support Wing",
            new_instance=True,
        )
    )

    assert result["status"] == "ok"
    assert captured == {
        "agent_id": "switcher",
        "lane": "generated",
        "child": "Support Wing",
        "new_instance": True,
    }


def test_bridge_browser_inspect_uses_local_manager_without_endpoint(monkeypatch):
    class FakeBridge:
        def inspect(self, data):
            return {"status": "ok", "title": "Example Domain", "url": data.get("url")}

    monkeypatch.delenv("JL_BROWSER_BRIDGE_URL", raising=False)
    monkeypatch.setattr(bridge_module, "_LOCAL_BROWSER_BRIDGE", None)
    monkeypatch.setattr(bridge_module, "_get_local_browser_bridge", lambda: FakeBridge())
    monkeypatch.setattr(bridge_module, "run_audit_tool", lambda payload: {"status": "ok"})

    result = bridge_module.run_bridge(
        {"mode": "browser_inspect", "data": {"url": "https://example.com"}}
    )

    assert result["status"] == "ok"
    assert result["result"]["title"] == "Example Domain"
    assert result["result"]["capability_tier"] == "session_attach_accessibility"


def test_bridge_browser_inspect_falls_back_to_local_manager_when_loopback_http_bridge_fails(monkeypatch):
    class FakeBridge:
        def inspect(self, data):
            return {"status": "ok", "title": "Example Domain", "url": data.get("url")}

    class FakeRequestException(requests.RequestException):
        pass

    def fake_post(*args, **kwargs):
        raise FakeRequestException("loopback bridge refused connection")

    monkeypatch.setenv("JL_BROWSER_BRIDGE_URL", "http://127.0.0.1:8000/browser-bridge")
    monkeypatch.setattr(bridge_module, "_LOCAL_BROWSER_BRIDGE", None)
    monkeypatch.setattr(bridge_module, "_get_local_browser_bridge", lambda: FakeBridge())
    monkeypatch.setattr(bridge_module.requests, "post", fake_post)
    monkeypatch.setattr(bridge_module, "run_audit_tool", lambda payload: {"status": "ok"})

    result = bridge_module.run_bridge(
        {"mode": "browser_inspect", "data": {"url": "https://example.com"}}
    )

    assert result["status"] == "ok"
    assert result["result"]["title"] == "Example Domain"
    assert "loopback bridge refused connection" in result["result"]["bridge_http_error"]


def test_bridge_alias_modes_normalize_into_real_browser_requests(monkeypatch):
    monkeypatch.setattr(bridge_module, "run_audit_tool", lambda payload: {"status": "ok"})
    monkeypatch.setattr(
        bridge_module,
        "_browser_inspect",
        lambda data: {"status": "ok", "kind": "inspect", "url": data.get("url", "")},
    )
    monkeypatch.setattr(
        bridge_module,
        "_browser_action",
        lambda data: {"status": "ok", "kind": "action", "action": data.get("action"), "url": data.get("url", "")},
    )

    inspect_result = bridge_module.run_bridge({"mode": "ui_info", "data": {"url": "https://example.com"}})
    action_result = bridge_module.run_bridge({"mode": "ui_access", "data": {"url": "https://example.com"}})

    assert inspect_result["status"] == "ok"
    assert inspect_result["effective_mode"] == "browser_inspect"
    assert inspect_result["result"]["kind"] == "inspect"
    assert action_result["status"] == "ok"
    assert action_result["effective_mode"] == "browser_action"
    assert action_result["result"]["action"] == "open"
