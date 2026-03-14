from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel

JL_FAT_AGENT_ID = "jl_fat_agent"


class ChatRequest(BaseModel):
    message: str
    agent: Optional[str] = None
    events: Optional[List[Dict[str, Any]]] = None
    context: Optional[Dict[str, Any]] = None


class ToolRequest(BaseModel):
    code: str


class AuditRequest(BaseModel):
    code: str
    output: Optional[str] = None
    expected_output_sha256: Optional[str] = None


class ForgeCreateRequest(BaseModel):
    name: str
    code: str
    description: Optional[str] = None


class ForgeRunRequest(BaseModel):
    name: str
    payload: Optional[Dict[str, Any]] = None


class ForgeDeleteRequest(BaseModel):
    name: str


class ForgePromoteRequest(BaseModel):
    name: str


class BridgeRequest(BaseModel):
    mode: str
    data: Optional[Dict[str, Any]] = None


class InterpreterRequest(BaseModel):
    message: str
    session_id: Optional[str] = None


class CCRunRequest(BaseModel):
    command: str | List[str]
    cwd: Optional[str] = None
    timeout: Optional[float] = None
    shell: Optional[bool] = True


class QuestAgentRegisterRequest(BaseModel):
    agent_id: str = JL_FAT_AGENT_ID
    agent: Optional[str] = None


class QuestChatRequest(BaseModel):
    agent_id: str = JL_FAT_AGENT_ID
    message: str
    agent: Optional[str] = None
    lane: Optional[str] = None
    child: Optional[str] = None
    new_instance: Optional[bool] = False
    context: Optional[Dict[str, Any]] = None
    execution_mode: Optional[str] = "auto"
    return_trace: Optional[bool] = True


class QuestChatConfirmRequest(BaseModel):
    agent_id: str = JL_FAT_AGENT_ID
    pending_action_id: str
    approved: bool
    note: Optional[str] = None
    return_trace: Optional[bool] = True


class QuestRunRequest(BaseModel):
    agent_id: str = JL_FAT_AGENT_ID
    task: str
    agent: Optional[str] = None


class QuestMissionRequest(BaseModel):
    task: str
    agent_id: Optional[str] = JL_FAT_AGENT_ID
    agent: Optional[str] = None
    dynamic_agent: Optional[bool] = None
    allow_clone: Optional[bool] = True


class WorkspaceReviewRequest(BaseModel):
    path: str
    focus: Optional[str] = None
    max_chars: Optional[int] = 20000


class WorkspaceSaveRequest(BaseModel):
    path: str
    content: str


class QuestCloneRequest(BaseModel):
    agent_id: str = JL_FAT_AGENT_ID
    reason: Optional[str] = None


class QuestSideQuestRequest(BaseModel):
    parent_agent_id: str
    task: str
    agent: Optional[str] = None


class QuestToolCreateRequest(BaseModel):
    agent_id: str
    name: str
    code: str
    description: Optional[str] = None


class QuestToolRunRequest(BaseModel):
    agent_id: str
    name: str
    payload: Optional[Dict[str, Any]] = None


class QuestToolDeleteRequest(BaseModel):
    agent_id: str
    name: str


class QuestBusinessAgentRequest(BaseModel):
    agent_id: str
    name: str
    industry: str = "general"
    voice: str = "clear"
    audience: str = "general audience"
    values: str = ""
    style: str = "practical"
    abilities: str = ""
    mission: str = ""
    products: str = ""
    docs: str = ""


class QuestCardAgentRequest(BaseModel):
    agent_id: str
    card_path: str


class QuestMPFAgentRequest(BaseModel):
    agent_id: str
    mpf_path: str


class QuestMPFAgentAgentRequest(BaseModel):
    agent_id: str
    agent_name: Optional[str] = None


class QuestAgentlizedAgentRequest(BaseModel):
    agent_id: str
    name: str
    role: str
    description: str = ""
    style: str = ""
    directives: Optional[List[str]] = None


class QuestLoopStartRequest(BaseModel):
    agent_id: str = JL_FAT_AGENT_ID
    agent: Optional[str] = None


class QuestLoopStopRequest(BaseModel):
    agent_id: str = JL_FAT_AGENT_ID


class ChatLoopStartRequest(BaseModel):
    agent_id: str = JL_FAT_AGENT_ID
    agent: Optional[str] = None
    message: str = "Continue the conversation and keep momentum."
    context: Optional[Dict[str, Any]] = None
    execution_mode: Optional[str] = "chat"
    interval_seconds: Optional[float] = 3.0
    max_iterations: Optional[int] = 0
    return_trace: Optional[bool] = False
    autostart_agent_loop: Optional[bool] = True


class ChatLoopStopRequest(BaseModel):
    agent_id: str = JL_FAT_AGENT_ID
    wait_seconds: Optional[float] = 6.0


class OllamaModelSelectionRequest(BaseModel):
    model_name: str


class OpenAISettingsRequest(BaseModel):
    api_key: Optional[str] = None
    model_name: Optional[str] = None
    base_url: Optional[str] = None


class BackendSelectionRequest(BaseModel):
    brain_backend_id: Optional[str] = None
    tool_backend_id: Optional[str] = None


class RuntimeModeRequest(BaseModel):
    mode: str


class QuestSwitchRequest(BaseModel):
    agent_id: str = JL_FAT_AGENT_ID
    lane: str
    child: Optional[str] = None
    new_instance: Optional[bool] = False


class SelfEditStartRequest(BaseModel):
    lab_dir: Optional[str] = ".self_edit_lab"
    interval_seconds: Optional[float] = 3.0
    max_iterations: Optional[int] = 0
    reseed_copy: Optional[bool] = False


class SelfEditStopRequest(BaseModel):
    lab_dir: Optional[str] = None
    wait_seconds: Optional[float] = 6.0
    force: Optional[bool] = False
    log_lines: Optional[int] = 120


class SelfEditLabRequest(BaseModel):
    lab_dir: Optional[str] = None
