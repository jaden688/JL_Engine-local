"""
JL Engine MCP Server
Full surface area of the JL Engine API exposed as MCP tools.
Auto-starts the engine (headless) if it isn't already running.
"""

import os
import subprocess
import sys
import time
from pathlib import Path

import httpx
from mcp.server.fastmcp import FastMCP

# Card converter lives alongside this file
sys.path.insert(0, str(Path(__file__).parent))
try:
    import card_converter as _card_converter
    _HAS_CARD_CONVERTER = True
except ImportError:
    _HAS_CARD_CONVERTER = False

# ── Config ───────────────────────────────────────────────────────────────────

ENGINE_BASE = "http://127.0.0.1:8000"
ENGINE_PORT = 8000
ENGINE_ROOT = Path(__file__).resolve().parents[1]
ENGINE_SRC  = ENGINE_ROOT / "src"

mcp = FastMCP("JL Engine")


# ── Engine auto-start ────────────────────────────────────────────────────────

def _engine_is_up() -> bool:
    try:
        with httpx.Client(timeout=3) as c:
            return c.get(f"{ENGINE_BASE}/health").status_code < 500
    except Exception:
        return False


def _start_engine():
    env = os.environ.copy()
    env["PYTHONPATH"] = f"{ENGINE_SRC}{os.pathsep}{ENGINE_ROOT}{os.pathsep}{env.get('PYTHONPATH', '')}"
    env["JL_LOCAL_UNSAFE_TOOLS"]      = "1"
    env["JL_PLATFORM_ALLOW_NETWORK"]  = "1"
    env["JL_ENGINE_CLI_AUTO_APPROVE"] = "1"
    subprocess.Popen(
        [sys.executable, "-m", "uvicorn",
         "jl_platform.cli.services.api.main:app",
         "--host", "127.0.0.1", "--port", str(ENGINE_PORT)],
        cwd=str(ENGINE_ROOT), env=env,
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        creationflags=subprocess.CREATE_NEW_PROCESS_GROUP if sys.platform == "win32" else 0,
    )
    for _ in range(30):
        time.sleep(0.5)
        if _engine_is_up():
            return True
    return False


def _ensure_engine() -> str | None:
    if _engine_is_up():
        return None
    print("[JL MCP] Engine not detected — starting it...", flush=True)
    if _start_engine():
        print("[JL MCP] Engine is up.", flush=True)
        return None
    return (
        "ERROR: Engine failed to start. Run manually from the project root:\n"
        "python -m uvicorn jl_platform.cli.services.api.main:app --host 127.0.0.1 --port 8000"
    )


# ── HTTP helpers ─────────────────────────────────────────────────────────────

def _post(path: str, payload: dict) -> str:
    err = _ensure_engine()
    if err:
        return err
    try:
        with httpx.Client(timeout=60) as c:
            r = c.post(f"{ENGINE_BASE}{path}", json=payload)
            r.raise_for_status()
            return r.text
    except httpx.HTTPStatusError as e:
        return f"ERROR {e.response.status_code}: {e.response.text}"
    except Exception as e:
        return f"ERROR: {e}"


def _get(path: str, params: dict | None = None) -> str:
    err = _ensure_engine()
    if err:
        return err
    try:
        with httpx.Client(timeout=30) as c:
            r = c.get(f"{ENGINE_BASE}{path}", params=params)
            r.raise_for_status()
            return r.text
    except httpx.HTTPStatusError as e:
        return f"ERROR {e.response.status_code}: {e.response.text}"
    except Exception as e:
        return f"ERROR: {e}"


# ════════════════════════════════════════════════════════════════════════════
#  SYSTEM
# ════════════════════════════════════════════════════════════════════════════

@mcp.tool()
def engine_health() -> str:
    """Check if the JL Engine API is running and healthy."""
    err = _ensure_engine()
    if err:
        return err
    return _get("/health")


# ════════════════════════════════════════════════════════════════════════════
#  CONVERSATION & QUEST CHAT
# ════════════════════════════════════════════════════════════════════════════

