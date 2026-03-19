from __future__ import annotations

import re
from collections import Counter
from pathlib import Path

from fastapi.testclient import TestClient

from jl_platform.services.api import main as api_main


def test_web_ui_shell_serves_switchboard_html() -> None:
    client = TestClient(api_main.app)

    response = client.get("/ui/")

    assert response.status_code == 200
    assert "text/html" in response.headers.get("content-type", "")
    html = response.text
    for element_id in (
        "laneSelect",
        "childSelect",
        "switchAgentBtn",
        "newGeneratedInstanceCheck",
        "advancedSwitchboardDrawer",
        "advancedOpsDrawer",
        "chatLog",
        "opsFeed",
        "backendModeChip",
        "heroVoiceSummary",
        "activeVoiceHeading",
        "activeVoiceNote",
        "productSummary",
    ):
        assert f'id="{element_id}"' in html

    ids = re.findall(r'\bid="([^"]+)"', html)
    duplicates = [element_id for element_id, count in Counter(ids).items() if count > 1]
    assert not duplicates
    assert "JL Engine Local" in html
    assert "Open engine controls" in html
    assert 'id="activeVoiceHeading"' in html
    assert "The selected fat-agent voice rides the controls right now." in html
    assert 'class="panel chat-only chat-primary reveal"' in html


def test_web_ui_shell_script_targets_switchboard_routes() -> None:
    script_path = Path(__file__).resolve().parents[1] / "ui_web" / "app.js"
    script = script_path.read_text(encoding="utf-8")

    assert "/quest/switchboard" in script
    assert "/quest/switch" in script
    assert "/quest/agents/profiles/mpf" in script
    assert "/quest/personas/mpf" not in script
    assert "/browser/action" in script
    assert "/browser/inspect" in script
    assert "/tools/cc-run" in script
    assert "/tools/shell-run" not in script
    assert "laneSelect" in script
    assert "childSelect" in script
    assert "BROWSER_ACTION" in script
    assert "BROWSER_INSPECT" in script
    assert "fs_mkdir" in script
    assert "run_cc_command" in script
    assert "pendingChatActionDecisionPending" in script
    assert "Resolve the pending action card first" in script
    assert 'execution_mode: state.totalAgentControlEnabled ? "auto" : "chat"' in script
    assert "PRIMARY_PRODUCT_SELECTION" in script
    assert "forcePrimary: true" in script
    assert "currentChatAgentLabel" in script
    assert "voiceSkinCopy" in script
    assert "is thinking..." in script
    assert "thinking-card" in script


def test_legacy_personas_api_alias_matches_agents_profiles() -> None:
    client = TestClient(api_main.app)

    profiles_response = client.get("/quest/agents/profiles/mpf")
    personas_response = client.get("/quest/personas/mpf")

    assert profiles_response.status_code == 200
    assert personas_response.status_code == 200
    assert personas_response.json()["personas"] == profiles_response.json()["agent_profiles"]
