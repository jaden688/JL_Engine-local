# JL Engine — SparkByte Omni

> A Julia-native AI agent engine with a real-time behavioral control layer. Not a chatbot wrapper — a middleware system that models conversation state as a dynamic behavioral machine before any LLM ever sees your message.

**Live UI:** `http://127.0.0.1:8081` &nbsp;|&nbsp; **Entry:** `julia sparkbyte.jl` &nbsp;|&nbsp; **Repo:** `github.com/jaden688/JL_Engine-local`

---

## Architecture Overview

```mermaid
graph TB
    subgraph USER["User Layer"]
        UI["Browser UI\nWebSocket :8081"]
        CLI["AI CLI\nClaude / Cursor / Gemini / Codex / Windsurf"]
    end

    subgraph BYTE["BYTE — Agentic Shell"]
        WS["WebSocket Server"]
        LOOP["Agentic Loop\nLLM → Tools → Loop"]
        FORGE["forge_new_tool\nLive Julia Eval"]
        TOOLS["Tool Dispatch\n14 built-in + dynamic"]
    end

    subgraph ENGINE["JLEngine Core"]
        SIG["SignalScorer"]
        BSM["BehaviorStateMachine\n5×4 Grid"]
        DRIFT["DriftPressureSystem\n0.0–1.0"]
        RHYTHM["RhythmEngine\nflip/flop/trot"]
        APE["EmotionalAperture\nOPEN/FOCUSED/TIGHT"]
        MEM["HybridMemorySystem"]
        AGENT["AgentManager"]
        STATE["StateManager\nStability + Advisory"]
    end

    subgraph STORAGE["Persistence"]
        DB[("sparkbyte_memory.db\nSQLite")]
        DYN["dynamic_tools.jl\nForged Tools"]
    end

    subgraph MCP["MCP Bridge"]
        MCPSRV["mcp_server/server.py\nstdio — data + action tools"]
    end

    UI --> WS
    CLI --> MCPSRV
    WS --> LOOP
    LOOP --> ENGINE
    ENGINE --> LOOP
    LOOP --> TOOLS
    FORGE --> DYN
    TOOLS --> FORGE
    ENGINE --> DB
    TOOLS --> DB
    MCPSRV --> DB
```

---

## Engine Turn Pipeline

Every message goes through this pipeline before the LLM responds:

```mermaid
flowchart LR
    MSG["User Message"] --> SIG

    subgraph PIPELINE["JLEngine — Per Turn"]
        SIG["SignalScorer\nsentiment · arousal · pace\nconfusion · intent · memory density"]
        BSM["BehaviorStateMachine\n5 intensity × 4 control\n= 20 named states"]
        DRIFT["DriftPressure\n0.0 → 1.0\nhow far from agent alignment"]
        RHYTHM["RhythmEngine\nflip · flop · trot\nresponse cadence"]
        APE["EmotionalAperture\nOPEN · FOCUSED · TIGHT\nsets LLM temp + top_p"]
        STATE["StateManager\nstability · advisory payload\ngating_bias · emotional_drift"]
    end

    SIG --> BSM --> DRIFT --> RHYTHM --> APE --> STATE

    STATE --> PROMPT["Shaped Prompt\n+ memory + agent + advisory"]
    PROMPT --> LLM["LLM Backend\nGemini · Ollama · OpenAI · XAI"]
    LLM --> RESPONSE["Response"]
```

---

## Behavioral State Grid

SparkByte's behavior is modeled as a 5×4 grid — intensity vs control:

