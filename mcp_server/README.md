# SparkByte MCP Server

Exposes the JL-Engine / SparkByte runtime to stdio-capable [Model Context Protocol](https://modelcontextprotocol.io) clients (Claude Desktop, Claude Code, Cursor, Zed, VS Code Copilot).

Server name: **`sparkbyte`** (also registered as `JL-SB-Omni` in some configs).

---

## What it gives you

Three integration paths into the engine:

1. **Database query tools** — query `sparkbyte_memory.db` and the embedded Julian quarry (`quarry.db`); these tools do not modify database rows.
2. **Runtime tools** — `run_turn` sends a task to the A2A endpoint.
3. **Hardware tools** — Ruida serial status and job upload; `ruida_send_job` does not start a job unless `auto_start=true` is explicitly supplied.

### Tool catalog

| Tool | Path | Description |
|---|---|---|
| `get_engine_state` | DB | Latest `turn_snapshots` row |
| `get_thoughts(limit=10, thought_type="diary")` | DB | Recent thoughts |
| `get_telemetry(limit=20)` / `get_recent_telemetry(limit=20)` | DB | Recent telemetry events |
| `query_memory(tag="", key="", limit=20)` | DB | Filter memory rows by tag/key |
| `get_knowledge(domain="", limit=20)` | DB | Query indexed knowledge |
| `list_agents` | DB | Registered agents |
| `list_forged_tools` | DB | Forged tools recorded in `tools` table |
| `list_forged_tools_registry` | FS | Dump `dynamic_tools_registry.json` (Julia runtime tools) |
| `search_julian_quarry(query, limit=10)` | DB | Full-text-ish scan of the code quarry |
| `run_turn(message)` | A2A | Execute a turn on the running engine |
| `ruida_status(port="COM3")` | Serial | Check Ruida controller status |
| `ruida_send_job(...)` | Serial | Upload a job; pass `auto_start=true` to start cutting immediately |

---

## Install / run

### Requirements
- Python 3.10+
- Install pinned deps: `pip install -r mcp_server/requirements.txt`
  (install the pinned package set from the requirements file)
- SparkByte SQLite database (read-only access for query tools)
- (Optional, for runtime turns) SparkByte A2A server running on `127.0.0.1:8082`
- (Optional, for hardware tools) Ruida controller and `pyserial`

### Run modes

```bash
# stdio transport used by MCP clients
python mcp_server/server.py
```

The current `server.py` entry point supports stdio only.

### Current runtime configuration

`server.py` reads `SPARKBYTE_STATE_DIR`, `JULIAN_DB`, and `JULIAN_SKILL`.
`run_turn` also reads `A2A_API_KEY` and forwards it to the local A2A service.
The following settings are historical and are not supported by the current stdio entry point:

| Var | Default | Purpose |
|---|---|---|
| `SPARKBYTE_STATE_DIR` | `<repo>/data` | SparkByte SQLite location |
| `A2A_API_KEY` | _(unset)_ | Optional bearer key for local A2A `run_turn` requests |
| `JULIAN_DB` | Embedded Julian quarry path | Path to quarry |
| `JULIAN_SKILL` | `~/.claude/skills/julian/SKILL.md` | Optional skill resource path |

### Historical settings (unsupported by current server.py)

| Var | Default | Purpose |
|---|---|---|
| `MCP_TRANSPORT` | `stdio` | Legacy transport selector |
| `MCP_PORT` | `8083` | Port for SSE mode |
| `MCP_BIND` | `127.0.0.1` | Bind address. Non-loopback requires the ack + auth (see Security) |
| `MCP_BIND_ACK` | _(unset)_ | Set to `I_understand_no_builtin_auth` to allow non-loopback bind |
| `MCP_AUTH_TOKEN` | _(unset)_ | Bearer token required for non-loopback HTTP/SSE (≥16 chars) |
| `MCP_WS_CONCURRENCY` | `4` | Max in-flight WS round-trips |
| `MCP_ALLOW_EXTERNAL_PATHS` | `0` | `1` skips path-sandbox check on JULIAN_DB / JULIAN_SKILL |
| `MCP_ALLOW_REMOTE_WS` | `0` | `1` allows non-loopback `SPARKBYTE_WS` |
| `MCP_LOG_LEVEL` | `INFO` | stderr log level (DEBUG/INFO/WARNING/ERROR) |
| `SPARKBYTE_WS` | `ws://127.0.0.1:8081` | Where the live engine is listening |
| `SPARKBYTE_WS_TIMEOUT` | `60` | Seconds to wait for a `spark` reply |
| `MCP_MAX_RESPONSE_BYTES` | `60000` | Cap for `query_memory` / `list_forged_tools_registry` output |
| `JULIAN_DB` | `JulianMetaMorph/JulianMetaMorph/data/quarry.db` | Path to quarry |
| `JULIAN_SKILL` | `~/.claude/skills/julian/SKILL.md` | Julian skill markdown |

---

## Client setup

### Install sweep

SparkByte can audit common local clients and editors, then offer to hook herself
up as their `sparkbyte` MCP server. The sweep lives inside the engine as the
native Julia tool `mcp_client_hooks` (see `BYTE/src/Tools.jl :: tool_mcp_client_hooks`).

From a SparkByte session, invoke it as a tool call:

```json
{ "tool": "mcp_client_hooks", "args": { "action": "scan" } }
```

To write supported JSON MCP configs, use the `apply` action:

```json
{ "tool": "mcp_client_hooks", "args": { "action": "apply" } }
{ "tool": "mcp_client_hooks", "args": { "action": "apply", "target": "repo_claude_code" } }
```

The sweep is read-only by default. Apply mode backs up existing JSON config files
before updating their `mcpServers.sparkbyte` entry.

### Claude Desktop (`%APPDATA%\Claude\claude_desktop_config.json`)

```json
{
  "mcpServers": {
    "sparkbyte": {
      "command": "python",
      "args": [
        "C:\\Users\\J_lin\\Desktop\\jl-engine-reboot-reboot\\JL_Engine-SB.Omni\\mcp_server\\server.py"
      ]
    }
  }
}
```

Restart Claude Desktop to pick up changes.

### Claude Code

Either reuse the Claude Desktop entry above, or add a project-scoped `.mcp.json` at the repo root:

```json
{
  "mcpServers": {
    "sparkbyte": {
      "command": "python",
      "args": ["mcp_server/server.py"]
    }
  }
}
```

### Cursor / Zed / VS Code Copilot

Same shape — point at `python mcp_server/server.py` (stdio).

---

## Runtime and hardware actions

`run_turn(message)` sends an A2A task to the local SparkByte endpoint. When A2A
authentication is enabled, pass the same `A2A_API_KEY` to the MCP process environment.

`ruida_send_job` sends a job to the connected laser controller even when
`auto_start=false`; that default prevents immediate cutting, but does not make the
upload a dry run. Set `auto_start=true` only when immediate cutting is intended.

---

## Architecture

```
┌──────────────────┐       stdio           ┌────────────────────────┐
│  MCP client      │◄────────────────────►│  mcp_server/server.py  │
│  (Claude/Cursor) │                       │  (FastMCP, this file)  │
└──────────────────┘                       └──────┬─────────┬───────┘
                                                  │         │
                                         SQLite   │         │ A2A :8082
                                                  ▼         ▼
                                  sparkbyte_memory.db   SparkByte engine
                                  quarry.db              (Julia + Python)
```

- Database tools return JSON strings. `run_turn` invokes the local A2A endpoint.
- Ruida tools send serial data to physical hardware.

---

## Legacy HTTP security reference

The current `server.py` entry point is stdio-only and does not implement these HTTP
settings or transports. Treat the following historical guidance as unsupported.

Default posture is **localhost-only, no auth**. To expose this server beyond your machine:

1. Set `MCP_BIND=0.0.0.0` (or a specific NIC IP).
2. Set `MCP_BIND_ACK=I_understand_no_builtin_auth` — the server refuses to start otherwise.
3. Set `MCP_AUTH_TOKEN` to a random ≥16-char string. Clients must send `Authorization: Bearer <token>`.
4. Install `uvicorn` (already in `requirements.txt`) — needed when auth is on.
5. **Front it with TLS** (Caddy, nginx, Cloudflare). The bundled auth is a Bearer check, not transport security.

## Known limitations

- Ruida job upload is not a dry run. `auto_start` defaults to false, but uploading a job still sends it to the connected controller.
- `run_turn` targets `http://127.0.0.1:8082` and waits up to 120 seconds.

---

## Safety tests

```bash
python -m pytest mcp_server/test_ruida_safety.py -q
```

---

## Verifying after a config change

After editing `server.py`, restart the MCP client and confirm its tool list contains
the database queries, `run_turn`, and Ruida tools. The Ruida tests mock serial I/O
and never connect to hardware.
