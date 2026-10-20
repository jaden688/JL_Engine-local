# OPERATION OMNI ASCENSION: END-TO-END TEST INFRASTRUCTURE SPECIFICATION (TEST_INFRA.md)

**Document Version:** 1.0.0  
**Target Repository:** `C:\Users\J_lin\Desktop\JL_Engine-SB.Omni`  
**Target Branch:** `feature/omni-ascension`  
**Owner:** E2E Test Architect (`test_writer_e2e`)  
**Authority:** Derived from `ORIGINAL_REQUEST.md`, `PROJECT.md`, and `OMNI_ASCENSION_AGENT_HANDOFF.md`  

---

## 1. EXECUTIVE SUMMARY & TEST PHILOSOPHY

### 1.1 Dual-Track Quality Architecture
Operation Omni Ascension establishes a parallel **E2E Testing Track** executing alongside the **Implementation Track (Waves 0-6)**. The testing track operates independently from internal implementation details to ensure that all deliverables satisfy user requirements, interface contracts, and non-negotiable operational invariants.

### 1.2 Core Testing Principles
1. **Opaque-Box / Black-Box Verification:**
   - E2E tests interact with SparkByte Omni strictly through external, public interfaces:
     * HTTP REST Endpoints (`http://127.0.0.1:8081/api/...`, `http://127.0.0.1:8081/control/...`, `http://127.0.0.1:8081/runtime/...`)
     * WebSocket Message Bus (`ws://127.0.0.1:8081/ws`)
     * Process-level CLI and Batch entrypoints (`sparkbyte.jl`, `Launch_SparkByte.bat`, `start.bat`)
     * Environment variables (`.env`, `SPARKBYTE_*`, `OPENROUTER_API_KEY`)
     * File-system artifacts, Git worktrees, and persistent SQLite databases (`data/sparkbyte_memory.db`) queried via standard SQL.
   - Tests do NOT import private module internals or manipulate private struct fields directly.
2. **Authoritative Expected Output Derivation:**
   - For every test case, the expected output is derived from:
     * Explicit requirements in `ORIGINAL_REQUEST.md` (R1-R5).
     * Interface contracts and feature specs in `PROJECT.md` (F01-F30).
     * Reference protocols in `OMNI_ASCENSION_AGENT_HANDOFF.md`.
   - When external dependencies produce non-deterministic data (e.g., UUIDs, ISO 8601 timestamps, process IDs, ephemeral paths), expected outputs are matched using structural JSON schema validation and regular expressions (`^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}`, `^[a-f0-9-]{36}$`).
3. **Zero Facade Tests:**
   - Trivial assertions (`@test true == true`) are strictly forbidden. Every test must exercise real logic, execute observable I/O, verify persistent side effects, and fail if the feature is broken or missing.
4. **Environment Isolation & Non-Destructiveness:**
   - Tests run in isolated sandboxes using temporary directories (`mktempdir()`), test-specific database files, and scoped environment variables (`withenv()`).
   - Anti-pattern rejection: E2E tests strictly prohibit destructive shortcuts (such as executing blind `taskkill /F /IM julia.exe` on port 8081 or deleting SQLite WAL files `*.db-wal`). Tests gracefully probe ports, manage child process trees cleanly with targeted process handles, and assert SQLite WAL checkpoint recovery.

---

## 2. 4-TIER TEST ARCHITECTURE & TAXONOMY

The E2E test harness is structured into 4 distinct tiers:

```
┌────────────────────────────────────────────────────────────────────────┐
│                   TIER 4: REAL-WORLD APPLICATION SCENARIOS             │
│        (5 Multi-Step End-to-End Workloads & Lifecycles)                │
├────────────────────────────────────────────────────────────────────────┤
│                 TIER 3: CROSS-FEATURE PAIRWISE COMBINATIONS            │
│         (Interaction Matrix & Combinatorial Fault Injection)           │
├────────────────────────────────────────────────────────────────────────┤
│              TIER 2: BOUNDARY & CORNER CASES (BVA / STRESS)            │
│   (≥5 Boundary Tests per Feature across F01-F30: 150 Boundary Tests)   │
├────────────────────────────────────────────────────────────────────────┤
│                 TIER 1: FEATURE COVERAGE BASELINE                      │
│     (≥5 Happy-Path Tests per Feature across F01-F30: 150 Tests)        │
└────────────────────────────────────────────────────────────────────────┘
```

---

## 3. TIER 1: FEATURE COVERAGE SPECIFICATIONS (F01 – F30)
*Requirement: Minimum 5 distinct opaque-box test cases per feature (Total: 150 tests).*

### F01: Git Baseline & Branch Setup
- **T1-F01-01:** Git repository tracking root points to primary remote `https://github.com/jaden688/JL_Engine-SB.Omni.git`.
- **T1-F01-02:** Active development branch is verified as `feature/omni-ascension`.
- **T1-F01-03:** Baseline commit history reflects upstream HEAD `9bd604e` ancestry.
- **T1-F01-04:** `.gitignore` excludes sensitive files (`.env`, `*.db-wal`, `*.db-shm`, credential caches).
- **T1-F01-05:** Reference remotes (`vrp`, `omni-old`, `sparkbyte-sb`) are queryable without overwriting `origin`.

### F02: Port 8081 Alignment
- **T1-F02-01:** Default host is `127.0.0.1` and default port is `8081` in engine configuration.
- **T1-F02-02:** Windows launch script `Launch_SparkByte.bat` specifies port `8081` in its command line.
- **T1-F02-03:** Windows startup script `start.bat` defaults browser launch to `http://127.0.0.1:8081`.
- **T1-F02-04:** Web server in `BYTE.jl` binds to port `8081` by default when started without environment overrides.
- **T1-F02-05:** Port environment override (`SPARKBYTE_PORT=18081`) is respected without hardcoding.

### F03: Destructive Recovery Rejection
- **T1-F03-01:** Verification scan confirms zero occurrences of blind process kills (`taskkill /f /im julia.exe`) targeting port 8081 in startup scripts.
- **T1-F03-02:** Verification scan confirms zero automated deletion commands (`rm -f *.db-wal`, `del *.db-shm`) across scripts and recovery paths.
- **T1-F03-03:** Port conflict detection initiates clean exit or targeted diagnostic error rather than terminating unrelated processes.
- **T1-F03-04:** SQLite recovery routine relies strictly on native SQLite WAL recovery (`PRAGMA wal_checkpoint(PASSIVE)`) instead of filesystem deletion.
- **T1-F03-05:** Process shutdown signals (SIGINT/Ctrl+C) invoke clean resource de-allocation, closing HTTP listener and SQLite handles.