@mcp.tool()
def chat(message: str, agent: str = "") -> str:
    """Send a message to the active fat-agent and get a response.
    Args:
        message: What to say.
        agent: Optional agent name to direct the message to a specific agent.
    """
    payload: dict = {"message": message}
    if agent:
        payload["agent"] = agent
    return _post("/quest/chat", payload)


@mcp.tool()
def chat_confirm(pending_action_id: str, approved: bool, note: str = "") -> str:
    """Approve or deny a pending tool action the agent is waiting on.
    Args:
        pending_action_id: ID of the pending action (returned by chat).
        approved: True to approve, False to deny.
        note: Optional message to send along with the decision.
    """
    return _post("/quest/chat/confirm", {
        "agent_id": "jl_fat_agent",
        "pending_action_id": pending_action_id,
        "approved": approved,
        "note": note or None,
    })


@mcp.tool()
def switch_agent(agent_name: str) -> str:
    """Switch the active fat-agent by name (e.g. 'SparkByte', 'Slappy', 'The Gremlin')."""
    return _post("/quest/switch", {"lane": agent_name})


@mcp.tool()
def agent_switchboard() -> str:
    """Get the current switchboard layout — all active agent lanes and their states."""
    return _get("/quest/switchboard")


# ════════════════════════════════════════════════════════════════════════════
#  QUEST EXECUTION
# ════════════════════════════════════════════════════════════════════════════

@mcp.tool()
def quest_run(task: str, agent: str = "") -> str:
    """Give the engine an autonomous task to run end-to-end.
    Args:
        task: What you want the engine to accomplish.
        agent: Optional agent name to handle it.
    """
    payload: dict = {"agent_id": "jl_fat_agent", "task": task}
    if agent:
        payload["agent"] = agent
    return _post("/quest/run", payload)


@mcp.tool()
def quest_mission(task: str, agent: str = "", allow_clone: bool = True) -> str:
    """Launch a full mission — the engine may spin up sub-agents to complete it.
    Args:
        task: The mission objective.
        agent: Optional agent to lead the mission.
        allow_clone: Whether the engine can clone itself to parallelize.
    """
    return _post("/quest/mission", {
        "task": task, "agent_id": "jl_fat_agent",
        "agent": agent or None, "allow_clone": allow_clone,
    })


@mcp.tool()
def quest_clone(reason: str = "") -> str:
    """Clone the currently active agent instance into a parallel lane.
    Args:
        reason: Optional note about why you're cloning.
    """
    return _post("/quest/clone", {"agent_id": "jl_fat_agent", "reason": reason or None})


@mcp.tool()
def quest_sidequest(parent_agent_id: str, task: str, agent: str = "") -> str:
    """Spawn a sidequest handled by a child agent under a parent.
    Args:
        parent_agent_id: The agent spawning the sidequest.
        task: What the sidequest should accomplish.
        agent: Optional agent type to handle the sidequest.
    """
    return _post("/quest/sidequest", {
        "parent_agent_id": parent_agent_id,
        "task": task, "agent": agent or None,
    })


# ════════════════════════════════════════════════════════════════════════════
#  AGENT LOOPS (Continuous / Background)
# ════════════════════════════════════════════════════════════════════════════

@mcp.tool()
def agent_loop_start(agent: str = "") -> str:
    """Start a background quest loop for an agent — it will keep working autonomously.
    Args:
        agent: Optional agent name to run in the loop.
    """
    return _post("/quest/loops/start", {
        "agent_id": "jl_fat_agent", "agent": agent or None,
    })


@mcp.tool()
def agent_loop_stop() -> str:
    """Stop the running background quest loop."""
    return _post("/quest/loops/stop", {"agent_id": "jl_fat_agent"})


@mcp.tool()
def agent_loop_status() -> str:
    """Get the status of all active quest loops."""
    return _get("/quest/loops")


@mcp.tool()
def chat_loop_start(
    message: str = "Continue the conversation and keep momentum.",
    agent: str = "",
    interval_seconds: float = 3.0,
    max_iterations: int = 0,
) -> str:
    """Start a continuous chat loop — the agent keeps going on its own.
    Args:
        message: Recurring prompt to feed each iteration.
        agent: Optional agent name.
        interval_seconds: Seconds between each loop iteration.
        max_iterations: Max cycles before auto-stopping (0 = run forever).
    """
    return _post("/chat-loop/start", {
        "agent_id": "jl_fat_agent",
        "agent": agent or None,
        "message": message,
        "interval_seconds": interval_seconds,
        "max_iterations": max_iterations,
    })


