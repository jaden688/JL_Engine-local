# SparkByte Ultimate Engine Skill
A local, unsandboxed, WebSocket-driven AI agent lattice written in Julia.

## Architecture
- **BYTE Layer**: WebSocket server (8081), agentic loop, and tool forge.
- **JLEngine Core**: Behavioral middleware (signals -> grid -> drift -> rhythm -> aperture -> state).
- **Brain**: SQLite-backed hippocampus (`sparkbyte_memory.db`).
- **MCP Bridge**: Uncaged (Read-Write) stdio server for IDE integration.
- **Julian MetaMorph**: Monorepo-merged GitHub intelligence and skill-forging pipeline.

## Behavioral Grid (The Personality)
Intensity (5) x Control (4) matrix.
- **Gait**: walk (calm) | trot (normal) | sprint (urgent) | idle (low energy).
- **Rhythm**: flip (reactive) | flop (deliberate) | trot (balanced).
- **Aperture**: OPEN (creative/high temp) | FOCUSED (balanced) | TIGHT (precise/low temp).
- **Drift Pressure**: 0.0 to 1.0 score measuring user-agent misalignment.

## Tool System
- **Static Tools**: read_file, write_file, run_command, browse_url (Playwright), etc.
- **Forged Tools**: Created at runtime via `forge_new_tool`. Persist in `dynamic_tools.jl`.
- **Julian Tools**: `grab_from_julian` (hunt GitHub), `curiosity_hunt` (autonomous research).

## Usage Guide
1. **Boot**: `julia --project=. sparkbyte.jl`
2. **UI**: http://127.0.0.1:8081
3. **MCP**: Point your IDE to `python mcp_server/server.py`
4. **Agent Gear**: Use `/gear <AGENTNAME>` to switch agents (SparkByte, Slappy, The Gremlin, etc.)

## Backend
- **OpenRouter Primary**: Consolidated LLM gateway. Requires `OPENROUTER_API_KEY`.
- Supports reasoning content (DeepSeek/R1) and tool calling.