### F04: Port Matrix & Architecture Baseline
- **T1-F04-01:** Baseline documentation `docs/ascension/ARCHITECTURE_BASELINE.md` exists and contains system component mapping.
- **T1-F04-02:** Port matrix `docs/ascension/PORT_MATRIX.md` exists and catalogs 29 candidate features from reference remotes.
- **T1-F04-03:** Each port candidate in `PORT_MATRIX.md` contains an explicit status (`already present`, `port`, `adapt`, `defer`, or `reject`).
- **T1-F04-04:** Verified commit hashes are documented for all source reference repositories in the architecture baseline.
- **T1-F04-05:** Security and licensing evaluations are recorded for ported components.

### F05: Reference Candidate Ports (Wave 0)
- **T1-F05-01:** Standardized `.env.example` exists at repository root documenting all supported environment variables.
- **T1-F05-02:** Early `.env` loader in `sparkbyte.jl` successfully populates `ENV` prior to package imports.
- **T1-F05-03:** `health_check.jl` executes cleanly from CLI (`julia health_check.jl`) and generates `health_check.log`.
- **T1-F05-04:** Static health scanner detects silent exception swallowers (`catch; end`) and logs warning/error codes.
- **T1-F05-05:** Windows batch scripts invoke Julia with `--project=.` without hardcoding machine-specific user paths.

### F06: OpenRouter Streaming Backend
- **T1-F06-01:** `OpenRouterBackend` registers HTTP endpoint `https://openrouter.ai/api/v1/chat/completions`.
- **T1-F06-02:** Server-Sent Events (SSE) streaming handles chunk parsing (`data: {...}`) and yields incremental tokens.
- **T1-F06-03:** Streaming response returns token usage metrics (prompt tokens, completion tokens) when provided by provider.
- **T1-F06-04:** Cancellation token or stream abort breaks HTTP connection promptly without hanging thread pool.
- **T1-F06-05:** Streaming chat completion endpoint emits structured error payload on upstream HTTP 4xx/5xx responses.

### F07: Live Model Catalog Discovery
- **T1-F07-01:** `fetch_model_catalog` requests `GET https://openrouter.ai/api/v1/models` using configured API credentials.
- **T1-F07-02:** Response parses into a structured list of `ModelInfo` containing ID, name, context length, and pricing.
- **T1-F07-03:** Model catalog caches metadata locally to SQLite or memory to eliminate redundant remote network calls.
- **T1-F07-04:** Cache refresh interval is configurable and respects explicit refresh triggers (`POST /api/models/refresh`).
- **T1-F07-05:** HTTP endpoint `GET /api/models` exposes the cached catalog as a valid JSON array.

### F08: Multi-Provider Extensible Architecture
- **T1-F08-01:** Abstract backend interface `AbstractBackend` defines required methods: `chat_completion`, `stream_chat_completion`, `fetch_model_catalog`, `test_connection`.
- **T1-F08-02:** `BACKEND_REGISTRY` contains distinct providers: `openrouter`, `ollama`, `gemini`, `custom_http`.
- **T1-F08-03:** Dynamic provider registration permits adding new backend implementations at runtime without restart.
- **T1-F08-04:** `test_connection(backend)` executes live ping or minimal token request and returns `ConnectionStatus`.
- **T1-F08-05:** Multiple active backends can coexist for different roles (e.g., OpenRouter for brain, Ollama for tools).

### F09: Fallback Provider Chain
- **T1-F09-01:** `FallbackChain` struct configures an ordered list of backend provider IDs.
- **T1-F09-02:** Automatic failover triggers when primary provider returns `ProviderAuthError` or `ProviderRateLimitError`.
- **T1-F09-03:** Provider timeout triggers fallback when request duration exceeds configured threshold (`source_timeout`).
- **T1-F09-04:** Circuit breaker trips after N consecutive failures, bypassing failed provider for a cooldown window.
- **T1-F09-05:** Diagnostic telemetry records every fallback event with source provider, error code, and target provider.

### F10: Typed Configuration Persistence
- **T1-F10-01:** `EngineConfig` struct maintains typed fields for models, providers, network, memory, and safety.
- **T1-F10-02:** `load_config` initializes default values and overlays SQLite `config` table records.
- **T1-F10-03:** `update_config!(key, value)` writes changes atomically to SQLite database.
- **T1-F10-04:** Persisted configuration survives engine process restart and loads identical values.
- **T1-F10-05:** `.env` synchronization safely writes bootstrap keys without overwriting comments or unrelated vars.

### F11: Secure Credential Storage
- **T1-F11-01:** API keys stored in SQLite database or memory are masked or encrypted at rest.
- **T1-F11-02:** Telemetry logs and console outputs mask API keys (e.g., `sk-or-v1-****1234`).
- **T1-F11-03:** WebSocket bus messages and UI responses sanitize credential fields before transmission.
- **T1-F11-04:** Endpoint `POST /api/config/key` updates key without exposing previous key value in return payload.
- **T1-F11-05:** Key clearance (`DELETE /api/config/key`) removes secret completely from memory and active runtime backends.

### F12: Comprehensive 16-View UI Navigation
- **T1-F12-01:** Web control center serves static HTML/JS/CSS assets on `http://127.0.0.1:8081/`.
- **T1-F12-02:** Navigation sidebar renders selectors for all 16 views (Chat, Dashboard, Agent Control, Teamwork Board, Model Lab, Provider Manager, Agent Studio, Tool Forge, Plugins, Memory, Workspace, Terminal, Browser, Inspector, Logs, Settings).
- **T1-F12-03:** View switching activates corresponding container and updates browser hash/route without page reload.
- **T1-F12-04:** Responsive layout maintains sidebar collapse toggle for compact desktop viewports.
- **T1-F12-05:** UI assets contain zero dead links or missing script references (HTTP 404 check).

### F13: 15 Authoritative Settings Screens
- **T1-F13-01:** All 15 settings screens (Models, Providers, Agents, Agents, Chat, Appearance, Workspaces, Safety, Browser, Memory, Voice, Advanced/Julia, Tools, Automations, Diagnostics) exist in UI DOM.
- **T1-F13-02:** Each setting control maps directly to an HTTP `GET /api/config` key.
- **T1-F13-03:** Submitting a setting change in UI issues `POST /api/config` and receives confirmation.
- **T1-F13-04:** Unsupported options render visibly disabled with tooltip rather than silently accepting input.
- **T1-F13-05:** Settings requiring runtime restart display an explicit restart warning indicator.

