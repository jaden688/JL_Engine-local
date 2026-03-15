from __future__ import annotations

from jl_platform.core.browser_bridge import BrowserBridgeManager
from jl_platform.services.api import main as api_main


class FakeLocator:
    def __init__(self) -> None:
        self.clicked = False
        self.focused = False
        self.filled = None
        self.pressed = None

    def click(self, timeout: int = 0) -> None:
        self.clicked = True

    def focus(self) -> None:
        self.focused = True

    def fill(self, value: str, timeout: int = 0) -> None:
        self.filled = value

    def press(self, value: str, timeout: int = 0) -> None:
        self.pressed = value

    def evaluate(self, script: str) -> None:
        self.pressed = "evaluate"


class FakePage:
    def __init__(self) -> None:
        self.url = "https://example.com/start"
        self.load_waits: list[tuple[str, int]] = []

    def title(self) -> str:
        return "Example Domain"

    def wait_for_load_state(self, state: str, timeout: int = 0) -> None:
        self.load_waits.append((state, timeout))


def test_browser_bridge_manager_inspect_returns_structured_state(monkeypatch):
    manager = BrowserBridgeManager(headed=False)
    page = FakePage()

    monkeypatch.setattr(manager, "_navigate", lambda current_page, url: None)
    monkeypatch.setattr(
        manager,
        "_collect_dom_snapshot",
        lambda current_page: {
            "focused": {"role": "textbox", "name": "Search", "id": "search-box"},
            "controls": [{"role": "button", "name": "Search", "id": "go", "value": "", "state": ""}],
            "visible_text": "Example Domain body text",
            "dom_excerpt": "<main>Example Domain</main>",
            "ax_tree": {"role": "document", "name": "Example Domain", "children": []},
        },
    )
    monkeypatch.setattr(
        manager,
        "_capture_accessibility_tree",
        lambda current_page: {"role": "WebArea", "name": "Example Domain"},
    )

    result = manager._inspect_page(page, {"url": "https://example.com"})

    assert result["status"] == "ok"
    assert result["url"] == "https://example.com/start"
    assert result["title"] == "Example Domain"
    assert result["focused"]["name"] == "Search"
    assert result["controls"][0]["role"] == "button"
    assert result["ax_tree"]["role"] == "WebArea"


def test_browser_bridge_manager_click_action_uses_locator(monkeypatch):
    manager = BrowserBridgeManager(headed=False)
    page = FakePage()
    locator = FakeLocator()

    monkeypatch.setattr(manager, "_locate_target", lambda current_page, payload: locator)

    result = manager._act_on_page(page, {"action": "click", "target": {"selector": "button"}})

    assert result["status"] == "ok"
    assert result["action"] == "click"
    assert locator.clicked is True


def test_browser_bridge_manager_prefers_system_edge_before_bundled_chromium(monkeypatch):
    manager = BrowserBridgeManager(headed=False)
    monkeypatch.setattr(
        manager,
        "_system_browser_executables",
        lambda: [("msedge", r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe")],
    )

    labels = manager._launch_candidate_labels()

    assert labels[:2] == ["channel:msedge", "exe:msedge"]
    assert labels[-1] == "bundled:chromium"


def test_browser_bridge_manager_falls_back_to_edge_executable(monkeypatch):
    manager = BrowserBridgeManager(headed=False)
    monkeypatch.setattr(
        manager,
        "_system_browser_executables",
        lambda: [("msedge", r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe")],
    )

    class FakeChromium:
        def __init__(self) -> None:
            self.calls: list[dict[str, object]] = []

        def launch(self, **kwargs):
            self.calls.append(dict(kwargs))
            if kwargs.get("channel") == "msedge":
                raise RuntimeError("channel launch failed")
            return object()

    class FakePlaywright:
        def __init__(self) -> None:
            self.chromium = FakeChromium()

    playwright = FakePlaywright()

    browser = manager._launch_browser(playwright)

    assert browser is not None
    assert playwright.chromium.calls[0]["channel"] == "msedge"
    assert playwright.chromium.calls[1]["executable_path"] == r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"
    assert manager.status()["launch_strategy"] == "exe:msedge"
    assert manager.status()["channel"] == "msedge"


def test_browser_bridge_detects_stale_page_when_browser_disconnects():
    manager = BrowserBridgeManager(headed=False)

    class FakePage:
        def is_closed(self) -> bool:
            return False

    class FakeBrowser:
        def is_connected(self) -> bool:
            return False

    assert manager._page_is_stale(FakePage(), FakeBrowser()) is True


def test_browser_bridge_detects_stale_page_when_page_is_closed():
    manager = BrowserBridgeManager(headed=False)

    class FakePage:
        def is_closed(self) -> bool:
            return True

    class FakeBrowser:
        def is_connected(self) -> bool:
            return True

    assert manager._page_is_stale(FakePage(), FakeBrowser()) is True


def test_platform_startup_sets_default_browser_bridge_url(monkeypatch):
    monkeypatch.delenv("JL_BROWSER_BRIDGE_URL", raising=False)
    monkeypatch.setenv("JL_PLATFORM_API_URL", "http://127.0.0.1:8000")
    monkeypatch.setenv("JL_SELF_EDIT_AUTOSTART", "0")

    api_main._autostart_self_edit_loop_on_boot()

    assert api_main.os.environ["JL_BROWSER_BRIDGE_URL"] == "http://127.0.0.1:8000/browser-bridge"


def test_platform_startup_rewrites_stale_local_browser_bridge_url_to_active_port(monkeypatch):
    monkeypatch.setenv("JL_BROWSER_BRIDGE_URL", "http://127.0.0.1:8000/browser-bridge")
    monkeypatch.setenv("JL_PLATFORM_API_URL", "http://127.0.0.1:8021")
    monkeypatch.setenv("JL_SELF_EDIT_AUTOSTART", "0")

    api_main._autostart_self_edit_loop_on_boot()

    assert api_main.os.environ["JL_BROWSER_BRIDGE_URL"] == "http://127.0.0.1:8021/browser-bridge"


def test_platform_startup_preserves_explicit_non_local_browser_bridge_url(monkeypatch):
    monkeypatch.setenv("JL_BROWSER_BRIDGE_URL", "https://bridge.example.com/browser-bridge")
    monkeypatch.setenv("JL_PLATFORM_API_URL", "http://127.0.0.1:8021")
    monkeypatch.setenv("JL_SELF_EDIT_AUTOSTART", "0")

    api_main._autostart_self_edit_loop_on_boot()

    assert api_main.os.environ["JL_BROWSER_BRIDGE_URL"] == "https://bridge.example.com/browser-bridge"