```mermaid
quadrantChart
    title Behavior State Grid (intensity vs control)
    x-axis Disciplined --> Chaotic
    y-axis Dormant --> Surge
    quadrant-1 Expressive Chaos
    quadrant-2 Focused Surge
    quadrant-3 Calm Control
    quadrant-4 Loose Low Energy
    Surge-Disciplined: [0.15, 0.95]
    Surge-Balanced: [0.45, 0.92]
    Surge-Expressive: [0.72, 0.88]
    Surge-Chaotic: [0.92, 0.85]
    High-Disciplined: [0.15, 0.72]
    High-Balanced: [0.45, 0.70]
    High-Expressive: [0.72, 0.68]
    High-Chaotic: [0.92, 0.65]
    Mid-Disciplined: [0.15, 0.50]
    Mid-Balanced: [0.45, 0.48]
    Mid-Expressive: [0.72, 0.46]
    Mid-Chaotic: [0.92, 0.44]
    Low-Disciplined: [0.15, 0.28]
    Low-Balanced: [0.45, 0.26]
    Low-Expressive: [0.72, 0.24]
    Low-Chaotic: [0.92, 0.22]
    Dormant: [0.45, 0.05]
```

---

## Tool System

```mermaid
graph LR
    subgraph BUILTIN["Built-in Tools (14)"]
        RF["read_file"]
        WF["write_file"]
        LF["list_files"]
        RC["run_command"]
        OS["get_os_info"]
        BT["bluetooth_devices"]
        SMS["send_sms"]
        EC["execute_code\nJulia · Python"]
        FNT["forge_new_tool ⭐"]
        GP["github_pillage"]
        BU["browse_url\nPlaywright"]
        REM["remember"]
        REC["recall"]
        META["metamorph\nself-repair"]
    end

    subgraph DYNAMIC["Dynamic Tools (forged at runtime)"]
        D1["tool_read_mystic_format"]
        D2["tool_python_web_scout"]
        D3["tool_live_dashboard"]
        D4["tool_self_audit"]
        D5["tool_greet_user"]
        DN["... + any tool SparkByte forges"]
    end

    FNT -->|"eval into live module\npersists to dynamic_tools.jl"| DYNAMIC
```

---

## forge_new_tool — Self-Extension Flow

```mermaid
sequenceDiagram
    participant User
    participant LLM
    participant BYTE
    participant Julia as Julia Runtime
    participant DB as sparkbyte_memory.db

    User->>LLM: "Build me a tool that does X"
    LLM->>BYTE: forge_new_tool(name, code, description)
    BYTE->>Julia: per-expression eval loop (skips using/import)
    Julia-->>BYTE: function registered in module
    BYTE->>Julia: live test via Base.invokelatest
    alt test passes
        BYTE->>DB: persist to tools table
        BYTE->>Julia: write to dynamic_tools.jl
        BYTE-->>LLM: success + test result
    else test fails
        BYTE-->>LLM: forge_broken: true — re-forge with fix
    end
    LLM-->>User: tool live, confirmed working
```

---

## MCP Server — AI CLI Bridge

```mermaid
graph LR
    subgraph CLIENTS["AI CLI Clients"]
        CC["Claude Code"]
        CUR["Cursor"]
        WS["Windsurf"]
        GEM["Gemini CLI"]
        COD["Codex"]
    end

    subgraph MCP["mcp_server/server.py\nstdio transport · data + action tools"]
        T1["get_engine_state"]
        T2["get_thoughts"]
        T3["list_forged_tools"]
        T4["query_memory"]
        T5["get_telemetry"]
        T6["search_julian_quarry"]
        T7["get_knowledge"]
        T8["run_turn"]
        T9["ruida_send_job\nexplicit opt-in to start"]
        R1["sparkbyte://skill"]
        R2["sparkbyte://agents"]
    end

    DB[("sparkbyte_memory.db")]
    JDB[("quarry.db\nJulian")]

    CC -->|stdio spawn| MCP
    CUR -->|stdio spawn| MCP
    WS -->|stdio spawn| MCP
    GEM -->|stdio spawn| MCP
    COD -->|stdio spawn| MCP

    MCP -->|database queries| DB
    MCP -->|read-only| JDB
```

The MCP bridge includes live turn execution and Ruida laser-controller tools in addition
to database reads. `ruida_send_job` uploads without starting by default; set `auto_start`
to `true` only when immediate physical operation is intended.