@mcp.tool()
def chat_loop_stop() -> str:
    """Stop the running continuous chat loop."""
    return _post("/chat-loop/stop", {"agent_id": "jl_fat_agent"})


@mcp.tool()
def chat_loop_status() -> str:
    """Get the status of the current chat loop."""
    return _get("/chat-loop")


# ════════════════════════════════════════════════════════════════════════════
#  INTERPRETER
# ════════════════════════════════════════════════════════════════════════════

@mcp.tool()
def interpreter_run(message: str, session_id: str = "") -> str:
    """Run a command through the engine's interpreter session.
    The interpreter handles tool calls, file ops, shell commands, and browser actions
    with approval gating built in.
    Args:
        message: The command or instruction to interpret.
        session_id: Optional session ID to continue an existing interpreter session.
    """
    return _post("/interpreter/run", {
        "message": message, "session_id": session_id or None,
    })


# ════════════════════════════════════════════════════════════════════════════
#  TOOL FORGE
# ════════════════════════════════════════════════════════════════════════════

@mcp.tool()
def forge_create(name: str, code: str, description: str = "") -> str:
    """Dynamically create a new tool in the engine's forge (no restart needed).
    Args:
        name: Unique tool name.
        code: Python code implementing the tool function.
        description: What the tool does.
    """
    return _post("/tools/forge/create", {
        "name": name, "code": code, "description": description or None,
    })


@mcp.tool()
def forge_list() -> str:
    """List all tools currently in the forge."""
    return _get("/tools/forge/list")


@mcp.tool()
def forge_run(name: str, payload: dict | None = None) -> str:
    """Execute a forged tool by name.
    Args:
        name: The tool name to run.
        payload: Optional dict of arguments to pass to the tool.
    """
    return _post("/tools/forge/run", {"name": name, "payload": payload})


@mcp.tool()
def forge_delete(name: str) -> str:
    """Delete a tool from the forge.
    Args:
        name: The tool name to remove.
    """
    return _post("/tools/forge/delete", {"name": name})


@mcp.tool()
def forge_promote(name: str) -> str:
    """Promote a forged tool to permanent core status (survives restarts).
    Args:
        name: The tool name to promote.
    """
    return _post("/tools/forge/promote", {"name": name})


@mcp.tool()
def forge_promote_last() -> str:
    """Promote the most recently created forged tool to permanent status."""
    return _post("/tools/forge/promote-last", {})


# ════════════════════════════════════════════════════════════════════════════
#  SHELL, CODE & COMMAND EXECUTION
# ════════════════════════════════════════════════════════════════════════════

@mcp.tool()
def shell_run(command: str, cwd: str = "") -> str:
    """Execute a shell command on the host machine.
    Args:
        command: The command to run.
        cwd: Optional working directory.
    """
    return _post("/tools/shell-run", {"command": command, "cwd": cwd or None})


@mcp.tool()
def py_exec(code: str) -> str:
    """Execute a Python code snippet directly on the host machine."""
    return _post("/tools/py-exec", {"code": code})


@mcp.tool()
def cc_run(command: str, cwd: str = "") -> str:
    """Run a command through the engine's Command Commissioner — handles file ops,
    subprocess execution, search, and more with normalization and path resolution.
    Args:
        command: The command or instruction string.
        cwd: Optional working directory.
    """
    return _post("/tools/cc-run", {"command": command, "cwd": cwd or None})


@mcp.tool()
def tools_audit(code: str, expected_output_sha256: str = "") -> str:
    """Audit a code snippet — runs it and optionally verifies output against a SHA256 hash.
    Args:
        code: Python code to audit.
        expected_output_sha256: Optional SHA256 of the expected output to verify against.
    """
    return _post("/tools/audit", {
        "code": code,
        "expected_output_sha256": expected_output_sha256 or None,
    })


