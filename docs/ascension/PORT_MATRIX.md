# Port Matrix: Reference Candidates & Ascension Decisions
**Operation Omni Ascension — Wave 0 Technical Port Matrix**  
**Document Version:** 1.0.0 (Wave 0 Final)  
**Date:** 2026-10-14  
**Primary Target Repository:** `C:\Users\J_lin\Desktop\JL_Engine-SB.Omni` (`feature/omni-ascension`)  
**Verified Origin HEAD Commit:** `9bd604e1fcee7eb40f462734d2e8d492e5ad3886`  

---

## 1. Decision Summary

A comprehensive diff audit and architectural evaluation was conducted across the three reference remotes (`vrp`, `omni-old`, `sparkbyte-sb`) against the primary repository. Exactly 29 reference candidates were cataloged, analyzed, and assigned authoritative architectural decisions:

| Decision Category | Count | Strategic Rationale |
|:---|:---:|:---|
| **ALREADY PRESENT** | 4 | Features already merged into primary HEAD (`9bd604e`) during prior development. |
| **PORT** | 6 | Clean, isolated components ported directly with exact fidelity into target paths. |
| **ADAPT** | 12 | High-value components adapted to match Omni architecture, naming, and contracts. |
| **DEFER** | 2 | Specialized or external protocols deferred to post-ascension plugin waves. |
| **REJECT** | 5 | Dangerous anti-patterns, destructive recovery loops, or unverified binary blobs. |
| **TOTAL** | **29** | Complete catalog of candidate reference features. |

---

## 2. Complete 29-Candidate Port Matrix

