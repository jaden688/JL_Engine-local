# SparkByte Docker & ops

## Quick start

1. Copy env template: **`cp .env.example .env`** (or copy on Windows) and add API keys you use.
2. **Compose:** `docker compose up --build`
3. **Smoke test** (host, with stack running): `powershell -File scripts/smoke_endpoints.ps1`

| Surface | URL |
|--------|-----|
| SparkByte UI / WebSocket | `http://localhost:${SPARKBYTE_PUBLIC_PORT:-8081}` |
| SparkByte health | `GET http://localhost:8081/health` |
| **A2A** (agent card + JSON-RPC) | `http://localhost:${A2A_PUBLIC_PORT:-8082}` |
| A2A health | `GET http://localhost:8082/health` |
| Agent card | `GET http://localhost:8082/.well-known/agent.json` |

## Build

```bash
docker build -t sparkbyte .
```

## Run (single container)

```bash
docker run --rm -it -p 8081:8081 -p 8082:8082 --env-file .env \
  -e SPARKBYTE_STATE_DIR=/app/runtime \
  -v sparkbyte-state:/app/runtime \
  sparkbyte
```

- Map **both** ports if you use **A2A** (`8082` inside the image).
- Browser auto-launch is disabled in Docker; the app still starts **headless Chromium** for `browse_url` where configured.

### Host Ollama

```bash
docker run --rm -it -p 8081:8081 -p 8082:8082 --env-file .env \
  --add-host=host.docker.internal:host-gateway \
  -e SPARKBYTE_STATE_DIR=/app/runtime \
  -e OLLAMA_BASE_URL=http://host.docker.internal:11434 \
  -v sparkbyte-state:/app/runtime \
  sparkbyte
```

## Compose

```bash
docker compose up --build
```

`compose.yaml` loads `.env`, maps **8081** (SparkByte) and **8082** (A2A), and persists state in volume `sparkbyte-state` → `/app/runtime`.

## A2A (production notes)

- Docker Compose binds A2A and SparkByte to all interfaces. Set a strong **`A2A_API_KEY`** in `.env` before starting Compose; Compose requires this key. Clients send `Authorization: Bearer <key>`.
- Local development can leave A2A keys unset only while both listeners remain bound to loopback (`127.0.0.1` / `::1`).
- Set **`A2A_PUBLIC_URL`** to the **external** base URL (e.g. `https://agent.example.com`) so `/.well-known/agent.json` advertises the correct endpoint behind a reverse proxy.
- JSON-RPC: **`POST /`** with methods such as `tasks/send` / `tasks/get` (see `a2a_server.jl`).

## Julian bridge (optional)

If **`JulianMetaMorph/JulianMetaMorph`** exists in the repo (copied into the image), SparkByte sets **`JULIAN_ROOT`** / **`JULIAN_DB`** at boot when unset. For **autonomous curiosity hunts**, set **`JULIAN_AUTONOMOUS_SECONDS`** (e.g. `3600`); `0` = off.

- **`GITHUB_TOKEN`** in `.env` improves GitHub rate limits for Julian hunts.
- **MCP** (`mcp_server/server.py`): defaults **`JULIAN_DB`** to `JulianMetaMorph/JulianMetaMorph/data/quarry.db` under the project root unless **`JULIAN_DB`** is set.

## Environment reference

See **`.env.example`** for all variables (SparkByte, A2A, Julian, LLM keys, Ollama).

## Notes

- Multi-stage **Dockerfile** caches Julia precompile; runtime exposes **8081** and **8082**.
- `run_command` uses PowerShell on Windows and POSIX shell on Linux (including the container).
- Runtime state: **`SPARKBYTE_STATE_DIR`** (default `/app/runtime` in Compose) holds SQLite, telemetry, forged tools, etc.