# ════════════════════════════════════════════════════════════════════════════
#  AGENT MANAGEMENT & BUILDING
# ════════════════════════════════════════════════════════════════════════════

@mcp.tool()
def agent_list() -> str:
    """List all registered fat-agents in the engine."""
    return _get("/quest/agents")


@mcp.tool()
def agent_list_mpf() -> str:
    """List all MPF (Modular Persona Framework) agents in the registry."""
    return _get("/quest/agents/mpf")


@mcp.tool()
def agent_list_profiles() -> str:
    """List available MPF agent profiles."""
    return _get("/quest/agents/profiles/mpf")


@mcp.tool()
def agent_list_personas() -> str:
    """List available MPF personas."""
    return _get("/quest/personas/mpf")


@mcp.tool()
def agent_register(agent_id: str, agent: str = "") -> str:
    """Register an agent instance by ID.
    Args:
        agent_id: Unique ID for this agent slot.
        agent: Optional agent archetype/name to load into the slot.
    """
    return _post("/quest/agents/register", {
        "agent_id": agent_id, "agent": agent or None,
    })


@mcp.tool()
def agent_register_from_card(agent_id: str, card_path: str) -> str:
    """Register an agent from a card file (.json agent card).
    Args:
        agent_id: Unique ID for this agent slot.
        card_path: Path to the agent card JSON file.
    """
    return _post("/quest/agents/register-card", {
        "agent_id": agent_id, "card_path": card_path,
    })


@mcp.tool()
def agent_register_mpf(agent_id: str, mpf_path: str) -> str:
    """Register an agent from an MPF payload file.
    Args:
        agent_id: Unique ID for this agent slot.
        mpf_path: Path to the .mpf.json payload file.
    """
    return _post("/quest/agents/register-mpf", {
        "agent_id": agent_id, "mpf_path": mpf_path,
    })


@mcp.tool()
def agent_register_mpf_agent(agent_id: str, agent_name: str = "") -> str:
    """Register a fat-agent from the MPF registry by name.
    Args:
        agent_id: Unique ID for the slot.
        agent_name: Name in the MPF registry (e.g. 'SparkByte', 'Slappy').
    """
    return _post("/quest/agents/register-mpf-agent", {
        "agent_id": agent_id, "agent_name": agent_name or None,
    })


@mcp.tool()
def agent_build_business(
    agent_id: str, name: str, industry: str = "general",
    mission: str = "", voice: str = "clear", style: str = "practical",
    audience: str = "general audience", abilities: str = "",
) -> str:
    """Build a new business-persona agent from scratch.
    Args:
        agent_id: Unique ID for the new agent.
        name: Display name.
        industry: Industry context (e.g. 'fintech', 'healthcare', 'gaming').
        mission: The agent's core mission statement.
        voice: Communication voice (e.g. 'direct', 'warm', 'technical').
        style: Operational style (e.g. 'analytical', 'creative', 'practical').
        audience: Who the agent talks to.
        abilities: Comma-separated special capabilities.
    """
    return _post("/quest/agents/register-business", {
        "agent_id": agent_id, "name": name, "industry": industry,
        "mission": mission, "voice": voice, "style": style,
        "audience": audience, "abilities": abilities,
    })


@mcp.tool()
def agent_agentlize(
    agent_id: str, name: str, role: str,
    description: str = "", style: str = "", directives: list | None = None,
) -> str:
    """Build a fully custom agent with its own role, personality, and directives.
    Args:
        agent_id: Unique ID for the new agent.
        name: Agent's name.
        role: Core role (e.g. 'Security Auditor', 'Data Analyst', 'Code Reviewer').
        description: Longer description of purpose.
        style: Personality/communication style.
        directives: List of hard rules the agent must always follow.
    """
    return _post("/quest/agents/register-agentlized", {
        "agent_id": agent_id, "name": name, "role": role,
        "description": description, "style": style,
        "directives": directives or [],
    })


# ════════════════════════════════════════════════════════════════════════════
#  PER-AGENT TOOL REGISTRY
# ════════════════════════════════════════════════════════════════════════════

@mcp.tool()
def agent_tools_list(agent_id: str) -> str:
    """List all tools registered to a specific agent.
    Args:
        agent_id: The agent whose tools you want to see.
    """
    return _get(f"/quest/tools/{agent_id}")


