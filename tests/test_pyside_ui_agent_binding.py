from __future__ import annotations

from types import SimpleNamespace
from ui.pyside_ui import Main


class FakeEngine:
    def __init__(self) -> None:
        self.current_agent_name = "SparkByte"
        self.behavior_profile = None

    def set_agent(self, agent_name: str) -> None:
        self.current_agent_name = agent_name

    def set_behavior_profile(self, profile: str) -> None:
        self.behavior_profile = profile


class FakeLineEdit:
    def __init__(self, value: str = "") -> None:
        self.value = value
        self.cleared = False

    def text(self) -> str:
        return self.value

    def clear(self) -> None:
        self.value = ""
        self.cleared = True


class FakeCombo:
    def __init__(self, current: str = "") -> None:
        self._current = current
        self.items: list[str] = []
        self.blocked = False

    def currentText(self) -> str:
        return self._current

    def blockSignals(self, value: bool) -> None:
        self.blocked = value

    def clear(self) -> None:
        self.items = []

    def addItems(self, items: list[str]) -> None:
        self.items.extend(items)

    def setCurrentText(self, value: str) -> None:
        self._current = value


def test_bind_ui_fat_agent_uses_agent_name_keyword():
    calls: dict[str, tuple[str, str, str | None] | tuple[str, str]] = {}

    def fake_register_agent(agent_id: str, agent_name: str = "SparkByte", parent_agent_id: str | None = None):
        calls["register"] = (agent_id, agent_name, parent_agent_id)
        return {"status": "ok"}

    def fake_ensure_agent(agent_id: str, agent_name: str = "SparkByte"):
        calls["ensure"] = (agent_id, agent_name)
        return SimpleNamespace(session=SimpleNamespace(engine=None), agent=agent_name)

    main = Main.__new__(Main)
    main.quest_agent_id = "jl_fat_agent"
    main.engine = FakeEngine()
    main.quest_runtime = SimpleNamespace(
        register_agent=fake_register_agent,
        ensure_agent=fake_ensure_agent,
    )

    Main._bind_ui_fat_agent(main)

    assert calls["register"] == ("jl_fat_agent", "SparkByte", None)
    assert calls["ensure"] == ("jl_fat_agent", "SparkByte")


def test_on_agent_change_uses_agent_name_keyword():
    calls: list[tuple[str, tuple[object, ...]]] = []

    def fake_register_agent(agent_id: str, agent_name: str = "SparkByte", parent_agent_id: str | None = None):
        calls.append(("register", (agent_id, agent_name, parent_agent_id)))
        return {"status": "ok"}

    def fake_ensure_agent(agent_id: str, agent_name: str = "SparkByte"):
        calls.append(("ensure", (agent_id, agent_name)))
        return SimpleNamespace(session=SimpleNamespace(engine=None, history=[]), agent=agent_name)

    main = Main.__new__(Main)
    main.quest_agent_id = "jl_fat_agent"
    main.engine = FakeEngine()
    main.quest_runtime = SimpleNamespace(
        register_agent=fake_register_agent,
        ensure_agent=fake_ensure_agent,
    )
    main._apply_agent_profile_defaults = lambda value: calls.append(("defaults", (value,)))
    main._bind_ui_fat_agent = lambda: calls.append(("bind", (main.engine.current_agent_name,)))
    main._refresh_agent_params_display = lambda: calls.append(("params", ()))
    main._refresh_agent_schema_inspector = lambda: calls.append(("schema", ()))
    main._append_chat = lambda *args: calls.append(("chat", args))
    main._sync_badges = lambda: calls.append(("sync", ()))
    main._interpreter_session = SimpleNamespace(engine=None)

    Main._on_agent_change(main, "The Gremlin")

    assert ("register", ("jl_fat_agent", "The Gremlin", None)) in calls
    assert ("ensure", ("jl_fat_agent", "The Gremlin")) in calls
    assert main.engine.current_agent_name == "The Gremlin"
    assert main.engine.behavior_profile == "expressive"


