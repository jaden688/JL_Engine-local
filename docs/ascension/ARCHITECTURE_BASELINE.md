# Architecture Baseline & System Specification
**Operation Omni Ascension — Wave 0 Technical Architecture Baseline**  
**Document Version:** 1.0.0 (Wave 0 Final)  
**Date:** 2026-10-14  
**Primary Working Directory:** `C:\Users\J_lin\Desktop\JL_Engine-SB.Omni`  
**Primary Git Branch:** `feature/omni-ascension`  

---

## 1. Executive Overview

Operation Omni Ascension establishes the Julia-native SparkByte Omni engine as an authoritative, observable, multi-agent AI environment. The architecture pairs a Julia 1.12 core engine (`JLEngine`) with an authoritative HTTP/WebSocket web control center (`BYTE`), world-age safe dynamic tool forge (`BYTE/src/Tools.jl`), and native SQLite transaction persistence (`data/sparkbyte_memory.db`).

The Wave 0 milestone establishes the baseline:
1. Verified repository inventory and remote commit baseline.
2. Port 8081 harmonization across all entrypoints and configurations.
3. Strict, audited ban on destructive recovery anti-patterns (blind process termination and manual SQLite WAL deletion).
4. Porting of critical Wave 0 foundation assets (`.env.example`, early `.env` loader, health scanner enhancement, Windows launchers, and `AgentManager.jl` type fix).
5. Clean health checks (0 errors, 0 warnings) and 100% test suite pass rate.

---

## 2. Verified Repository Inventory & Commit Hashes

All remote repositories have been queried, inspected, and configured within the primary workspace:

| Remote Alias | Git Remote URL | Verified Branch | Verified Commit SHA | Role / Relationship |
|:---|:---|:---|:---|:---|
| **origin** (primary) | `https://github.com/jaden688/JL_Engine-SB.Omni.git` | `main` | `9bd604e1fcee7eb40f462734d2e8d492e5ad3886` | Primary target destination for Operation Omni Ascension on branch `feature/omni-ascension`. Contains core Julia engine, cognitive lattice, and web server. |
| **vrp** | `https://github.com/jaden688/jl-engine-vrp.git` | `master`<br>`main` | `master`: `5198053f5426db1cb17a085dd5376290ef9e3373`<br>`main`: `00deddde44c80780e0102b68e7747ff53f741e19` | Vulnerability Research Platform reference. Source of `.env.example`, multi-provider backends, HTTP control plane (`/control/*`), UI panels (`mind-panel`, `browser-center`), and dynamic tool test suites. Contains destructive patterns explicitly rejected. |
| **omni-old** | `https://github.com/jaden688/JL_Engine-SB.Omni-20260702.git` | `main` / `master` | `625e760d489ad948efeceb0a21fe94db4f870132` | Historical baseline (July 2026). Key features (token accounting, Balthazar agent) already incorporated into primary HEAD. |
| **sparkbyte-sb** | `https://github.com/jaden688/JL-Engine-SB.git` | `main` | `631e2c83f1fd9f0b13fc0bdd475d75fe2e505830` | Windows distribution variant. Source of `start.bat`, `install.bat`, and `AgentManager.jl` type fix (`return nothing`). |

---

## 3. Runtime Environment & Julia Dependencies

The engine is built on **Julia 1.12.6** running on Windows x86_64. Dependency resolution is governed strictly by `Project.toml` and locked via `Manifest.toml`.

### Instantiated Packages (Julia 1.12)
- **Colors v0.13.1**: Color models and perceptual palette handling.
- **DataFrames v1.8.2**: In-memory tabular data structures.
- **FileIO v1.19.0**: Abstract file format I/O manager.
- **HTTP v1.11.0**: High-performance HTTP client/server and WebSocket transport.
- **ImageIO v0.6.9** & **Images v0.26.2**: Visual processing and canvas manipulation.
- **JSON v1.6.1** & **JSON3 v1.14.3**: High-throughput JSON parsing and serialization.
- **PythonCall v0.9.34**: In-process Python C-API bridge (`JULIA_CONDAPKG_BACKEND=Null`).
- **SQLite v1.8.0**: Native SQLite bindings for zero-copy embedded database operations.
- **Standard Libraries**: Base64, Dates, Random, SHA, UUIDs.

---

## 4. Architectural Subsystems Baseline

### 4.1 Core Engine Architecture (`src/JLEngine/`)
The core engine provides an autonomous cognitive runtime operating on a 20-cell (5×4) behavioral lattice:
- **`Backends.jl`**: Model provider routing abstraction (`AbstractBackend`). Primary provider is OpenRouter (`DEFAULT_OPENROUTER_ENDPOINT`, `DEFAULT_OPENROUTER_MODEL = "deepseek/deepseek-v4-flash"`). Extensible to Ollama, Gemini, Cerebras, and Azure.
- **`Behavior.jl`**: State machine managing cognitive modes (Focus, Explore, Sprint, Drift, Rest) and mode transitions.
- **`MPF.jl` & `AgentManager.jl`**: Multi-Agent Framework managing agent loadouts (`data/agents/Agents.mpf.json`). Cross-agent relation search uses explicit `return nothing` type safety.
- **`Signals.jl`**: Turn signal scorer evaluating user input sentiment, complexity, and urgency.
- **`Aperture.jl`**: Emotional aperture modulating temperature, top_p, and generation bounds.
- **`Drift.jl`**: Entropy and pressure tracking preventing cognitive stagnation or looping.
- **`Rhythm.jl`**: Cadence, momentum, and operational tempo regulation.
- **`App.jl`**: Engine initialization, memory DB attachment, and entrypoint orchestration. Port 8081 aligned.