### F14: Dynamic UI Model Selector
- **T1-F14-01:** HTML model selector replaces hardcoded `<option>` elements with dynamically populated options.
- **T1-F14-02:** UI model selector displays model provider badge, context length, and pricing tiers.
- **T1-F14-03:** Live search / filter input filters model list in real time without lag.
- **T1-F14-04:** Selecting a model immediately updates active engine runtime model setting via API.
- **T1-F14-05:** Network disconnection falls back to locally cached model list with stale-cache warning.

### F15: Ported UI Panels Integration
- **T1-F15-01:** `mind-panel` renders dynamic SVG/Canvas graph reflecting cognitive state (`_build_mind_graph`).
- **T1-F15-02:** `mission-panel` renders active goal hierarchy, subtasks, and completion progress bars.
- **T1-F15-03:** `browser-center` panel displays web session status, current URL, and screenshot viewer.
- **T1-F15-04:** `terminal-panel` streams command execution stdout/stderr with ANSI color decoding.
- **T1-F15-05:** Panels update in real time via incoming WebSocket events (`ws://127.0.0.1:8081/ws`).

### F16: Headless Control API
- **T1-F16-01:** HTTP `GET /control/state` returns JSON object detailing active agents, models, and memory stats.
- **T1-F16-02:** HTTP `GET /control/tools` returns JSON array of registered tool schemas and signatures.
- **T1-F16-03:** HTTP `POST /control/dispatch` accepts task payload and queues execution asynchronously.
- **T1-F16-04:** CORS headers (`Access-Control-Allow-Origin: *`) are returned on all `/control/*` routes.
- **T1-F16-05:** Invalid JSON dispatch payload returns HTTP 400 with structured validation error message.

### F17: Multi-Agent Teamwork Task Board
- **T1-F17-01:** Task board creates tasks with title, description, assigned agent role, and status column.
- **T1-F17-02:** Task status transitions across columns: `backlog` -> `in_progress` -> `review` -> `done`.
- **T1-F17-03:** Concurrent subagent dispatch schedules independent tasks across available worker slots.
- **T1-F17-04:** Review gate requires explicit review approval before task reaches `done` status.
- **T1-F17-05:** Agent task cancellation aborts active child process and marks task as `cancelled`.

### F18: Isolated Git Worktrees for Agents
- **T1-F18-01:** Dispatching concurrent agent task initializes dedicated Git worktree (`git worktree add`).
- **T1-F18-02:** Agent file modifications occur exclusively within the assigned worktree path.
- **T1-F18-03:** Worktree branch names follow structured convention (`agent/<role>/<task-id>`).
- **T1-F18-04:** Task completion triggers automated merge validation check against base branch before integration.
- **T1-F18-05:** Worktree teardown cleans up filesystem directory (`git worktree remove`) after review approval.

### F19: Reactive Agent Studio & Behavior Lattice
- **T1-F19-01:** Agent Studio loads Modular Agent File (`.mpf.json`) schemas into editable controls.
- **T1-F19-02:** 20-cell cognitive lattice displays current activations and weights.
- **T1-F19-03:** Parameter sliders modify `drift`, `gait`, `aperture`, and `rhythm` in real time.
- **T1-F19-04:** Agent state transition triggers dynamic prompt modification based on state thresholds.
- **T1-F19-05:** Export function serializes active agent configuration into valid MPF JSON schema.

### F20: Persistent Memory & Context Explorer
- **T1-F20-01:** SQLite database table `memory` persists entries with timestamp, tag, key, and content.
- **T1-F20-02:** Keyword and vector/tag search retrieves relevant memory entries within latency budget (<100ms).
- **T1-F20-03:** Context budgeter trims retrieved memories to fit model token limit window.
- **T1-F20-04:** Memory Explorer UI renders searchable table with delete and edit capabilities.
- **T1-F20-05:** Namespace indexing segments memories between global, workspace, and session scopes.

### F21: Dynamic Tool Forge & World-Age Safety
- **T1-F21-01:** Dynamic tool registration synthesizes new Julia function from code string in sandbox.
- **T1-F21-02:** Dynamic tool dispatch utilizes `Base.invokelatest` to prevent Julia world-age errors.
- **T1-F21-03:** AST security validator rejects prohibited function calls (`rm`, `Base.run`, `unsafe_load`).
- **T1-F21-04:** Registered tools persist in `dynamic_tools_registry.json` or SQLite table `tools`.
- **T1-F21-05:** Tool rollback deactivates faulty tool version and restores previous stable implementation.

### F22: Workspace Routing & File Explorer
- **T1-F22-01:** Workspace Explorer enforces root directory boundary, rejecting paths containing `..` escape attempts.
- **T1-F22-02:** File tree endpoint `GET /api/workspace/files` returns hierarchical file listing.
- **T1-F22-03:** File preview endpoint returns text contents for allowed extensions and blocks binary payloads.
- **T1-F22-04:** Git diff preview generates unified diff between working directory and HEAD.
- **T1-F22-05:** Workspace switching changes active file root without server restart.

### F23: Terminal Host Execution & Approvals
- **T1-F23-01:** Terminal host executes shell command and captures stdout, stderr, and exit code.
- **T1-F23-02:** Commands configured under approval policy prompt for user approval before execution.
- **T1-F23-03:** Command execution timeout kills runaway processes after configured duration (`exec_timeout`).
- **T1-F23-04:** Terminal output streams incrementally over WebSocket to UI terminal panel.
- **T1-F23-05:** Environment variables inside terminal execution inherit sanitized parent environment.

### F24: Browser Automation & Job Scheduling
- **T1-F24-01:** Browser controller launches Playwright session in headless mode.
- **T1-F24-02:** Navigation command loads target URL and returns page title and status code.
- **T1-F24-03:** Screenshot command captures PNG buffer and stores artifact in workspace data directory.
- **T1-F24-04:** Job scheduler registers cron or interval triggers and executes scheduled tasks.
- **T1-F24-05:** Scheduler pause/resume controls halt background job triggering without killing session.

