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