### 4.2 Web & Control Center Architecture (`BYTE/`)
- **`BYTE/src/BYTE.jl`**: Asynchronous HTTP and WebSocket server running on `http://127.0.0.1:8081`. Coordinates live message dispatch, session telemetry, token accounting (`/tokens`), agent status (`/operator`), and streaming responses.
- **`BYTE/src/ui.html`**: Desktop control center interface providing file explorer, live terminal, tool visualizer, cognitive graph inspector, and settings screens.
- **`BYTE/src/Tools.jl`**: Authoritative tool dispatcher. Houses both static core tools and dynamic forged tools.

### 4.3 Dynamic Tool Forge & World-Age Safety
Dynamic tools are evaluated into the `BYTE` module at runtime. To prevent Julia world-age violations (`MethodError: no method matching ... in world X, current world Y`):
1. Code expressions are parsed via `Meta.parseall` and evaluated sequentially.
2. Tool definitions are verified with `isdefined(BYTE, sym)`.
3. Execution is dispatched strictly through `Base.invokelatest`:
   ```julia
   TOOL_MAP[name] = (args) -> Base.invokelatest(getfield(@__MODULE__, _sym), args)
   ```
4. AST pre-checks enforce a strict security deny-list blocking API key leakage and file tampering.

### 4.4 Persistence Architecture
- **Database:** `data/sparkbyte_memory.db` (SQLite).
- **Schema:** 12 indexed tables (`memory`, `tools`, `thoughts`, `knowledge`, `agents`, `behavior_states`, `sessions`, `web_cache`, `tool_usage_log`, `telemetry`, `conversation_turns`, `turn_snapshots`).
- **Journaling:** Native SQLite Write-Ahead Logging (`WAL`).

---

## 5. Non-Negotiable Engineering Rules & Anti-Pattern Rejections

To maintain system integrity and host stability, the following architectural rules are strictly enforced:

### Rule 1: Definitive Ban on Blind Process Termination
- **Banned Behavior:** Running host commands such as:
  ```cmd
  netstat -ano | findstr :8081 | ... taskkill /PID %a /F
  ```
- **Hazard:** Indiscriminately kills unrelated host processes listening on port 8081, prevents orderly database flushing, and causes file lock corruption.
- **Enforced Standard:** Graceful process shutdown via SIGINT, WebSocket `/runtime/shutdown`, or clean port ownership diagnostics.

### Rule 2: Definitive Ban on Manual SQLite `-wal` and `-shm` File Deletion
- **Banned Behavior:** Executing `rm(db_path * "-wal")` or `rm(db_path * "-shm")`.
- **Hazard:** Deleting `-wal` deletes uncheckpointed database transactions and corrupts the SQLite database irreparably.
- **Enforced Standard:** Database recovery is handled entirely by SQLite's native crash recovery on connection open and explicit `PRAGMA wal_checkpoint(TRUNCATE);` calls.

### Rule 3: Ban on Interactive Blocking Prompts in Daemon Loops
- **Banned Behavior:** Using `readline()` inside crash or recovery loops.
- **Hazard:** Freezes headless, daemon, service, and automated agent workflows indefinitely.
- **Enforced Standard:** Configurable non-interactive recovery policies with backoff limits.

### Rule 4: Ban on Unversioned Large Binaries in Source Control
- **Banned Behavior:** Checking `.exe`, `.dll`, or `.zip` binary archives into git.
- **Enforced Standard:** Pure source code repository; binary tools must be provisioned via build scripts or package managers.

### Rule 5: Ban on Per-Run `Pkg.add` Calls
- **Banned Behavior:** Running `Pkg.add(...)` during application boot.
- **Hazard:** Network contention, non-deterministic dependencies, and slow startup.
- **Enforced Standard:** Deterministic pre-instantiation via `Pkg.instantiate()` based on `Project.toml` and `Manifest.toml`.

### Rule 6: Zero Mock UI State
- **Banned Behavior:** Hardcoding UI status, model catalogs, or mock settings in HTML/JS.
- **Enforced Standard:** All UI telemetry, model catalogs, and settings must bind directly to authoritative Julia runtime APIs.

---

## 6. Operational Entrypoints

- **`start.bat`**: Canonical Windows launcher (`julia --project=. sparkbyte.jl`).
- **`Launch_SparkByte.bat`**: Desktop launcher with port 8081 health polling and browser launching.
- **`install.bat`**: Setup and dependency bootstrap (`Pkg.instantiate()`, pip requirements, `.env` template copy).
- **`sparkbyte.jl`**: Core Julia bootstrap script with early `.env` loading and pre-flight health scan.
- **`health_check.jl`**: Pre-flight static code and message audit scanner.