| ID | Source Remote & Commit | Source File / Feature | Target Destination File | Target Wave | Decision | Technical Rationale & Implementation Notes |
|:---:|:---|:---|:---|:---:|:---:|:---|
| **C-01** | `vrp:master` (`5198053`)<br>`vrp:main` (`00deddd`) | `sparkbyte.jl:68` (`netstat taskkill /PID %a /F` on 8081) | None | Wave 0 | **REJECT** | Blindly force-kills unrelated host processes on port 8081; violates safe shutdown standards and host isolation. |
| **C-02** | `vrp:master` (`5198053`)<br>`vrp:main` (`00deddd`) | `sparkbyte.jl:76-80` (manual `rm -wal` and `-shm`) | None | Wave 0 | **REJECT** | Causes silent database corruption by deleting uncheckpointed transactions. Recovery must use native SQLite WAL roll-forward. |
| **C-03** | `vrp:master` (`5198053`)<br>`vrp:main` (`00deddd`) | `sparkbyte.jl:96-102` (interactive `readline()` prompt) | None | Wave 0 | **REJECT** | Freezes unattended, daemon, background agent, or CI processes indefinitely waiting on stdin. |
| **C-04** | `omni-old:master` (`625e760`) | `tools/tunnel-client/tunnel-client.exe` (20.5MB) | None | Wave 0 | **REJECT** | Opaque, unversioned binary blob in source control. Violates supply chain security and repo cleanliness. |
| **C-05** | `sparkbyte-sb:main` (`631e2c8`) | `sparkbyte.jl` (inlined `Pkg.add` & single-file flatten) | None | Wave 0 | **REJECT** | Destroys modular `JLEngine` architecture and causes startup latency/dependency churn on every boot. |
| **C-06** | `vrp:master` (`5198053`) | `.env.example` (45 environment variable templates) | `.env.example` | Wave 0 | **ADAPT** | Adapted with OpenRouter as primary provider defaults, port 8081, and all 45 environment parameters documented. |
| **C-07** | `sparkbyte-sb:main` (`631e2c8`) | Early `.env` file loader before health check | `sparkbyte.jl` | Wave 0 | **PORT** | Loads `.env` variables at entrypoint so `SPARKBYTE_PORT` and other keys are active before health check runs. |
| **C-08** | `vrp:master` (`5198053`) | `health_check.jl` (broad directory scan & noise filter) | `health_check.jl` | Wave 0 | **PORT** | Scans `BYTE/src` and `src/*.jl`, filters JSON schema primitives; prevents false-positive WS warnings. |
| **C-09** | `sparkbyte-sb:main` (`631e2c8`) | `start.bat` (canonical Windows launcher) | `start.bat` | Wave 0 | **PORT** | Clean Windows runner executing `julia --project=. sparkbyte.jl`. |
| **C-10** | `sparkbyte-sb:main` (`631e2c8`) | `install.bat` (preflight & dependency check) | `install.bat` | Wave 0 | **ADAPT** | Adapted to use deterministic `Pkg.instantiate()` instead of `Pkg.add`. Checks Julia/Python prerequisites and copies `.env`. |
| **C-11** | `sparkbyte-sb:main` (`631e2c8`) | `src/JLEngine/AgentManager.jl` (`return nothing` fix) | `src/JLEngine/AgentManager.jl` | Wave 0 | **PORT** | Replaces bare returns on lines 29 and 40 with explicit `return nothing` for type inference stability. |
| **C-12** | `vrp:main` (`00deddd`) | `scripts/@py-scripts/bughunt/` (`smoke_matrix.py`) | `scripts/bughunt/` | Wave 0 | **PORT** | Automated HTTP endpoint smoke tester and error log triage utility. |
| **C-13** | `vrp:main` (`00deddd`) | `BYTE/src/BYTE.jl` (`/control/state`, `/control/tools`, `/control/dispatch`) | `BYTE/src/BYTE.jl` | Wave 1 | **ADAPT** | Headless REST API and CORS support for external tool execution, subagent control, and MCP clients. Translate operator -> agent. |
| **C-14** | `vrp:master` (`5198053`) | `src/JLEngine/Backends.jl` (Ollama, Gemini, Cerebras backends) | `src/JLEngine/Backends.jl` | Wave 1 | **ADAPT** | Integrate Ollama and CustomHTTP providers alongside primary `OpenRouterBackend` under `AbstractBackend` fallback chain. |
| **C-15** | `omni-old:master` (`625e760`) | `/tokens` endpoint and session token counter | `BYTE/src/BYTE.jl` | Wave 1 | **ALREADY PRESENT** | Verified active and verified in primary HEAD commit `9bd604e`. |
| **C-16** | `vrp:master` (`5198053`) | `BYTE/src/ui.html` (`settings-modal` with OpenRouter key) | `BYTE/src/ui.html` | Wave 2 | **ALREADY PRESENT** | Verified active in primary HEAD; requires wiring to typed SQLite configuration persistence. |
| **C-17** | `vrp:master` (`5198053`) | `BYTE/src/ui.html` (`mission-panel` plan/step viewer) | `BYTE/src/ui.html` | Wave 3 | **ADAPT** | Autonomous goal breakdown, active plan step viewer, and abort control for multi-agent teamwork. |
| **C-18** | `vrp:master` (`5198053`) | `BYTE/src/ui.html` (`mind-panel` thought/memory graph) | `BYTE/src/ui.html` | Wave 4 | **ADAPT** | Canvas/SVG graph visualizer connecting directly to `Autopilot.jl`'s existing `mind_graph` WebSocket broadcast. |
| **C-19** | `vrp:master` (`5198053`) | `BYTE/src/ui.html` (`forge-panel` live stream & editor) | `BYTE/src/ui.html` | Wave 4 | **ALREADY PRESENT** | Verified present in primary HEAD (`forge-panel` and `forge_resubmit`). |
| **C-20** | `vrp:main` (`00deddd`) | `test/test_dynamic_tools.jl` (11 tool validation suites) | `test/test_dynamic_tools.jl` | Wave 4 | **PORT** | Comprehensive test battery validating dynamic tool execution, world-age safety, and parameter normalization. |
| **C-21** | `vrp:master` (`5198053`) | `BYTE/src/ui.html` (`browser-center` Playwright screen) | `BYTE/src/ui.html` | Wave 5 | **ADAPT** | Interactive visual browser pane with click tracking, URL navigation, and stealth mode toggle. |
| **C-22** | `vrp:master` (`5198053`) | `BYTE/src/ui.html` (`terminal-panel` with xterm.js) | `BYTE/src/ui.html` | Wave 5 | **ADAPT** | Embedded interactive console container for host command output and terminal execution. |
| **C-23** | `vrp:main` (`00deddd`) | `src/Tools/ReplTools.jl` (Persistent REPL stdin pipes) | `src/Tools/ReplTools.jl` | Wave 5 | **ADAPT** | Persistent state REPL sessions for Python and Julia subprocess execution. |
| **C-24** | `vrp:main` (`00deddd`) | `src/Tools/MetaReasonTools.jl` (Retrospective tool sweep) | `src/Tools/MetaReasonTools.jl` | Wave 5 | **ADAPT** | Periodic tool execution review buffer for self-monitoring and cognitive reflection. |
| **C-25** | `vrp:main` (`00deddd`) | `test/runtests.jl` (JLEngine 10-subsystem test battery) | `test/runtests.jl` | Wave 6 | **ADAPT** | Comprehensive unit test battery covering Config, Signals, Behavior, Rhythm, Drift, Aperture, Core. |
| **C-26** | `vrp:main` (`00deddd`) | `scripts/build_exe.jl` & `build_exe.bat` (PackageCompiler) | `scripts/` | Wave 6 | **ADAPT** | Standalone Windows `.exe` distribution bundler using PackageCompiler.jl. |
| **C-27** | `vrp:main` (`00deddd`) | `burp-extension/` & `PentestTools.jl` / `CascadeTools.jl` | None | Future | **DEFER** | Offensive security and penetration testing utilities; deferred to specialized security plugin. |
| **C-28** | `vrp:main` (`00deddd`) | Fetch.ai / Agentverse / Almanac scripts | None | Future | **DEFER** | Third-party cryptocurrency/blockchain agent protocol; deferred to future external ecosystem wave. |
| **C-29** | `omni-old:master` (`625e760`) | `Balthazar` agent profile (`Balth.json`, `Balth.md`) | `data/agents/` | Wave 0 | **ALREADY PRESENT** | Verified active in primary HEAD (`data/agents/Balth.json`, 1,055 lines). |

---

## 3. Wave Execution Roadmap

- **Wave 0 (Baseline)**: C-01..C-05 rejected. C-06, C-07, C-08, C-09, C-10, C-11 ported/adapted. Architecture & Port Matrix documented.
- **Wave 1 (Model Providers & Settings)**: Port C-13 (`/control/*`), adapt C-14 (`Backends.jl`), implement OpenRouter SSE streaming and dynamic model discovery.
- **Wave 2 (Control Center UI)**: Integrate authoritative settings screens, dynamic model dropdowns, and clean UI telemetry.
- **Wave 3 (Teamwork & Worktrees)**: Adapt C-17 (`mission-panel`), implement concurrent task board and isolated Git worktrees.
- **Wave 4 (Memory, Lattice & Tool Forge)**: Adapt C-18 (`mind-panel`), port C-20 (`test_dynamic_tools.jl`), wire behavioral lattice inspection.
- **Wave 5 (Workspace, Terminal & Browser)**: Adapt C-21 (`browser-center`), C-22 (`terminal-panel`), C-23 (`ReplTools.jl`), C-24 (`MetaReasonTools.jl`).
- **Wave 6 (Hardening & Release)**: Adapt C-25 (`runtests.jl`), adapt C-26 (`build_exe.jl`), run full regression and E2E validation.
