from __future__ import annotations

from jl_platform.services.api.schemas import (
    ChatLoopStartRequest,
    JL_FAT_AGENT_ID,
    QuestAgentRegisterRequest,
    QuestChatRequest,
    QuestMissionRequest,
    QuestMPFAgentAgentRequest,
    QuestSwitchRequest,
)


def test_register_request_preserves_runtime_defaulting_behavior() -> None:
    payload = QuestAgentRegisterRequest()

    assert payload.agent_id == JL_FAT_AGENT_ID
    assert payload.agent is None


def test_chat_request_defaults_match_current_route_contract() -> None:
    payload = QuestChatRequest(message="hi")

    assert payload.agent_id == JL_FAT_AGENT_ID
    assert payload.agent is None
    assert payload.execution_mode == "auto"
    assert payload.return_trace is True
    assert payload.new_instance is False


def test_mission_request_keeps_optional_dynamic_agent_toggle() -> None:
    payload = QuestMissionRequest(task="ship docs")

    assert payload.agent_id == JL_FAT_AGENT_ID
    assert payload.agent is None
    assert payload.dynamic_agent is None
    assert payload.allow_clone is True


def test_chat_loop_request_defaults_remain_chat_first() -> None:
    payload = ChatLoopStartRequest()

    assert payload.agent_id == JL_FAT_AGENT_ID
    assert payload.agent is None
    assert payload.execution_mode == "chat"
    assert payload.autostart_agent_loop is True


def test_switch_request_defaults_are_non_destructive() -> None:
    payload = QuestSwitchRequest(lane="generated")

    assert payload.agent_id == JL_FAT_AGENT_ID
    assert payload.child is None
    assert payload.new_instance is False


def test_mpf_agent_register_request_keeps_optional_name_for_compatibility() -> None:
    payload = QuestMPFAgentAgentRequest(agent_id="agent-1")

    assert payload.agent_id == "agent-1"
    assert payload.agent_name is None
