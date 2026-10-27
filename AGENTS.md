# JL Engine (SparkByte Omni) — Agent Guide

Julia-native agent engine. A behavioral control pipeline (`src/JLEngine/`) runs on every
turn *before* the LLM call, setting temperature/top_p and an advisory payload. `BYTE/` is
the WebSocket agentic shell (LLM ↔ tool loop, live tool forging). Runtime state lives in
SQLite. Not a chatbot wrapper.

## Commands

| Action | Command |
|---|---|
| Boot (dev) | `julia sparkbyte.jl` — self-activates `@__DIR__`; same as `julia --project=. sparkbyte.jl` |
| UI | http://127.0.0.1:8081 |
| A2A | http://127.0.0.1:8082 |
| Unit tests | `julia --project=. -e 'using Pkg; Pkg.test()'` (runs `test/runtests.jl`) |
| One suite | `julia --project=. test/test_backends.jl` (each `test_*.jl` is self-contained) |
| E2E harness | `julia --project=. tests/e2e/runner.jl --tier=1` |
| MCP bridge | `python mcp_server/server.py` (stdio) · `--http` (SSE :8083) · `python mcp_server/http_server.py` (:8000) |
| MCP smoke | `python mcp_server/smoke_test.py` (`RUN_WS=1` also hits the live engine) |
| Endpoint smoke | `powershell -File scripts/smoke_endpoints.ps1` |
| Docker | `docker compose up --build` |
| Skip dep install | `SPARKBYTE_SKIP_PKG_INSTANTIATE=1` |

Tests do **not** need a running engine: the A2A and control-API suites exercise HTTP
in-process with mock streams. `runtests.jl` also shells out to `tool_execute_code`
(Python), so a system `python` must be on PATH.

## Repo layout & filing rules

Root is core engine code/config only. Engine code lives in `src/JLEngine/` or `BYTE/src/`; helpers live in `scripts/`; tests and manual test artifacts live under `test/`. Images/SVG/HTML belong in `assets/`; dead files belong in `archive/`; scratch belongs in `tmp/`. Never hand-place files in `data/` or `logs/` (engine-owned runtime).

- `src/JLEngine.jl` is the module loader: it `include`s every `src/JLEngine/*.jl` in a
  fixed order, then `src/App.jl`. Add new engine modules to that list, not ad hoc.
- `src/App.jl` pulls in `BYTE/src/BYTE.jl` and `a2a_server.jl` by relative path. `BYTE/`
  has its own `Project.toml` but is **not** a Pkg dependency — no separate instantiate.
- `tests/e2e/` ("Omni Ascension") is a separate harness with its own framework/runner,
  distinct from the `test/` unit suite. `web/` is a standalone Next.js app (own
  `package.json`; use `npm` there, not the Julia toolchain).
- `JL_Engine-SB.Omni/JL_Engine-SB.Omni/` is an **untracked stale duplicate** of the repo.
  Never edit it; expect `grep -r` to return duplicate hits.

## Architecture

Per-turn pipeline (`src/JLEngine/Core.jl`), all before the LLM sees the message:

```
msg → SignalScorer → BehaviorStateMachine → DriftPressureSystem → RhythmEngine
→ EmotionalAperture → StateManager advisory → shaped prompt → LLM → tool loop → reply
```

Every turn writes a `turn_snapshots` row (gait, rhythm, aperture, drift, stability). The
behavioral vocabulary (5×4 grid, gaits, rhythm modes, aperture) is diagrammed in `README.md`.

- `src/JLEngine/Core.jl` — `JLEngineCore`, `analyze_turn!`, `run_turn!`, `set_cognitive_callback!`.
- `BYTE/src/BYTE.jl` — WebSocket server + agentic loop; `Tools.jl` — tool dispatch;
  `Schema.jl` — tool schemas (Gemini `function_declarations`). UI is the single inlined
  `BYTE/src/ui.html`.
- `a2a_server.jl` — A2A (`/.well-known/agent.json`, JSON-RPC `tasks/send`); its entrypoint
  is `run_turn!`.
- `BYTE.jl` also serves a local control API on 8081: `GET /control/state`, `GET /control/tools`,
  `POST /control/dispatch`, `POST /control/cancel`.
- `mcp_server/server.py` — FastMCP bridge: database query tools, live A2A turn execution,
  and Ruida serial tools. The laser job tool uploads without starting by default; explicitly
  set `auto_start=true` to start a job.

## Teamwork

Teamwork settings live in `opencode.json` and `.omo/`; local credentials and runtime state are not committed.

**1. OpenCode MCP teamwork** (what an OpenCode session gets by default). `opencode.json`
launches two local MCP servers: `sparkbyte` (read-only tool allowlist — only the 6 names
under `tools` are enabled) and `sparkbyte-teamwork` (team/task/message board in
`.opencode/teamwork.sqlite3`; reads SparkByte `/control/state`). The `team-lead` agent runs
with `edit` and `bash` **denied** and may only spawn the read-only `team-researcher` /
`team-verifier` subagents. `sparkbyte_runtime_state` needs the live engine.

**2. OMO Team Mode** (`.omo/omo.jsonc` + `.omo/teams/sparkbyte-omni/config.json`). Lead
`sisyphus` delegates to six specialist categories. Every worker goal: trace the real
contracts from source, own only explicitly assigned disjoint files, coordinate before
edits, report exact paths + evidence through the team mailbox, never claim a runtime action
that didn't happen, and create no nested teams.