def test_file_tree_click_toggles_directories_and_opens_files():
    calls: list[object] = []

    class FakeModel:
        def isDir(self, index: object) -> bool:
            return index == "folder"

        def filePath(self, index: object) -> str:
            return f"/tmp/{index}"

    class FakeTree:
        def __init__(self) -> None:
            self.expanded: dict[object, bool] = {"folder": False}

        def isExpanded(self, index: object) -> bool:
            return self.expanded.get(index, False)

        def setExpanded(self, index: object, value: bool) -> None:
            self.expanded[index] = value

    main = Main.__new__(Main)
    main.file_model = FakeModel()
    main.file_tree = FakeTree()
    main._on_file_selected = lambda index: calls.append(index)

    Main._on_file_tree_clicked(main, "folder")
    Main._on_file_tree_clicked(main, "file")

    assert main.file_tree.expanded["folder"] is True
    assert calls == ["file"]


def test_chat_attachment_context_reads_file(tmp_path):
    sample = tmp_path / "notes.txt"
    sample.write_text("hello from file", encoding="utf-8")

    main = Main.__new__(Main)
    main._chat_attachment_path = sample
    main.chat_attachment_input = SimpleNamespace(text=lambda: "external/notes.txt")

    context = Main._chat_attachment_context(main)

    assert "hello from file" in context
    assert "Attached File:" in context
    assert "notes.txt" in context
    assert str(sample) not in context


def test_chat_attachment_label_hides_absolute_external_path(tmp_path):
    sample = tmp_path / "notes.txt"

    main = Main.__new__(Main)

    label = Main._chat_attachment_label(main, sample)

    assert label == "external/notes.txt"
    assert str(sample) != label


def test_apply_ollama_model_selection_updates_chat_controls(monkeypatch):
    import ui.pyside_ui as pyside_ui

    calls: list[object] = []

    def fake_set_ollama_model(model: str, persist: bool = True):
        calls.append(("model", model, persist))
        return {"model_name": model}

    monkeypatch.setattr(pyside_ui.backends, "set_ollama_model", fake_set_ollama_model)
    monkeypatch.setattr(pyside_ui, "save_service_config", lambda config: calls.append(("save", dict(config))))

    main = Main.__new__(Main)
    main.service_config = {}
    main.preferred_ollama_model = "gemma3:4b"
    main.ollama_model_combo = FakeCombo("old")
    main.chat_model_combo = FakeCombo("old")
    main.bench_model_input = SimpleNamespace(setText=lambda value: calls.append(("bench", value)))
    main._chat_model_options = lambda: ["gemma3:4b", "llama3.1:8b"]
    main._sync_badges = lambda: calls.append(("sync",))

    Main._apply_ollama_model_selection(main, "gemma3:4b")

    assert ("model", "gemma3:4b", True) in calls
    assert main.service_config["ollama_model"] == "gemma3:4b"
    assert main.ollama_model_combo.currentText() == "gemma3:4b"
    assert main.chat_model_combo.currentText() == "gemma3:4b"
    assert ("bench", "gemma3:4b") in calls


def test_on_send_includes_attached_file_context(monkeypatch, tmp_path):
    import ui.pyside_ui as pyside_ui

    attachment = tmp_path / "draft.txt"
    attachment.write_text("alpha beta gamma", encoding="utf-8")

    captured: dict[str, object] = {}

    class FakeThread:
        def __init__(self, target=None, args=(), daemon=None):
            captured["target"] = target
            captured["args"] = args
            captured["daemon"] = daemon

        def start(self) -> None:
            captured["started"] = True

    monkeypatch.setattr(pyside_ui.threading, "Thread", FakeThread)

    main = Main.__new__(Main)
    main._response_inflight = False
    main.chat_input = FakeLineEdit("Do the thing")
    main._chat_attachment_path = attachment
    main.chat_attachment_input = FakeLineEdit("external/draft.txt")
    main.chat_history = []
    main.engine = SimpleNamespace(current_agent_name="SparkByte")
    main.console_tabs = SimpleNamespace(currentIndex=lambda: 0, tabText=lambda _index: "CHAT")
    main._append_chat = lambda *args: captured.setdefault("chat", []).append(args)
    main._get_active_code_context = lambda: "\n\n[Active Context]\nprint('x')"
    main._set_request_busy = lambda busy: captured.setdefault("busy", []).append(busy)

    Main._on_send(main)

    prompt, agent_name = captured["args"]
    assert agent_name == "SparkByte"
    assert "Do the thing" in prompt
    assert "Active Context" in prompt
    assert "alpha beta gamma" in prompt
    assert str(attachment) not in prompt
    assert "external/draft.txt" in prompt
    assert main.chat_input.cleared is True