### F25: Full Subsystem Regression Testing
- **T1-F25-01:** Engine unit test suite `test/runtests.jl` executes and reports zero failures.
- **T1-F25-02:** Dynamic tool tests `test/test_dynamic_tools.jl` pass without world-age exceptions.
- **T1-F25-03:** Agent-to-Agent protocol tests (`test/test_a2a_protocol.jl`) verify discovery and handshake.
- **T1-F25-04:** Billing and metering unit tests verify token cost calculation algorithms.
- **T1-F25-05:** System health check script runs at boot and logs zero critical structural issues.

### F26: Database Migration & Recovery Validation
- **T1-F26-01:** Database schema version table `schema_migrations` tracks applied migration scripts.
- **T1-F26-02:** Applying new migration script modifies SQLite tables idempotently without data loss.
- **T1-F26-03:** Simulating unclean shutdown (unclosed WAL file) triggers automatic SQLite native WAL checkpoint on boot.
- **T1-F26-04:** Verification confirms zero corruption errors (`PRAGMA integrity_check` returns `ok`).
- **T1-F26-05:** Database rollback script reverts schema changes and verifies data consistency.

### F27: 100% E2E Test Suite Pass (Tiers 1-4)
- **T1-F27-01:** E2E test runner CLI executes full suite and produces complete TAP v13 report.
- **T1-F27-02:** E2E test runner generates valid JUnit XML output file for CI ingestion.
- **T1-F27-03:** Zero test failures or skipped assertions in final test execution report.
- **T1-F27-04:** Test execution summary report is generated at `tests/e2e/results/summary.json`.
- **T1-F27-05:** Artifact `TEST_READY.md` is published with verifiable test run evidence and timestamps.

### F28: Tier 5 Adversarial Coverage Hardening
- **T1-F28-01:** Challenger agent test harness injects malformed JSON payloads into all HTTP/WS endpoints.
- **T1-F28-02:** Concurrency fuzzer floods WebSocket bus with simultaneous messages to detect deadlocks.
- **T1-F28-03:** Memory exhaustion injection verifies engine fails gracefully without corrupting database.
- **T1-F28-04:** Path traversal fuzzer tests 100+ directory escape vectors against workspace endpoints.
- **T1-F28-05:** Verification confirms all adversarial inputs return controlled error codes (HTTP 4xx/5xx) with no crash.

### F29: Release Verification & Test Report
- **T1-F29-01:** Clean checkout of branch `feature/omni-ascension` installs all dependencies via `Pkg.instantiate()`.
- **T1-F29-02:** Engine boots cleanly via `julia --project=. sparkbyte.jl` without manual code edits.
- **T1-F29-03:** Production release checklist is fully satisfied and documented in `docs/RELEASE_NOTES.md`.
- **T1-F29-04:** Windows launch batch scripts start application cleanly on fresh Windows machine.
- **T1-F29-05:** Test reproducibility report documents operating system, Julia version, and commit SHA.

### F30: E2E Test Infrastructure & Suite Design
- **T1-F30-01:** `TEST_INFRA.md` defines complete 4-tier testing specification and execution semantics.
- **T1-F30-02:** Test runner `tests/e2e/runner.jl` supports CLI flags (`--tier`, `--format`, `--bail`).
- **T1-F30-03:** Test harness provides isolated temporary environments and cleanup guarantees.
- **T1-F30-04:** Test runner produces standard TAP v13 stream with YAML error diagnostics.
- **T1-F30-05:** Test runner exits with deterministic exit codes: 0 on pass, 1 on test failure, 2 on harness error.

---

## 4. TIER 2: BOUNDARY & CORNER CASES (BVA / STRESS)
*Requirement: Minimum 5 distinct boundary/corner-case test cases per feature (Total: 150 boundary tests).*

### F01-B: Git Baseline Boundaries
- **T2-F01-01:** Empty Git commit message or detached HEAD state handled gracefully by Git inspectors.
- **T2-F01-02:** Remote repository unreachable (network down) produces informative error without hanging CLI.
- **T2-F01-03:** Uncommitted dirty working tree state is reported accurately before branch switching.
- **T2-F01-04:** Branch name containing invalid characters or spaces is rejected with validation error.
- **T2-F01-05:** Large commit history (>10,000 commits) log query respects depth limits (`--depth=10`).

### F02-B: Port 8081 Alignment Boundaries
- **T2-F02-01:** Port number boundary: port `0` (dynamic port selection) handled correctly if configured.
- **T2-F02-02:** Port number boundary: port `65535` (maximum TCP port) binds successfully if free.
- **T2-F02-03:** Port number boundary: invalid port strings (`-1`, `80800`, `abc`) throw validation exception on load.
- **T2-F02-04:** Port already in use by external non-Julia process triggers clean port-in-use diagnostic.
- **T2-F02-05:** Binding to non-routable interface (`192.0.2.1`) fails with host-binding error without crashing engine.

### F03-B: Destructive Recovery Rejection Boundaries
- **T2-F03-01:** Corrupted SQLite file header triggers SQLite database recovery routine without file deletion.
- **T2-F03-02:** Zero-byte database file triggers table recreation without deleting existing metadata.
- **T2-F03-03:** Unwritable database directory produces descriptive permission error.
- **T2-F03-04:** Rapid start-kill-start cycles (SIGINT during boot) leave database WAL in consistent state.
- **T2-F03-05:** Simultaneous engine processes attempting to bind 8081 exit cleanly with lockfile notice.

### F04-B: Port Matrix Documentation Boundaries
- **T2-F04-01:** Malformed Markdown table in `PORT_MATRIX.md` is detected by documentation linter.
- **T2-F04-02:** Duplicate candidate IDs in `PORT_MATRIX.md` are flagged during matrix integrity check.
- **T2-F04-03:** Missing commit SHA in port entry triggers validation warning.
- **T2-F04-04:** Candidate referencing non-existent remote file is flagged during verification.
- **T2-F04-05:** Architecture baseline documents minimum supported Julia version (`>= 1.10`).

### F05-B: Reference Candidate Ports Boundaries
- **T2-F05-01:** `.env` containing empty lines, comments, and unquoted values parses without error.
- **T2-F05-02:** `.env` containing multiline values or escaped characters (`\n`, `\"`) preserves formatting.
- **T2-F05-03:** `health_check.jl` executed on empty directory returns zero false-positive errors.
- **T2-F05-04:** `health_check.jl` scanning file with 10,000 lines executes in under 2 seconds.
- **T2-F05-05:** Windows batch script executed from arbitrary working directory locates project root correctly.

