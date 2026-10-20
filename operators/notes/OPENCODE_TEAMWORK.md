# OpenCode Teamwork for SparkByte Omni

## How it fits

OpenCode provides the lead and parallel subagent sessions. The configured
`sparkbyte-teamwork` MCP server stores team membership, tasks, path claims, and
direct messages in `.opencode/teamwork.sqlite3`. Its `sparkbyte_runtime_state`
tool reads SparkByte's existing `GET /control/state` endpoint. The engine's
Julia behavioral pipeline and local tool dispatcher remain the source of truth;
the teamwork service does not dispatch or execute SparkByte tools. OpenCode also
connects to SparkByte's existing MCP bridge with a small read-only tool allowlist;
`run_turn` is disabled in OpenCode to avoid nesting another model/tool loop.

OpenCode Task subagents share the project checkout. To avoid concurrent edits,
the configured team lead cannot use shell or edit tools, and both workers have
file editing, shell, and nested task tools disabled. For any future write task,
the MCP board also rejects overlapping write-path claims, including parent and
child paths. A path claim is a coordination guard; keep OpenCode edit
permissions restricted to the named owner as well.

## Startup

1. From the repository root, start SparkByte in one PowerShell window:

   ```powershell
   julia --project=. sparkbyte.jl
   ```

2. Ensure OpenCode can use a valid OpenRouter credential. It can use OpenCode's
   stored provider credential, or inherit the project credential in a single
   PowerShell process without putting it in OpenCode config:

   ```powershell
   $keyLine = Get-Content .env | Where-Object { $_ -match '^OPENROUTER_API_KEY=' } | Select-Object -First 1
   if (-not $keyLine) { throw 'OPENROUTER_API_KEY is missing from .env' }
   $env:OPENROUTER_API_KEY = ($keyLine -replace '^OPENROUTER_API_KEY=', '').Trim('"', "'")
   .\operators\scripts\start-opencode-omo.ps1 --agent team-lead
   ```

   This selects the team lead for this OpenCode session without changing your
   default agent for ordinary sessions. OpenCode launches
   `python mcp_server/teamwork_server.py` over stdio from the project config.
   For one-shot execution use
   `.\operators\scripts\start-opencode-omo.ps1 run --agent team-lead "<task>"`.

3. The MCP runtime-state tool defaults to `http://127.0.0.1:8081/control/state`.
   If SparkByte uses another port, set `SPARKBYTE_CONTROL_URL` in OpenCode's
   process environment, for example
   `http://127.0.0.1:18081/control/state`.

## Oh My OpenAgent Team Mode

OMO Team Mode is a separate coordination layer from the SparkByte teamwork MCP
board above. The project declares six specialists in
`.omo/teams/sparkbyte-omni/`; the current Sisyphus session is the seventh team
member and lead. Use Sisyphus because OMO's team runtime only accepts its
eligible lead agents. Its project prompt append makes it responsible for
delegation, disjoint file ownership, message coordination, and evidence-based
completion. The project-specific `team-lead` remains available for the
SparkByte MCP workflow described above.

From the repository root, after setting the OpenRouter credential as described
in Startup, launch:

```powershell
.\operators\scripts\start-opencode-omo.ps1 --agent sisyphus
```

Then ask Sisyphus to use Team Mode and the named `sparkbyte-omni` team for the
task. OMO Team Mode provides the shared task board, direct team messaging,
member delegation, parallel member sessions, and live task/member status
through its `team_*` tools. These capabilities are enabled together by
`[opencode].team_mode.enabled`; the installed version has no separate switches
for tasks, messages, delegation, or progress tracking. Sisyphus is instructed
to create shared tasks, assign owners and disjoint scopes, start independent
tasks concurrently, send messages for coordination, update task states, and
check the task list and team status before reporting or closing a run.

The role-to-model routes are editable in `.omo/omo.jsonc`: change the `model`
field on `agents.sisyphus` for the lead or on the matching `categories` entry
for a worker. The current budget routing uses DeepSeek V3.2 for orchestration
and broader code/integration work, and Qwen3.5 Flash for focused specialist
work.

| Role | Category | OpenRouter model | Focus |
|---|---|---|---|
| Lead | OMO Sisyphus | `deepseek/deepseek-v3.2` | Delegate, coordinate file ownership, collect evidence, report verified outcomes |
| Architect | `sparkbyte-architect` | `deepseek/deepseek-v3.2` | Engine architecture, contracts, dependency impact |
| Runtime | `sparkbyte-runtime` | `deepseek/deepseek-v3.2` | Julia/BYTE lifecycle, runtime and MCP/API behavior |
| Behavior | `sparkbyte-behavior` | `qwen/qwen3.5-flash-02-23` | SignalScorer, behavior, drift, rhythm, aperture |
| Telemetry | `sparkbyte-telemetry` | `qwen/qwen3.5-flash-02-23` | Telemetry, snapshots, persistence, diagnostics and broadcasts |
| Integration | `sparkbyte-integration` | `deepseek/deepseek-v3.2` | SparkByte, OpenCode, MCP and API boundaries |
| QA | `sparkbyte-qa` | `qwen/qwen3.5-flash-02-23` | Assigned-scope verification, failure paths and regressions |

