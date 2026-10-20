# Agent handoff — JL Engine / SparkByte Omni

Use this file when continuing work in another IDE, agent, or machine. The canonical product overview and diagrams live in **`README.md`**. Deployment and env reference: **`DOCKER.md`** and **`.env.example`**.

---

## What this repo is

- **JL Engine (`src/JLEngine/`)** — Behavioral middleware per turn: signals → behavior grid → drift → rhythm → emotional aperture → state; SQLite-backed memory; MPF agents.
- **BYTE (`BYTE/src/`)** — WebSocket UI + agentic loop (LLM ↔ tools), `forge_new_tool`, Playwright `browse_url`, etc.
- **Entry:** `julia sparkbyte.jl` → UI **`http://127.0.0.1:8081`**
- **A2A** — `a2a_server.jl`; HTTP on **`8082`** by default (`/.well-known/agent.json`, JSON-RPC `tasks/send`). Booted from `src/App.jl` via `start_a2a_server`.
- **JulianMetaMorph** — Vendored under `JulianMetaMorph/JulianMetaMorph/` (GitHub quarry, `hunt_task`, `curiosity-hunt` CLI). Optional bridge to SparkByte.
- **MCP** — `mcp_server/server.py` (stdio); read-only access to engine state + Julian quarry when DB paths exist.

---

## Paths (Windows dev layout)

Workspace often lives under:

`jl-vs\vscode-main\copilot-separate-leopard`

Adjust if the user clones elsewhere. **`SPARKBYTE_ROOT`** can override runtime discovery (must contain `data/agents/Agents.mpf.json`).

---

## Run locally (dev)

```powershell
cd <repo-root>
copy .env.example .env   # then fill keys
julia sparkbyte.jl
```

- **SparkByte:** `8081` · **A2A:** `8082` (set `A2A_HOST` / `A2A_PORT` if needed)
- **`SPARKBYTE_LAUNCH_BROWSER=0`** — skip opening browser

---

## Docker / Compose

```bash
docker compose up --build
```

- Maps **8081** and **8082**; state volume → `/app/runtime`
- **`Dockerfile`** exposes **8081** and **8082**
- Smoke (on host with stack up): `powershell -File scripts/smoke_endpoints.ps1`

---

## Environment highlights (see `.env.example`)

| Area | Variables |
|------|-----------|
| SparkByte | `SPARKBYTE_HOST`, `SPARKBYTE_PORT`, `SPARKBYTE_STATE_DIR`, `SPARKBYTE_ROOT` |
| A2A | `A2A_HOST`, `A2A_PORT`, `A2A_PUBLIC_URL`, **`A2A_API_KEY`** (set when exposed beyond localhost) |
| Julian | `JULIAN_ROOT`, `JULIAN_DB`, **`JULIAN_AUTONOMOUS_SECONDS`** (0 = off; e.g. 3600 = hourly curiosity loop) |
| LLM | `OPENROUTER_API_KEY`, `OPENAI_API_KEY`, `CEREBRAS_API_KEY`, `XAI_API_KEY`, `OLLAMA_BASE_URL` |
| GitHub (Julian hunts) | `GITHUB_TOKEN` |

On boot, **`App.jl`** calls **`_sync_julian_env!(root)`** so embedded `JulianMetaMorph/JulianMetaMorph` sets `JULIAN_ROOT` / `JULIAN_DB` when unset.

---

## Julian ↔ SparkByte bridge (implemented)

- **`metamorph` tool** — `grab_from_julian` runs `python -m julian_metamorph.cli hunt-task "<task>"` from resolved Julian root (uses **`withenv` + `cd`**, not fragile shell strings).
- **`curiosity_hunt`** — runs **`curiosity-hunt`** CLI: rotating/random interest seeds from **`JulianProfile.curiosity_seeds`** (`profile.py` + `curiosity.py`).
- **CLI:** `hunt-task` and `curiosity-hunt` are registered in `JulianMetaMorph/.../cli.py` (older docs may only list older commands).
- **FastAPI:** `POST /hunt/curiosity` in `service.py` for the Julian service.
- **Autonomous loop:** `App.jl` → **`_start_julian_autonomous_loop!(root)`** when `JULIAN_AUTONOMOUS_SECONDS` > 0; writes diary + WS broadcast type **`julian_curiosity`** (UI may need a handler if you want it visible in chat).

---

## A2A chat path (important)

- **`run_turn!`** is used for plain-text chat tasks (full engine + LLM). **`process_turn`** was not a real symbol; routing uses **`run_turn!`** in `a2a_server.jl`.

---

## MCP defaults

- **`mcp_server/server.py`** — `JULIAN_DB` defaults to **`<repo>/JulianMetaMorph/JulianMetaMorph/data/quarry.db`**; override with env. **`SKILL_MD`** defaults under user home `.claude/skills/julian/SKILL.md`.

---

## Product / user context (non-code)

- User is exploring **deployment** (Azure credits / trial window was discussed) and wants a **callable agent** story (**A2A**, **forge**, **Julian**). **Vercel** is not a fit for this long-running stack; **VM + Docker** or **Azure Container Apps** / similar are the right class of target.
- Positioning: **controllable agent + persistent forge + standard surfaces (A2A/MCP)** — not a thin chat wrapper.

---

## Suggested next steps for the next agent

1. Confirm **`python -m julian_metamorph.cli curiosity-hunt`** and **`hunt-task`** run from embedded Julian with `PYTHONPATH=src` and optional `GITHUB_TOKEN`.
2. Optional: handle WS **`julian_curiosity`** in `BYTE/src/ui.html` for visible autonomous hunts.
3. Azure: deploy **Linux VM + Docker Compose** or **Container Apps**; set **`A2A_PUBLIC_URL`** and **`A2A_API_KEY`** for public endpoints.
4. Run **`scripts/smoke_endpoints.ps1`** after any deploy to verify **8081** and **8082**.

---

## Docs index

| File | Purpose |
|------|---------|
| `README.md` | Architecture, tools, agents, MCP diagram |
| `DOCKER.md` | Docker, Compose, A2A/Julian ops |
| `.env.example` | Env template |
| `.github/copilot-instructions.md` (if present) | VS Code / Copilot workspace hints |

---

*Handoff generated for continuity when switching tools or hosts. Update this file if major wiring changes.*