def test_chat_runtime_context_enables_all_workers_mode():
    main = Main.__new__(Main)
    main.chat_all_workers_toggle = SimpleNamespace(isChecked=lambda: True)

    context = Main._chat_runtime_context(main)

    assert context["channel"] == "ui_main_chat"
    assert context["delegated_execution_mode"] == "execute"
    assert context["tooling_mode"] == "forge_first"
    assert context["external_tool_fallback"] is True
    assert context["auto_approve_actions"] is True
    assert context["auto_approve_max"] == 3
    assert context["delegation_mode"] == "all"
    assert context["delegate_max_workers"] == 6


def test_chat_runtime_context_defaults_to_single_front_agent():
    main = Main.__new__(Main)
    main.chat_all_workers_toggle = SimpleNamespace(isChecked=lambda: False)

    context = Main._chat_runtime_context(main)

    assert context == {
        "channel": "ui_main_chat",
        "delegated_execution_mode": "execute",
        "tooling_mode": "forge_first",
        "external_tool_fallback": True,
        "auto_approve_actions": True,
        "auto_approve_note": "Auto-approved by UI chat.",
        "auto_approve_max": 3,
    }


def test_run_generate_response_renders_confirmation_required_as_reply():
    emitted: dict[str, object] = {}
    errors: list[str] = []

    def fake_chat(**kwargs):
        return {
            "status": "confirmation_required",
            "reply": "Awaiting confirmation: run shell task.",
            "pending_action": {"id": "abc123"},
        }

    main = Main.__new__(Main)
    main.quest_agent_id = "jl_fat_agent"
    main.service_config = {}
    main.quest_runtime = SimpleNamespace(chat=fake_chat)
    main._chat_runtime_context = lambda: {"channel": "ui_main_chat"}
    main.response_ready_signal = SimpleNamespace(
        emit=lambda reply, telemetry, latency: emitted.update(
            {"reply": reply, "telemetry": telemetry, "latency": latency}
        )
    )
    main.response_error_signal = SimpleNamespace(emit=lambda msg: errors.append(str(msg)))

    Main._run_generate_response(main, "hello", "SparkByte")

    assert not errors
    assert emitted["reply"] == "Awaiting confirmation: run shell task."


def test_run_generate_response_includes_status_when_runtime_errors():
    emitted: list[tuple[str, object, float]] = []
    errors: list[str] = []

    def fake_chat(**kwargs):
        return {
            "status": "error",
            "error": "backend_disconnected",
            "reply": "Tool backend is offline.",
        }

    main = Main.__new__(Main)
    main.quest_agent_id = "jl_fat_agent"
    main.service_config = {}
    main.quest_runtime = SimpleNamespace(chat=fake_chat)
    main._chat_runtime_context = lambda: {"channel": "ui_main_chat"}
    main.response_ready_signal = SimpleNamespace(emit=lambda *args: emitted.append(args))
    main.response_error_signal = SimpleNamespace(emit=lambda msg: errors.append(str(msg)))

    Main._run_generate_response(main, "hello", "SparkByte")

    assert not emitted
    assert errors
    assert "backend_disconnected" in errors[0]


def test_voice_reply_text_strips_code_blocks():
    main = Main.__new__(Main)

    spoken = Main._voice_reply_text(
        main,
        "Here is the fix. ```python\nprint('secret code')\n``` Now restart the app.",
    )

    assert "secret code" not in spoken
    assert spoken == "Here is the fix. Now restart the app."


def test_speak_engine_reply_uses_live_bridge_when_enabled(monkeypatch):
    import ui.pyside_ui as pyside_ui

    calls: list[str] = []

    class _ImmediateThread:
        def __init__(self, target=None, args=(), daemon=None):
            self._target = target

        def start(self) -> None:
            if self._target:
                self._target()

    main = Main.__new__(Main)
    main.live_audio_enable_check = SimpleNamespace(isChecked=lambda: True)
    main.live_audio_bridge = SimpleNamespace(
        configure=lambda **kwargs: None,
        available=lambda: (True, "ok"),
        speak_text=lambda text: calls.append(text),
    )
    main.live_audio_status_signal = SimpleNamespace(emit=lambda _msg: None)
    main._sync_live_audio_bridge = lambda: None

    monkeypatch.setattr(pyside_ui.threading, "Thread", _ImmediateThread)

    Main._speak_engine_reply(main, "SparkByte says hello.")

    assert calls == ["SparkByte says hello."]