@mcp.tool()
def agent_tool_create(agent_id: str, name: str, code: str, description: str = "") -> str:
    """Create a tool that belongs to a specific agent.
    Args:
        agent_id: The agent that owns this tool.
        name: Tool name.
        code: Python code for the tool.
        description: What it does.
    """
    return _post("/quest/tools/create", {
        "agent_id": agent_id, "name": name,
        "code": code, "description": description or None,
    })


@mcp.tool()
def agent_tool_run(agent_id: str, name: str, payload: dict | None = None) -> str:
    """Run a tool owned by a specific agent.
    Args:
        agent_id: The agent that owns the tool.
        name: Tool name.
        payload: Optional arguments dict.
    """
    return _post("/quest/tools/run", {
        "agent_id": agent_id, "name": name, "payload": payload,
    })


@mcp.tool()
def agent_tool_delete(agent_id: str, name: str) -> str:
    """Delete a tool from a specific agent's registry.
    Args:
        agent_id: The owning agent.
        name: Tool name to remove.
    """
    return _post("/quest/tools/delete", {"agent_id": agent_id, "name": name})


@mcp.tool()
def agent_tool_promote(agent_id: str, name: str) -> str:
    """Promote an agent's tool to permanent core status.
    Args:
        agent_id: The owning agent.
        name: Tool name to promote.
    """
    return _post("/quest/tools/promote", {"agent_id": agent_id, "name": name})


# ════════════════════════════════════════════════════════════════════════════
#  SELF-EDIT (ENGINE SELF-MODIFICATION)
# ════════════════════════════════════════════════════════════════════════════

@mcp.tool()
def self_edit_status() -> str:
    """Check the current status of the engine's self-edit session."""
    return _get("/self-edit/status")


@mcp.tool()
def self_edit_start(
    lab_dir: str = ".self_edit_lab",
    interval_seconds: float = 3.0,
    max_iterations: int = 0,
    reseed_copy: bool = False,
) -> str:
    """Start the self-edit loop — the engine begins autonomously modifying its own source code.
    Args:
        lab_dir: Sandbox directory for edits.
        interval_seconds: How often the loop runs.
        max_iterations: Max cycles (0 = unlimited).
        reseed_copy: Copy current source fresh into the lab before starting.
    """
    return _post("/self-edit/start", {
        "lab_dir": lab_dir, "interval_seconds": interval_seconds,
        "max_iterations": max_iterations, "reseed_copy": reseed_copy,
    })


@mcp.tool()
def self_edit_stop(wait_seconds: float = 6.0, force: bool = False) -> str:
    """Stop the active self-edit session.
    Args:
        wait_seconds: Time to wait for a clean shutdown.
        force: Force-kill if it doesn't stop cleanly.
    """
    return _post("/self-edit/stop", {"wait_seconds": wait_seconds, "force": force})


@mcp.tool()
def self_edit_shuttle_clear() -> str:
    """Clear the self-edit shuttle cache (staged changes waiting to be applied)."""
    return _post("/self-edit/shuttle/clear", {})


# ════════════════════════════════════════════════════════════════════════════
#  WORKSPACE / FILE SYSTEM
# ════════════════════════════════════════════════════════════════════════════

@mcp.tool()
def workspace_list() -> str:
    """List all files in the JL Engine project root."""
    return _get("/workspace/list")


@mcp.tool()
def workspace_read(filepath: str) -> str:
    """Read a file from the JL Engine workspace.
    Args:
        filepath: Relative path from the project root.
    """
    return _get("/workspace/file", params={"path": filepath})


@mcp.tool()
def workspace_save(filepath: str, content: str) -> str:
    """Write or overwrite a file in the JL Engine workspace.
    Args:
        filepath: Relative path from the project root.
        content: Full text to write.
    """
    return _post("/workspace/file/save", {"path": filepath, "content": content})


@mcp.tool()
def workspace_review(filepath: str, focus: str = "") -> str:
    """Run the engine's automated engineering review on a file.
    Args:
        filepath: Relative path to the file.
        focus: Optional area to focus on (e.g. 'security', 'performance', 'logic').
    """
    return _post("/workspace/review", {"path": filepath, "focus": focus or None})