| Member | Category | Focus |
|---|---|---|
| architect | `sparkbyte-architect` | Engine architecture, contracts, dependency impact |
| runtime | `sparkbyte-runtime` | Julia/BYTE lifecycle, runtime + MCP/API behavior |
| behavior | `sparkbyte-behavior` | SignalScorer, behavior, drift, rhythm, aperture |
| telemetry | `sparkbyte-telemetry` | Telemetry, snapshots, persistence, broadcasts |
| qa | `sparkbyte-qa` | Assigned-scope verification, failure paths, regressions |
| integration | `sparkbyte-integration` | SparkByte / OpenCode / MCP / HTTP-A2A boundaries |

Limits: 7 members, 500 messages/run, 60 min, 80 turns/member; ≤8 tasks/team and ≤3
concurrent. Duplicate task titles, duplicate claims, and overlapping parent/child write
paths are rejected; `team_fail` releases a worker's claims. Routing is DeepSeek V3.2 for
the lead + architect/runtime/integration, Qwen3.5 Flash for behavior/telemetry/qa. OMO
is an optional experimental integration; start it only through its current checked-in configuration.

## Gotchas

1. `run_turn!` (in `a2a_server.jl`) is the real A2A entrypoint; `process_turn` was never a
   symbol — don't `import` it.
2. `sparkbyte.jl`, `src/JLEngine.jl`, and `BYTE/src/Tools.jl` force
   `JULIA_CONDAPKG_BACKEND=Null` + `JULIA_PYTHONCALL_EXE=python`. CondaPkg will not provision
   Python; Playwright and other deps must already exist in the system `python`.
3. SQLite schema is created at boot in `src/App.jl:_open_memory_db` via
   `CREATE TABLE IF NOT EXISTS` (~12 tables). Add new tables/columns there — there is no
   migration framework.
4. `_seed_self_context!` is destructive on every boot: it deletes `memory` rows tagged
   `self_tree`/`self_src` and runs `DELETE FROM agents`, then re-seeds. Don't treat those
   as durable.
5. Env vars are read lazily through functions (e.g. `_a2a_port()` in `a2a_server.jl`), so the
   `.env` loaded in `sparkbyte.jl` takes effect; constants compiled in `Backends.jl` are read
   at compile time.
6. `src/Autopilot.jl` exists and documents `SPARKBYTE_AUTOPILOT_SECONDS`, but it is **not
   `include`d anywhere** — autopilot is not wired into `app_main`. The only background loop
   that actually runs is Julian (`_start_julian_autonomous_loop!`, gated by
   `JULIAN_AUTONOMOUS_SECONDS > 0`).
7. Forge is live and irreversible: `forge_new_tool` `include_string`s Julia into `Main.BYTE`
   and persists to `dynamic_tools.jl`. There is no un-forge — edit the file and restart. The
   runtime registry (`dynamic_tools_registry.json`) and the SQLite `tools` table can diverge.
8. MCP security: sandboxed paths must resolve under the repo root or `$HOME`
   (`MCP_ALLOW_EXTERNAL_PATHS=1` disables); non-loopback bind requires
   `MCP_BIND_ACK=I_understand_no_builtin_auth` + `MCP_AUTH_TOKEN`; `SPARKBYTE_WS` must be
   loopback unless `MCP_ALLOW_REMOTE_WS=1`.
9. `health_check.jl` runs on every boot and writes `health_check.log`; a non-empty report is
   informational, not a boot failure.
10. Gitignored runtime state, regenerated at boot: `*.db`, `*.jsonl`, `*.log`,
    `dynamic_tools.jl`, `dynamic_tools_registry.json`, `Manifest.toml`, `_mcp_inspect/`,
    `hunts/`, `.env` (see `.gitignore`).

## Environment

Copy `.env.example` → `.env` (gitignored) before booting.

| Variable | Default | Notes |
|---|---|---|
| `SPARKBYTE_HOST` / `SPARKBYTE_PORT` | 127.0.0.1 / 8081 | WebSocket + HTTP UI + control API |
| `SPARKBYTE_ROOT` | auto-detect | Must contain `data/agents/Agents.mpf.json` |
| `SPARKBYTE_STATE_DIR` | `<root>/data` | Override data dir |
| `SPARKBYTE_LAUNCH_BROWSER` | 1 | Set `0` to skip opening a browser on boot |
| `A2A_HOST` / `A2A_PORT` | 127.0.0.1 / 8082 | A2A protocol |
| `A2A_API_KEY` | — | Required when A2A is exposed beyond localhost |
| `OPENROUTER_API_KEY` | — | Primary provider (also `OPENAI_`, `GEMINI_`, `XAI_`, `CEREBRAS_`, `OLLAMA_BASE_URL`) |
| `JULIAN_AUTONOMOUS_SECONDS` | 0 | Julian autonomy interval; 0 = off |
| `SPARKBYTE_AUTOPILOT_SECONDS` | 0 | Documented but currently inert (see Gotcha 6) |
| `SPARKBYTE_TOOL_FAILURE_THRESHOLD` | 3 | Auto-quarantine a forged tool after N dispatch failures |

## Agent system (MPF)

Agents are registered in `data/agents/Agents.mpf.json`, each pointing at a "fat" JSON profile.
Switch in the UI with `/gear <AgentName>` or in code with `set_agent!`. Built-ins: SparkByte
(quirky/creative, default), Slappy, The Gremlin, Temporal, Supervisor.