### F06-B: OpenRouter Streaming Boundaries
- **T2-F06-01:** Empty prompt string (`""`) triggers HTTP 400 validation error before remote dispatch.
- **T2-F06-02:** Prompt exceeding model context limit (e.g. 1,000,000 characters) returns structured context error.
- **T2-F06-03:** Network socket disconnect mid-stream triggers stream retry or clean error callback.
- **T2-F06-04:** Upstream SSE stream sending malformed non-JSON data lines is ignored without terminating parser.
- **T2-F06-05:** Immediate client cancellation on first token disconnects upstream request within 50ms.

### F07-B: Model Catalog Discovery Boundaries
- **T2-F07-01:** OpenRouter API returning 500+ models parses without memory spike or truncation.
- **T2-F07-02:** Remote catalog endpoint returning HTTP 401 Unauthorized produces clean authentication error.
- **T2-F07-03:** Remote catalog endpoint timing out after 10 seconds falls back to cached models.
- **T2-F07-04:** Empty model list from upstream API raises `EmptyCatalogException`.
- **T2-F07-05:** Model with missing pricing or context fields sets safe defaults (`0` or `unknown`).

### F08-B: Multi-Provider Extensible Boundaries
- **T2-F08-01:** Registering duplicate provider ID overwrites or throws descriptive conflict warning.
- **T2-F08-02:** Invoking unregistered provider ID throws `UnknownProviderException` with available provider list.
- **T2-F08-03:** Custom HTTP backend configured with invalid URL scheme (`ftp://`) is rejected.
- **T2-F08-04:** Provider returning HTTP 429 Too Many Requests sets provider rate-limit status.
- **T2-F08-05:** Switching active provider under concurrent chat requests does not drop in-flight requests.

### F09-B: Fallback Provider Chain Boundaries
- **T2-F09-01:** Empty fallback chain (single provider) propagates original exception on failure.
- **T2-F09-02:** All providers in chain failing returns `AllProvidersFailedException` with aggregated error logs.
- **T2-F09-03:** Circular fallback reference (`A -> B -> A`) is detected and prevented.
- **T2-F09-04:** Fallback timeout set to 0 milliseconds immediately delegates to next provider.
- **T2-F09-05:** Transient failure with retry count = 3 retries with exponential backoff before fallback.

### F10-B: Typed Config Persistence Boundaries
- **T2-F10-01:** Setting config value with mismatched type (e.g. string for integer port) throws `TypeError`.
- **T2-F10-02:** SQLite database locked by concurrent write retries with busy-timeout.
- **T2-F10-03:** Massive configuration string (100KB) persists and retrieves without truncation.
- **T2-F10-04:** Special characters in config keys/values (quotes, null bytes, unicode emojis) preserve integrity.
- **T2-F10-05:** Config load on corrupted SQLite database falls back to `.env` and default struct values.

### F11-B: Secure Credential Storage Boundaries
- **T2-F11-01:** API key containing leading/trailing whitespace is trimmed before storage.
- **T2-F11-02:** Extremely long API key (4096 characters) is stored securely without buffer overflow.
- **T2-F11-03:** Setting empty string as API key clears active credentials and marks provider unconfigured.
- **T2-F11-04:** Logging exception containing API key in URL scrubs key before writing to disk.
- **T2-F11-05:** Memory inspection / dump of serializable config objects reveals masked string.

### F12-B: UI Navigation Boundaries
- **T2-F12-01:** Navigating to non-existent route `#unknown-view` defaults to Dashboard view.
- **T2-F12-02:** Rapid view switching (10 clicks per second) causes zero UI state synchronization crashes.
- **T2-F12-03:** Extremely small viewport (320px width) renders mobile navigation drawer cleanly.
- **T2-F12-04:** 4K ultra-wide viewport (3840px width) maintains bounded max-width content container.
- **T2-F12-05:** Keyboard navigation (Tab / Arrow keys) cycles through navigation links in logical order.

### F13-B: Authoritative Settings Boundaries
- **T2-F13-01:** Numeric setting input subjected to negative value rejects input with validation badge.
- **T2-F13-02:** Floating-point setting input subjected to NaN or Infinity is clamped to default.
- **T2-F13-03:** Rapid consecutive settings updates maintain sequential consistency in SQLite.
- **T2-F13-04:** Saving setting while backend server is offline displays visible offline error alert.
- **T2-F13-05:** Reset to defaults button restores initial values and updates both UI and Julia runtime.