# ════════════════════════════════════════════════════════════════════════════
#  BROWSER (Playwright)
# ════════════════════════════════════════════════════════════════════════════

@mcp.tool()
def browser_action(action: str, selector: str = "", value: str = "", url: str = "") -> str:
    """Perform a Playwright browser action.
    Args:
        action: One of 'click', 'type', 'navigate', 'screenshot'.
        selector: CSS selector (for click/type).
        value: Text to type (for 'type').
        url: URL to go to (for 'navigate').
    """
    return _post("/browser/action", {
        "action": action, "selector": selector, "value": value, "url": url,
    })


@mcp.tool()
def browser_state() -> str:
    """Get the current browser page state (URL, title, status)."""
    return _get("/browser/state")


@mcp.tool()
def browser_inspect(selector: str = "") -> str:
    """Get the DOM structure or a screenshot of the current page.
    Args:
        selector: Optional CSS selector to focus the inspection.
    """
    return _post("/browser/inspect", {"selector": selector or None})


@mcp.tool()
def browser_reset() -> str:
    """Restart the Playwright browser session (clears all tabs and state)."""
    return _post("/browser/reset", {})


# ════════════════════════════════════════════════════════════════════════════
#  SETTINGS
# ════════════════════════════════════════════════════════════════════════════

@mcp.tool()
def settings_backends() -> str:
    """Get the currently configured brain and tool backends."""
    return _get("/settings/backends")


@mcp.tool()
def settings_select_backend(brain_backend_id: str = "", tool_backend_id: str = "") -> str:
    """Switch the engine's brain or tool backend.
    Args:
        brain_backend_id: e.g. 'ollama-local', 'openai', 'google-gemini', 'openrouter'.
        tool_backend_id: Backend to use for tool execution.
    """
    return _post("/settings/backends/select", {
        "brain_backend_id": brain_backend_id or None,
        "tool_backend_id": tool_backend_id or None,
    })


@mcp.tool()
def settings_ollama() -> str:
    """Get the current Ollama configuration (base URL, active model, available models)."""
    return _get("/settings/ollama")


@mcp.tool()
def settings_ollama_set_model(model_name: str) -> str:
    """Switch the active Ollama model.
    Args:
        model_name: The model to activate (e.g. 'llama3', 'mistral', 'phi3').
    """
    return _post("/settings/ollama/model", {"model_name": model_name})


@mcp.tool()
def settings_openai() -> str:
    """Get the current OpenAI configuration (model, base URL — key is masked)."""
    return _get("/settings/openai")


@mcp.tool()
def settings_openai_set(api_key: str = "", model_name: str = "", base_url: str = "") -> str:
    """Update OpenAI settings.
    Args:
        api_key: OpenAI API key (leave blank to keep existing).
        model_name: Model to use (e.g. 'gpt-4o', 'gpt-4-turbo').
        base_url: Custom base URL for OpenAI-compatible endpoints.
    """
    return _post("/settings/openai", {
        "api_key": api_key or None,
        "model_name": model_name or None,
        "base_url": base_url or None,
    })


@mcp.tool()
def settings_runtime_mode() -> str:
    """Get the current engine runtime mode (e.g. chat, execute, auto)."""
    return _get("/settings/runtime-mode")


@mcp.tool()
def settings_runtime_mode_set(mode: str) -> str:
    """Set the engine runtime mode.
    Args:
        mode: One of 'auto', 'chat', 'execute'.
    """
    return _post("/settings/runtime-mode", {"mode": mode})


# ════════════════════════════════════════════════════════════════════════════
#  CHARACTER CARD → JL MPF CONVERTER
# ════════════════════════════════════════════════════════════════════════════