At the listed OpenRouter rates checked 2026-10-15, DeepSeek V3.2 is
$0.2088/M input and $0.3096/M output; Qwen3.5 Flash is $0.065/M input and
$0.26/M output. The previous lead model, Claude Opus 5.5, is $4/M input and
$20/M output. Prices can change, and actual spend depends on token volume and
provider routing.

The project config caps a run at 7 active members (six workers plus lead), 500
messages, 60 minutes, and 80 turns per member. tmux visualization is off, so
tmux is not required. Agents are instructed to avoid duplicate tool loops,
report actual evidence, and coordinate before overlapping file edits.

The model and Team Mode settings are in `.omo/omo.jsonc`; the worker roles,
category assignments, and prompts are in `.omo/teams/sparkbyte-omni/config.json`.

## OpenCode V2 compatibility

The installed Oh My OpenAgent 5.1.33 plugin uses OpenCode's V1 plugin API.
OpenCode 2.x rejects that plugin API at server startup with a missing
`id`/`effect`/`setup` error. To preserve OMO Team Mode without breaking the
OpenCode 2.x install, OpenCode 1.19.0 is installed side-by-side under
`%LOCALAPPDATA%\OpenCodeV1`. Use the launcher above for OMO sessions. It sets
`OPENCODE_CONFIG` to `%USERPROFILE%\.config\opencode\opencode-omo-v1.jsonc`,
which enables OMO only in that V1 process, and uses port 4097 to avoid the V2
server's default port.

OMO has been removed from the global OpenCode V2 server and CLI plugin lists,
so V2 can run without attempting to load the incompatible plugin. Restart an
already-running V2 process once for the changed plugin list to take effect.
The V1 and V2 global config files were backed up beside the originals with a
`.bak-<timestamp>` suffix.

## Limits and recovery

- Lead: at most 8 model steps; workers: at most 5 steps each. Subagent nesting
  is disabled, and the lead may invoke only `team-researcher` and
  `team-verifier`.
- Each team accepts at most 8 tasks (the configured test uses 4); at most 3
  tasks can run concurrently within one team. Duplicate task titles are
  rejected, as are duplicate claims and messages after the 40-message cap.
- Task instructions and results are capped at 3,000 characters. A team can send
  at most 40 messages. SparkByte state reads have a 3-second timeout and a
  64-KiB response cap.
- Active write-path claims are checked across all teams, not just the current
  team. Ancestor/descendant paths overlap; `..` path segments are rejected.
- Verified safeguards: duplicate task titles and claims, path traversal,
  overlapping parent/child write claims across teams, and claim reuse after a
  task has started are rejected; finishing/failing releases the path claim.
- Failed workers should report once and call `team_fail`, which releases their
  file claims. Tasks remain in the local SQLite audit history. The DB and WAL
  files are ignored by Git.

## Verified run

OpenCode 1.19.0 with `openrouter/~openai/gpt-luna-latest` ran a real team against
the live SparkByte API on 2026-10-15. Team ID:
`5a04fa6c-cd60-46e9-9b29-7b9173d1a8e6`.

| Worker | Task | Result |
|---|---|---|
| researcher | `6535dc76-b14d-49d2-a36d-7cf1742cb80f` | `done`; MCP read returned `sparkbyte-omni`, `ok: true`, port `18081` |
| verifier | `9f704144-2727-4ec8-9ff4-588d0d3a8085` | `done`; independently read `AGENTS.md` startup commands |

Both workers sent a persistent message to `lead`. Their recorded execution
intervals overlapped: researcher `1792046623.613773`–`1792046630.7717848`,
verifier `1792046625.054755`–`1792046633.4667492` (about 5.72 seconds).
The lead queried the final team status and reported both tasks and messages.

## Configuration files

- `opencode.json` — lead permissions, subagent depth, both local
  MCP server launches, and the SparkByte MCP read-only tool allowlist.
- `.opencode/agents/team-lead.md` — bounded orchestrator instructions.
- `.opencode/agents/team-researcher.md` and `team-verifier.md` — read-only
  workers.
- `mcp_server/teamwork_server.py` — persistent team/task/message MCP tools and
  SparkByte state API adapter.
