from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from jl_platform.services.api import main as api_main


def test_web_ui_easy_serves_flow_shell() -> None:
    client = TestClient(api_main.app)

    response = client.get("/ui-easy/")

    assert response.status_code == 200
    assert "text/html" in response.headers.get("content-type", "")
    html = response.text
    for element_id in (
        "voiceSelect",
        "autoToolsToggle",
        "healthChip",
        "modeChip",
        "modelChip",
        "browserChip",
        "selectionChip",
        "chatLog",
        "approvalPanel",
        "activityFeed",
        "compositionPanel",
    ):
        assert f'id="{element_id}"' in html
    assert "JL Engine" in html
    assert "Flow Deck" in html
    assert "Open legacy deck" in html


def test_web_ui_easy_script_targets_runtime_routes() -> None:
    script_path = Path(__file__).resolve().parents[1] / "ui_easy" / "app.js"
    script = script_path.read_text(encoding="utf-8")

    assert "/health" in script
    assert "/settings/ollama" in script
    assert "/browser/state" in script
    assert "/quest/chat" in script
    assert "/quest/chat/confirm" in script
    assert "/quest/agents/mpf" in script
    assert "/quest/agents" in script
    assert "SparkByte Modular" in script
    assert "autoToolsToggle" in script
    assert "thinkingMessageEl" in script
    assert "appendThinkingMessage" in script
    assert "quick-action" in (Path(__file__).resolve().parents[1] / "ui_easy" / "index.html").read_text(encoding="utf-8")