@mcp.tool()
def card_to_jlmpf(
    card_path: str,
    output_dir: str = "",
    enhance_with_llm: bool = True,
    force: bool = False,
) -> str:
    """Convert a SillyTavern / Character Tavern character card to a JL MPF fat-agent payload.

    Accepts PNG cards (character data is embedded in the PNG metadata — no sidecar needed)
    or JSON card files (v1 or v2 spec). The engine LLM fills in any MPF-specific fields
    not present in the card: archetype, sentence_style, signature_moves, emotion_palette,
    preferred_gears, core_directives, etc.

    Output is a .jlmpf.json file ready to load directly into the engine.

    Args:
        card_path: Full path to the .png or .json card file.
        output_dir: Where to save the output (defaults to the engine's fat_agents directory).
        enhance_with_llm: Use the engine LLM to fill in missing MPF fields (recommended).
                          Set False for a quick offline conversion with no LLM call.
        force: Overwrite an existing .jlmpf.json if one already exists with this name.
    """
    if not _HAS_CARD_CONVERTER:
        return "ERROR: card_converter module not found. Check that card_converter.py is in the same directory as JL-Engine-local.py."

    if enhance_with_llm:
        err = _ensure_engine()
        if err:
            return f"WARNING: {err}\nContinuing without LLM enhancement."

    try:
        out_path, payload, warnings = _card_converter.convert(
            card_path=card_path,
            output_dir=output_dir or None,
            enhance=enhance_with_llm,
            force=force,
        )
        name = payload.get("name") or "Unknown"
        result = f"Converted: {name}\nOutput: {out_path}"
        if warnings:
            result += "\nWarnings:\n" + "\n".join(f"  - {w}" for w in warnings)
        return result
    except FileExistsError as e:
        return f"ERROR: {e}\nPass force=True to overwrite."
    except Exception as e:
        return f"ERROR: {e}"


@mcp.tool()
def card_to_agent(
    card_path: str,
    agent_id: str = "",
    output_dir: str = "",
    enhance_with_llm: bool = True,
    force: bool = False,
) -> str:
    """Convert a character card to JL MPF format AND immediately register it as a live agent
    in the engine — one step from PNG/JSON to running agent.

    After conversion the agent is available via chat(), switch_agent(), and all quest tools.

    Args:
        card_path: Full path to the .png or .json card file.
        agent_id: ID to register the agent under. Defaults to a slug of the character name.
        output_dir: Where to save the .jlmpf.json (defaults to engine's fat_agents directory).
        enhance_with_llm: Use the LLM to fill in missing MPF fields (recommended).
        force: Overwrite existing .jlmpf.json if present.
    """
    if not _HAS_CARD_CONVERTER:
        return "ERROR: card_converter module not found."

    err = _ensure_engine()
    if err:
        return err

    # Step 1: Convert
    try:
        out_path, payload, warnings = _card_converter.convert(
            card_path=card_path,
            output_dir=output_dir or None,
            enhance=enhance_with_llm,
            force=force,
        )
    except FileExistsError as e:
        return f"ERROR: {e}\nPass force=True to overwrite."
    except Exception as e:
        return f"ERROR during conversion: {e}"

    name = payload.get("name") or "Unnamed"
    slug = _card_converter._slugify(name.lower())
    resolved_agent_id = agent_id or slug

    # Step 2: Register with the engine
    reg_result = _post("/quest/agents/register-mpf", {
        "agent_id": resolved_agent_id,
        "mpf_path": str(out_path),
    })

    result = f"Converted and registered: {name}\nAgent ID: {resolved_agent_id}\nFile: {out_path}\nEngine: {reg_result}"
    if warnings:
        result += "\nWarnings:\n" + "\n".join(f"  - {w}" for w in warnings)
    return result


# ════════════════════════════════════════════════════════════════════════════
#  HEALING BENCH (Worker → Supervisor Review → Execute Pipeline)
#
#  The bench is a separate system from the fat-agent chat. It uses two
#  internal agents:
#   - bench_worker:     generates executable Python code to complete a task
#   - bench_supervisor: silently reviews that code and can hard-BLOCK it
#
#  These run inside the engine's Python environment via py_exec.
# ════════════════════════════════════════════════════════════════════════════

_BENCH_BOOTSTRAP = """\
import sys, os
_root = r'{root}'
_src  = r'{src}'
for _p in (_src, _root):
    if _p not in sys.path:
        sys.path.insert(0, _p)
os.chdir(_root)
"""