---

## Agents

| Agent | Vibe | Drive |
|---------|------|-------|
| **SparkByte** | Sassy, playful, fast-talking junior engineer | Creative + Technical |
| **Slappy** | Chaotic hillbilly gremlin energy | Chaos |
| **The Gremlin** | Pure chaos builder | Destruction → Creation |
| **Temporal** | Analytical, temporal/quantum reasoning | Logic |
| **Supervisor** | Safe, grounding, helper mode | Stability |

Switch in chat: `/gear SparkByte` &nbsp;|&nbsp; Switch in code: `set_agent!(engine, "SparkByte")`

---

## LLM Backends

| ID | Provider | Default Model |
|----|---------|--------------|
| `openrouter` | Google Gemini | gemini-1.5-pro |
| `openrouter` | Ollama (local) | qwen3:4b |
| `xai` | xAI Grok | grok-2 |
| `openai` | OpenAI | gpt-4o |
| `cerebras` | Cerebras | llama3.1-70b |
| `noop-stub` | No-op for testing | — |

---

## Quick Start

```powershell
# Local (full host access — recommended for dev)
cd "C:\Users\J_lin\Desktop\JL_Engine (3)\jl-vs\vscode-main\copilot-separate-leopard"
julia --project=. start.jl
# Open http://127.0.0.1:8081

# Docker (containerized deploy)
docker compose up -d
# Open http://localhost:8081
```

**Environment variables:**
```powershell
$env:SPARKBYTE_ROOT   = "path/to/project"
$env:SPARKBYTE_PORT   = "8081"
$env:SPARKBYTE_HOST   = "127.0.0.1"   # or 0.0.0.0 for Docker
$env:OPENROUTER_API_KEY   = "..."
$env:OPENAI_API_KEY   = "..."
$env:XAI_API_KEY      = "..."
```

---

## Project Structure

```
JL_Engine-local/
├── start.jl                  # Canonical Julia entrypoint
├── compose.yaml              # Docker compose
├── Dockerfile                # Multi-stage build
├── requirements.docker.txt   # Python deps (Playwright, Pillow, requests)
├── dynamic_tools.jl          # Runtime-forged tools (auto-generated)
│
├── BYTE/src/
│   ├── BYTE.jl               # WebSocket server, agentic loop, forge hooks
│   ├── Tools.jl              # All tool implementations
│   ├── Schema.jl             # Gemini function declaration schemas
│   ├── Telemetry.jl          # Health check, linting, telemetry
│   └── ui.html               # Browser chat UI (single file)
│
├── src/
│   ├── App.jl                # Boot sequence, DB init, browser context
│   ├── JLEngine.jl           # Module loader
│   └── JLEngine/
│       ├── Core.jl           # Turn orchestration
│       ├── Signals.jl        # Signal scoring
│       ├── Behavior.jl       # State machine
│       ├── Drift.jl          # Drift pressure
│       ├── Rhythm.jl         # Rhythm engine
│       ├── Aperture.jl       # Emotional aperture
│       ├── Memory.jl         # Hybrid memory
│       ├── AgentManager.jl # Agent loading
│       ├── Backends.jl       # LLM provider routing
│       └── State.jl          # Advisory + stability
│
├── mcp_server/
│   └── server.py             # MCP stdio server (data, runtime, and hardware tools)
│
├── data/
│   ├── agents/             # Fat JSON agent profiles
│   ├── behavior_states.json  # 5×4 behavior grid definitions
│   └── JLframe_Engine_Framework.json
│
└── _mcp_inspect/             # MPF Open Standard adapters + agent packs
```

---

## Related Projects

**JulianMetaMorph** — GitHub intelligence engine. Hunts real repos, indexes code into a full-text-search quarry, forges reusable Python skill modules with provenance manifests.

```
Julian hunt-task → quarry DB → forge-skill → SparkByte forge_new_tool → live capability
```

> Monorepo merge in progress — Julian will live at `julian/` inside this repo.
