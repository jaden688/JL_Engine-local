# Operators Hub — Repo Map & Filing Rules

This folder is the operator's home base: agent docs, project notes, and this map of
where everything lives. **When you create a file, file it by these rules** so the root
stays clean and things stay findable.

## Repo layout

| Location | What lives there |
|---|---|
| `/` (root) | **Core engine code only** — boot files (`sparkbyte.jl`, `health_check.jl`, `a2a_server.jl`, etc.), project configs (`Project.toml`, `Manifest.toml`, `compose.yaml`, `Dockerfile`, `.env`), and standard docs (`README.md`, `LICENSE`, `AGENTS.md`, `PRIVACY.md`, `NOTICE.md`, `DOCKER.md`). Nothing else goes here. |
| `src/` | JLEngine core modules (behavioral pipeline) |
| `BYTE/` | WebSocket server, agentic loop, tool forge, console UI |
| `mcp_server/` | Python MCP bridge |
| `data/` | **Runtime persistent state** — memory DBs, forged tools, agent registry (`data/agents/`), configs. The engine writes here; don't hand-file code here. |
| `logs/` | Runtime logs (`full_telemetry.jsonl`, `health_check.log`, session logs) |
| `operators/` | This hub. `agents/` = agent identity docs (ABOUT_AGENT, AGENT_PROFILE, AGENT_HANDOFF). `notes/` = project notes, plans, rename/copy notes, compliance plan. |
| `scripts/` | Operational scripts (PowerShell/Python helpers, launcher) |
| `test/` | Test suite (`runtests.jl` + `test_*.jl`). `test/manual/` = one-off/manual test scripts (test_browser, test_cerebras, stress_test, roast tests…). |
| `assets/` | `images/` = wallpapers/art. `laser/` = laser-cutter SVGs + their HTML previews. `pages/` = standalone landing/marketing HTML pages. |
| `archive/` | Cold storage — zips, old API dumps, `stale-launchers/` (bat files pointing at scripts that no longer exist), `temp-scripts/` (old _temp_hunt*.ps1). Safe to ignore; don't delete without checking. |
| `web/` | Next.js web app (its own package.json — don't drop loose HTML here) |
| `tools/`, `bridge/`, `infra/`, `upgrades/`, `hunts/` | Supporting subsystems |
| `JulianMetaMorph/` | GitHub intelligence / skill-forging monorepo |
| `tmp/` | Scratch space — anything disposable |

## Filing rules for new files

1. **New Julia engine code** → `src/JLEngine/` or `BYTE/src/`, never root.
2. **One-off test or experiment script** → `test/manual/` (Julia/Python) or `tmp/` if truly disposable.
3. **Operational helper script** → `scripts/`.
4. **Docs & notes** → `operators/notes/`; agent identity docs → `operators/agents/`.
5. **Images/SVGs/HTML pages** → the matching `assets/` subfolder.
6. **Zips, dumps, dead launchers** → `archive/`.
7. **Never hand-place files in `data/` or `logs/`** — those are the engine's.

## Things deliberately left at root

- **Symlinks** (`forge_tool.jl`, `riff.jl`, `verify_forge.jl`, `test_engine.jl`, `full_telemetry.jsonl`, `sb_18081_*.log`, `run_demo.bat`, etc.) — left untouched; their targets may be referenced elsewhere.
- **Runtime files** (`sparkbyte_state.db`, `health_check.log`) — a live engine may write these; if runtime files scatter into root, check the resolvers (`_telemetry_root`, `_health_state_dir`, `_runtime_state_dir`).
- **`AGENTS.md`** — stays at root by agent-tooling convention.