### F14-B: Dynamic UI Model Selector Boundaries
- **T2-F14-01:** Model search query containing regex meta-characters (`.*+?^${}()|[]\`) does not crash filter.
- **T2-F14-02:** Search query matching zero models displays clean "No models found" state.
- **T2-F14-03:** Model catalog containing models with names exceeding 100 characters wraps or truncates cleanly.
- **T2-F14-04:** Dropdown keyboard navigation allows selecting models with Enter key.
- **T2-F14-05:** Switching models during active chat stream queues switch for subsequent turn.

### F15-B: Ported UI Panels Boundaries
- **T2-F15-01:** `mind-panel` handling graph with 500+ nodes renders with force-directed layout performance.
- **T2-F15-02:** `mission-panel` handling 50 nested subtasks renders scrollable tree without overflow.
- **T2-F15-03:** `terminal-panel` handling 10,000 lines of output applies circular buffer to prevent DOM bloat.
- **T2-F15-04:** Terminal ANSI parser handles complex 24-bit RGB escape sequences without breaking layout.
- **T2-F15-05:** `browser-center` handling invalid screenshot buffer displays placeholder icon.

### F16-B: Headless Control API Boundaries
- **T2-F16-01:** HTTP `POST /control/dispatch` with empty body returns HTTP 400 Bad Request.
- **T2-F16-02:** HTTP `POST /control/dispatch` with 10MB payload is rejected with HTTP 413 Payload Too Large.
- **T2-F16-03:** Request with unsupported `Content-Type: text/plain` returns HTTP 415.
- **T2-F16-04:** Concurrent requests to `/control/state` (100 simultaneous requests) complete within 500ms.
- **T2-F16-05:** Pre-flight HTTP `OPTIONS` requests receive valid CORS pre-flight response headers.

### F17-B: Multi-Agent Teamwork Task Board Boundaries
- **T2-F17-01:** Task title with 500 characters renders without overflowing board column.
- **T2-F17-02:** Dragging task into invalid column reverts to original column position.
- **T2-F17-03:** Scheduling 50 concurrent agent tasks queues excess tasks beyond worker pool limit.
- **T2-F17-04:** Worker agent encountering unhandled exception reports failure state without freezing board.
- **T2-F17-05:** Task cancellation issued to already completed task returns idempotent status.

### F18-B: Isolated Git Worktrees Boundaries
- **T2-F18-01:** Creating worktree with already existing branch name handles collision gracefully.
- **T2-F18-02:** Deleting worktree containing uncommitted modified files requires explicit force flag.
- **T2-F18-03:** Concurrent creation of 5 worktrees executes without Git index lock conflicts.
- **T2-F18-04:** Merge conflict between worktree and main branch marks task in `review_conflict` state.
- **T2-F18-05:** Disk full condition during worktree checkout aborts cleanly and rolls back worktree registration.

### F19-B: Reactive Agent Studio Boundaries
- **T2-F19-01:** Loading corrupted or non-JSON MPF file displays validation error message.
- **T2-F19-02:** Parameter slider set to extreme bounds (`0.0` or `1.0`) maintains stable cognitive calculations.
- **T2-F19-03:** Rapid slider dragging (50 events/second) throttles WebSocket updates to maintain UI responsiveness.
- **T2-F19-04:** Importing agent with missing required fields populates default profile values.
- **T2-F19-05:** Switching agents mid-turn applies new agent prompt cleanly on subsequent turn.

### F20-B: Persistent Memory Boundaries
- **T2-F20-01:** Memory search query containing SQL injection patterns (`' OR 1=1; --`) executes safely via parameterized query.
- **T2-F20-02:** Memory entry containing 1MB of text is stored and retrieved accurately.
- **T2-F20-03:** Searching with empty string returns most recent memories sorted by timestamp.
- **T2-F20-04:** Deleting non-existent memory ID returns false/error without throwing database exception.
- **T2-F20-05:** Database filled with 100,000 memory entries maintains search response under 150ms.

### F21-B: Dynamic Tool Forge Boundaries
- **T2-F21-01:** Dynamic tool definition with syntax error returns compilation error diagnostics.
- **T2-F21-02:** Tool attempting infinite recursion is caught and terminated by execution timeout.
- **T2-F21-03:** Tool attempting to redefine core Julia functions (`Base.+`, `eval`) is blocked by AST filter.
- **T2-F21-04:** Dynamic tool throwing runtime exception returns structured error dict to caller.
- **T2-F21-05:** Registering tool with existing name increments version number and updates registry.

### F22-B: Workspace Routing Boundaries
- **T2-F22-01:** Path traversal attempts (`../../Windows/System32`, `..\..\..\etc\passwd`) return 403 Forbidden.
- **T2-F22-02:** Opening file exceeding 10MB displays size warning and prompts for partial head/tail view.
- **T2-F22-03:** Opening non-existent file path returns HTTP 404 with structured error.
- **T2-F22-04:** Workspace folder containing 20,000 files lazy-loads directory tree without browser freeze.
- **T2-F22-05:** Read-only file modification attempt returns explicit write-permission error.

### F23-B: Terminal Host Execution Boundaries
- **T2-F23-01:** Executing command producing 100,000 lines of output buffers stream without memory exhaustion.
- **T2-F23-02:** Command attempting interactive prompt (waiting on stdin) times out cleanly after limit.
- **T2-F23-03:** Command returning non-zero exit code (e.g. `exit 42`) captures exact exit code in result.
- **T2-F23-04:** Command injection attempts (`echo test; rm -rf /`) undergo argument array isolation.
- **T2-F23-05:** Terminating a process tree cleanly kills all spawned child subprocesses.

### F24-B: Browser Automation Boundaries
- **T2-F24-01:** Navigating to unreachable domain (`http://nonexistent-domain-test.local`) times out gracefully.
- **T2-F24-02:** Page containing broken SSL certificates navigates if explicitly configured, else rejects.
- **T2-F24-03:** Screenshot capture on page with infinite height scroll clamps to maximum dimension.
- **T2-F24-04:** Closing browser session while page action is in-flight cleans up driver process.
- **T2-F24-05:** Scheduling job with invalid cron expression (`* * * * * * * *`) throws syntax validation error.

### F25-B: Subsystem Regression Boundaries
- **T2-F25-01:** Running test suite with zero test files discovered flags error rather than passing trivially.
- **T2-F25-02:** Interrupted test run (Ctrl+C) cleans up temporary test workspaces before exit.
- **T2-F25-03:** Running regression tests under constrained memory (512MB RAM) runs sequentially.
- **T2-F25-04:** Mock provider simulating 100% network packet loss triggers all fallback assertions.
- **T2-F25-05:** Static code scan flags deprecated Julia function usage across codebases.

### F26-B: Database Migration Boundaries
- **T2-F26-01:** Applying migration script that fails halfway rolls back transaction atomically.
- **T2-F26-02:** Running migrations when database is already at latest version is a clean no-op.
- **T2-F26-03:** Migration script executed out of version sequence throws sequencing error.
- **T2-F26-04:** Database migration on 50MB SQLite database executes in under 5 seconds.
- **T2-F26-05:** Downgrade migration restores exact previous schema and column definitions.

### F27-B: E2E Test Suite Boundaries
- **T2-F27-01:** E2E runner executed with `--filter` matching zero tests exits with status 0 and note.
- **T2-F27-02:** E2E runner executed with invalid flag `--invalid-arg` exits with status 2 and usage help.
- **T2-F27-03:** Single test failure when `--bail` is passed halts test suite immediately.
- **T2-F27-04:** Generating JUnit XML output to unwritable path reports error to stderr.
- **T2-F27-05:** Test suite execution with 300 tests tracks wall-clock time with sub-millisecond precision.

### F28-B: Adversarial Coverage Boundaries
- **T2-F28-01:** HTTP headers containing 64KB random bytes are rejected with 431 Request Header Fields Too Large.
- **T2-F28-02:** Malformed UTF-8 byte sequences in chat inputs are sanitized without crashing parser.
- **T2-F28-03:** Replaying expired authentication tokens receives 401 Unauthorized.
- **T2-F28-04:** Sending HTTP requests with HTTP/0.9 or invalid HTTP versions returns 400 or 505.
- **T2-F28-05:** Multiple parallel WebSocket connections (50 concurrent) open and close cleanly.

### F29-B: Release Verification Boundaries
- **T2-F29-01:** Packaging script executed with missing required files halts with checklist deficit report.
- **T2-F29-02:** Environment check flags missing Python executable if `JULIA_PYTHONCALL_EXE` is invalid.
- **T2-F29-03:** Release archive integrity verified via SHA-256 checksum comparison.
- **T2-F29-04:** Running release on path containing spaces (`C:\Program Files\SparkByte Omni`) boots cleanly.
- **T2-F29-05:** Windows batch scripts handle non-standard CMD/PowerShell environments.

### F30-B: Test Infrastructure Boundaries
- **T2-F30-01:** TAP reporter handles test names with special characters (`#`, `-`, quotes, newlines).
- **T2-F30-02:** JUnit reporter escapes XML special characters (`<`, `>`, `&`, `"`, `'`) in failure logs.
- **T2-F30-03:** Test assertions with deeply nested data structures format YAML diagnostics cleanly.
- **T2-F30-04:** Test runner isolates standard output of test under test from TAP protocol stream.
- **T2-F30-05:** Harness timeout monitors individual test execution and terminates hung tests after 60s.

---

## 5. TIER 3: CROSS-FEATURE PAIRWISE COMBINATIONS
*Requirement: Multi-feature interaction tests covering coupled subsystems and edge interactions.*

| Test ID | Features Coupled | Interaction Objective & Verification Assertion |
|---------|------------------|------------------------------------------------|
| **T3-COMB-01** | F06 + F09 | **Streaming + Fallback Cascade:** When primary OpenRouter streaming encounters mid-stream socket drop, fallback provider chain engages secondary provider without corrupting conversation history. |
| **T3-COMB-02** | F10 + F16 | **Config Persistence + Headless API:** Modifying configuration via `POST /control/dispatch` updates `EngineConfig`, persists to SQLite, and immediately reflects in `GET /control/state`. |
| **T3-COMB-03** | F17 + F18 | **Teamwork Tasks + Isolated Worktrees:** Multiple concurrent tasks on Task Board spawn independent Git worktrees; concurrent file writes do not cause Git index locks or merge collisions. |
| **T3-COMB-04** | F20 + F21 | **Persistent Memory + Dynamic Tool Forge:** Dynamically forged tool stores execution history in persistent SQLite memory; subsequent agent turns retrieve tool results from memory. |
| **T3-COMB-05** | F02 + F03 | **Port Binding + Non-Destructive Recovery:** Simulating an engine restart while port 8081 has active TCP connections verifies socket graceful reuse without invoking destructive process kills. |
| **T3-COMB-06** | F11 + F25 | **Credential Sanitization + Regression Testing:** Full test suite execution produces zero unmasked API keys across logs, test reports, and SQLite test artifacts. |
| **T3-COMB-07** | F19 + F21 | **Agent Lattice + Dynamic Tools:** Agent cognitive drift triggers dynamic tool synthesis based on behavioral aperture; newly synthesized tool executes with `Base.invokelatest`. |
| **T3-COMB-08** | F22 + F23 | **Workspace Boundaries + Host Execution:** Sandboxed terminal commands enforce workspace root boundaries; attempts to execute commands targeting parent paths are denied. |
| **T3-COMB-09** | F03 + F26 | **Non-Destructive Recovery + DB Migration:** Applying forward SQLite migrations during simulated crash recovery relies on native WAL checkpointing without deleting `-wal` files. |
| **T3-COMB-10** | F17 + F24 | **Teamwork Task Board + Browser Automation:** Agent on task board executes Playwright browser task, captures page screenshot, attaches screenshot to task card, and requests review. |
| **T3-COMB-11** | F07 + F14 | **Model Catalog Discovery + UI Model Selector:** Triggering `POST /api/models/refresh` updates SQLite catalog and pushes WebSocket `catalog_updated` event, refreshing UI dropdown. |
| **T3-COMB-12** | F13 + F15 | **Settings Screens + Ported UI Panels:** Toggling developer telemetry in Settings screen immediately updates real-time metrics displayed in `mind-panel` and `terminal-panel`. |
| **T3-COMB-13** | F05 + F10 | **Early Env Loader + Config Persistence:** Overriding config via `.env` initializes `EngineConfig` on boot; subsequent UI config change persists to SQLite and takes precedence. |
| **T3-COMB-14** | F21 + F23 | **Tool Forge + Approval Gates:** Dynamic tool requesting shell execution prompts approval gate; upon approval, executes and logs stdout to memory and terminal panel. |
| **T3-COMB-15** | F18 + F29 | **Git Worktrees + Release Verification:** Release verification script cleans all stale agent worktrees and validates that release branch is clean and reproducible. |

---

## 6. TIER 4: REAL-WORLD APPLICATION SCENARIOS
*Requirement: Minimum 5 end-to-end realistic workloads.*

### Scenario 1: Autonomous Full-Stack Development Workload (`T4-SCEN-01`)
1. **User Action:** User creates a new task on Teamwork Task Board: "Build a CSV analysis tool and generate summary report."
2. **Agent Dispatch:** Orchestrator assigns task to Specialist Agent in an isolated Git worktree.
3. **Tool Forging:** Specialist agent uses Dynamic Tool Forge to synthesize a Julia CSV aggregation function. AST validator checks code safety; tool is registered in SQLite with `Base.invokelatest` dispatch.
4. **Execution & Memory:** Tool executes against sample data in workspace; results are committed to persistent memory and SQLite database.
5. **Review Gate:** Specialist agent files pull request on worktree branch; Reviewer agent runs automated tests, approves merge, and marks task `done` on the UI Task Board.

### Scenario 2: Multi-Agent Collaborative Refactoring with Concurrent Worktrees (`T4-SCEN-02`)
1. **Concurrent Dispatch:** Master Orchestrator spawns two subagents simultaneously: Agent A (refactoring `Config.jl`) and Agent B (updating `Backends.jl`).
2. **Worktree Isolation:** Agent A works in `.worktrees/agent-config`; Agent B works in `.worktrees/agent-backends`.
3. **Execution & Commits:** Both agents independently make commits and run unit tests.
4. **Review & Merge:** Orchestrator initiates sequential merge validation; Agent A merges cleanly; Agent B's branch detects no conflicts, runs regression tests, and merges into `feature/omni-ascension`.
5. **Teardown:** Both worktrees are pruned cleanly without leaving orphaned Git locks.

### Scenario 3: High-Resilience Model Failover & Live Provider Discovery Under Rate Limiting (`T4-SCEN-03`)
1. **Initial State:** Primary backend configured as OpenRouter with model `deepseek/deepseek-v4-flash`.
2. **Fault Injection:** Test harness intercepts OpenRouter endpoint and injects HTTP 429 (Rate Limit Exceeded).
3. **Circuit Breaker:** Engine circuit breaker detects 429, increments failure count, trips breaker, and switches to secondary provider (Ollama / Gemini).
4. **Streaming Continuity:** Client chat session receives notification of provider failover and seamlessly streams completion from fallback provider.
5. **Auto-Recovery:** After cooldown window expires, circuit breaker transitions to half-open, probes primary provider with canary request, and resumes primary routing upon success.

### Scenario 4: Dynamic Tool Lifecycle: Forge, Synthesize, Test, Audit, Invokelatest Dispatch, and Rollback (`T4-SCEN-04`)
1. **Tool Creation:** Dynamic Tool Forge receives request to build `calculate_portfolio_risk(weights, returns)`.
2. **Static AST Analysis:** Tool Forge verifies AST, ensuring no forbidden primitives (`ccall`, `eval`, `run`).
3. **Dynamic Compilation:** Code compiled into runtime module; registered with metadata, schema, and version `1.0.0`.
4. **Execution & Verification:** Tool is invoked via `POST /control/dispatch` using `Base.invokelatest`; produces correct statistical output.
5. **Fault Injection & Rollback:** Version `1.1.0` is registered with injected bug (division by zero); execution test fails; automated rollback restores version `1.0.0` and logs incident to diagnostics.

### Scenario 5: Enterprise Security, Audit Trail, and Crash Recovery with Persistent State Integrity (`T4-SCEN-05`)
1. **Operations:** User performs settings updates, agent dispatches, and memory storage operations over 15 minutes of simulated activity.
2. **Audit Verification:** Audit log confirms zero unmasked API keys or secrets in logs, WebSocket messages, or telemetry.
3. **Hard Crash Simulation:** Test harness simulates abrupt process termination (kill without clean shutdown) while SQLite has active WAL transactions.
4. **Cold Boot & Recovery:** Engine restarts on port 8081; executes early `.env` loader, health check scanner, and opens SQLite database.
5. **Integrity Assertion:** Database runs SQLite native WAL checkpoint; zero data loss; `PRAGMA integrity_check` returns `ok`; engine resumes normal HTTP/WS operation on port 8081.

---

## 7. TEST RUNNER SPECIFICATIONS & PASS/FAIL SEMANTICS

### 7.1 Test Runner CLI Command
```bash
julia --project=. tests/e2e/runner.jl [options]
```

### 7.2 CLI Options and Flags
- `--tier=<1|2|3|4|all>`: Run specific test tier (default: `1`).
- `--feature=<F01..F30|all>`: Run tests for a specific feature (default: `all`).
- `--format=<tap|junit|summary>`: Output format (default: `tap`).
- `--out=<filepath>`: Write structured test output to specified file.
- `--bail`: Stop test execution immediately upon first failure.
- `--help`: Display usage and argument instructions.

### 7.3 Structured Output Formats
1. **TAP v13 (Test Anything Protocol):**
   ```tap
   TAP version 13
   1..5
   ok 1 - T1-F01-01: Git repository tracking remote
   ok 2 - T1-F01-02: Branch alignment on feature/omni-ascension
   ok 3 - T1-F01-03: Baseline commit history verification
   ok 4 - T1-F01-04: Gitignore excludes sensitive artifacts
   ok 5 - T1-F01-05: Reference remotes queryable
   # tests 5
   # pass 5
   # fail 0
   ```
2. **JUnit XML (`junit.xml`):**
   Standard XML format compatible with CI systems, recording test suites, test cases, execution durations, and `<failure>` blocks containing stack traces and assertions.

### 7.4 Pass/Fail Semantics & Exit Codes
- **Exit Code 0:** All executed tests passed (100% pass rate).
- **Exit Code 1:** One or more tests failed.
- **Exit Code 2:** Test harness configuration or fatal setup error.

### 7.5 Progressive Testability Matrix
During Wave-by-Wave execution, tests are gated based on milestone deliverables:
- **Milestone 0 (Wave 0):** F01, F02, F03, F04, F05, F30.
- **Milestone 1 (Wave 1):** F06, F07, F08, F09, F10, F11.
- **Milestone 2 (Wave 2):** F12, F13, F14, F15, F16.
- **Milestone 3 (Waves 3-5):** F17, F18, F19, F20, F21, F22, F23, F24.
- **Milestone 4 (Wave 6):** F25, F26, F27, F28, F29 (Full 100% Release Pass).

---

## 8. CODE LAYOUT FOR `tests/e2e/`

```
tests/e2e/
├── runner.jl                       # Main E2E CLI Test Runner
├── framework/
│   ├── TestHarness.jl              # Core test harness, isolation & assertion macros
│   └── TAPReporter.jl              # TAP v13 and JUnit XML emitters
├── tier1_baseline/                 # M0/Wave 0 baseline verification tests
│   ├── test_f01_git_baseline.jl
│   ├── test_f02_port_binding.jl
│   ├── test_f03_destructive_rejection.jl
│   ├── test_f04_port_matrix.jl
│   ├── test_f05_reference_ports.jl
│   └── test_f30_infra_design.jl
├── tier1_features/                 # Comprehensive Tier 1 test suites (F01..F30)
├── tier2_boundaries/               # Tier 2 boundary and corner case test suites
├── tier3_combinations/             # Tier 3 pairwise interaction test suites
├── tier4_scenarios/                # Tier 4 real-world workload scenarios
└── fixtures/                       # Test data, sample configs, mock payloads
```

---

## 9. ADVERSARIAL VERIFICATION & TIER 5 GUIDELINES
When the implementation reaches Wave 6, Challenger agents will leverage this infrastructure to execute white-box adversarial stress testing:
1. **Encoding & Escaping Integrity:** Injection of control characters, null bytes, bidirectional overrides, and format meta-characters across all input and output channels.
2. **Invalid Input Combinations:** Combinations of valid and invalid parameters to ensure deterministic error cascades without partial state mutations.
3. **Resource Starvation & Partitioning:** Disk full, port exhaustion, and CPU starvation simulations verifying bounded degradation and recovery.

---
*End of TEST_INFRA.md*