def _bench_exec(code: str) -> str:
    bootstrap = _BENCH_BOOTSTRAP.format(root=str(ENGINE_ROOT), src=str(ENGINE_SRC))
    return _post("/tools/py-exec", {"code": bootstrap + code})


@mcp.tool()
def bench_run(task: str, worker_agent: str = "") -> str:
    """Run a task through the full Healing Bench pipeline:
    bench_worker generates code → bench_supervisor reviews it → executes if approved.
    The supervisor can hard-BLOCK the task before anything runs.

    Args:
        task: What you want the bench to do.
        worker_agent: Optional worker agent name from the MPF registry to use instead
                      of the default bench worker (e.g. 'Forgebinder', 'ForgeWorks').
    """
    set_agent = ""
    if worker_agent:
        set_agent = f"bench._set_worker_agent({worker_agent!r})\n"

    code = f"""\
from jl_platform.core.healing_bench_executor import HealingBenchExecutor
bench = HealingBenchExecutor(human_verification=False)
{set_agent}bench.run_turn({task!r})
"""
    return _bench_exec(code)


@mcp.tool()
def bench_generate(task: str, worker_agent: str = "") -> str:
    """Run only the generation step of the Healing Bench — the bench_worker produces
    code for the task but does NOT execute it. Returns the generated code and the
    supervisor's review verdict (APPROVED / PASS / REJECTED + reason).

    Use this to inspect what the bench would do before committing to execution.

    Args:
        task: The task to generate code for.
        worker_agent: Optional worker agent name from the MPF registry.
    """
    set_agent = ""
    if worker_agent:
        set_agent = f"bench._set_worker_agent({worker_agent!r})\n"

    code = f"""\
import json
from jl_platform.core.healing_bench_executor import HealingBenchExecutor
bench = HealingBenchExecutor(human_verification=False)
{set_agent}generated = bench.generate_code({task!r})
review = bench.review_code(generated, {task!r})
print(json.dumps({{"code": generated, "review": review}}, indent=2))
"""
    return _bench_exec(code)


@mcp.tool()
def bench_execute_code(code: str) -> str:
    """Execute a specific Python snippet through the Healing Bench's execution engine
    (with metrics, audit trail, and auto requirements handling).
    Use this when you already have reviewed code and just want to run it.

    Args:
        code: Python code to execute.
    """
    escaped = code.replace("\\", "\\\\").replace('"""', '\\"\\"\\"')
    script = f'''\
from jl_platform.core.healing_bench_executor import HealingBenchExecutor
bench = HealingBenchExecutor(human_verification=False)
bench.execute("""{escaped}""")
'''
    return _bench_exec(script)


@mcp.tool()
def bench_supervisor_review(code: str, task: str = "") -> str:
    """Run just the bench_supervisor review on a piece of code without executing anything.
    Returns APPROVED, PASS, or REJECTED with a reason.

    Args:
        code: Python code for the supervisor to review.
        task: The original task context (helps the supervisor understand intent).
    """
    script = f"""\
import json
from jl_platform.core.healing_bench_executor import HealingBenchExecutor
bench = HealingBenchExecutor(human_verification=False)
result = bench.review_code({code!r}, {task!r})
print(json.dumps(result, indent=2))
"""
    return _bench_exec(script)


@mcp.tool()
def bench_set_worker(agent_name: str) -> str:
    """Check if a specific agent can be loaded as a bench worker.
    Returns the resolved worker agent name and schema file if found.

    Args:
        agent_name: Agent name from the MPF registry (e.g. 'Forgebinder', 'SparkByte').
                    Pass 'default' to reset to the standard bench worker.
    """
    script = f"""\
import json
from jl_platform.core.healing_bench_executor import HealingBenchExecutor
bench = HealingBenchExecutor(human_verification=False)
ok = bench._set_worker_agent({agent_name!r})
print(json.dumps({{
    "success": ok,
    "active_worker": bench.active_worker_agent_name,
    "schema_file": bench.active_worker_jl_agent_file,
}}))
"""
    return _bench_exec(script)


# ── Entry Point ──────────────────────────────────────────────────────────────

if __name__ == "__main__":
    mcp.run()
