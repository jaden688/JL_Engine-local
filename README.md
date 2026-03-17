# JL Engine Local

![Version](https://img.shields.io/badge/version-1.0.0-blue)
![Python](https://img.shields.io/badge/python-3.10%2B-blue)
![License](https://img.shields.io/badge/license-PolyForm%20Noncommercial-lightgrey)
![Platform](https://img.shields.io/badge/platform-Windows%20%7C%20macOS%20%7C%20Linux-informational)

JL Engine Local is the local-first JL Engine runtime and UI stack. The engine is the product surface, and `SparkByte` is the default active fat-agent voice loaded on top of it.

This repository is source-available under the non-commercial license in `LICENSE.md`. It is not an OSI open-source license.

> **New here?** Start with [`ONBOARDING.md`](ONBOARDING.md) for a step-by-step first-run guide, then return here for a reference overview.

## Table of contents

- [Features](#features)
- [What ships here](#what-ships-here)
- [Quick start](#quick-start)
- [Available agents](#available-agents)
- [Backend providers](#backend-providers)
- [Environment variables](#environment-variables)
- [Runtime layout](#runtime-layout)
- [Fat agents and modular agents](#fat-agents-and-modular-agents)
- [API surfaces](#api-surfaces)
- [Project layout](#project-layout)
- [Verification](#verification)
- [More docs](#more-docs)
- [License](#license)

## Features

- **Fat-agent runtime** — full persona capsules with behavior rules, memory, cognitive gears, and backend routing loaded per session
- **Modular agents** — composable shells that expand at load time into a resolved persona payload
- **Quest sessions** — structured request flow through `FatQuestRuntime` → `JLEngineCore` → `InterpreterSession` with approval gating for privileged actions
- **Browser automation** — Playwright-backed browser bridge for local web tasks (optional install)
- **Tool Forge** — create, run, and promote temporary tools via API without restarting the engine
- **Multiple UIs** — main command deck (`/ui/`) and a lighter flow deck (`/ui-easy/`) served by the same API
- **CLI** — `j-engine` and `j-agent` entrypoints for headless and scripted use
- **Pluggable backends** — route inference to Ollama (local), OpenAI, OpenRouter, or Google Gemini per agent
- **MPF registry** — a short pointer layer that maps agent names to full payload files, making it easy to add or swap agents without changing engine code

## What ships here

- `jl_engine_core/`: the core engine, MPF registry loader, backends, behavior engine, memory, cognitive gears, and compatibility API
- `src/jl_platform/`: the full local platform runtime, quest/interpreter flow, browser bridge, and operator tools
- `ui_web/`: the main command deck served at `/ui/`
- `ui_easy/`: the lighter flow deck served at `/ui-easy/`
- `src/jl_engine_cli/`: CLI entrypoints (`j-engine`, `j-agent`)
- `game_integrations/`: game persona integration layer
- `modules/`: utility modules including MPF card converter
- `tools/`: shared utility scripts
- `docs/`: architecture notes, MPF standard, tool forge guide, and error-handling reference

## Quick start

### Windows front door

For a true one-click first run on Windows, double-click:

```powershell
.\install_and_run_windows.bat
```

That script uses your current Python install, installs the API dependencies into that environment, and then launches the standalone command deck.

If you explicitly want an isolated `.venv`, set `JL_PLATFORM_USE_VENV=1` before running it.

Notes for the first Windows install:

- `Defaulting to user installation because normal site-packages is not writeable` is normal on a non-admin Python install
- `Checking if build backend supports build_editable ... done` is a normal `pip install -e` step, not a JL Engine error
- if that window sits there for several minutes with no new output, run `py -3 -m pip install --disable-pip-version-check -e ".[api]" -v` from the repo root to see the exact package step that is stalling

If you already have the environment installed, the faster launcher is:

```powershell
.\run_command_deck.bat
```

That launcher starts the full JL Platform API at `jl_platform.services.api.main:app`, waits for `/health`, and opens the standalone command deck window using the current Python environment.

Optional launcher switches:

- `JL_PLATFORM_UI_PATH=/ui/` keeps the main command deck
- `JL_PLATFORM_UI_PATH=/ui-easy/` opens the lighter flow deck
- `JL_PLATFORM_LAUNCH_MODE=standalone` opens an app-style window when Edge or Chrome is available
- `JL_PLATFORM_LAUNCH_MODE=browser` opens a normal browser tab

### Manual API start

```bash
pip install -e .[api]
python -m uvicorn jl_platform.services.api.main:app --host 127.0.0.1 --port 8000
```

Then open:

- `http://127.0.0.1:8000/ui/`
- `http://127.0.0.1:8000/ui-easy/`
- `http://127.0.0.1:8000/health`

### CLI path

```bash
pip install -e .
j-engine --agent SparkByte
```

### Browser automation (optional)

```bash
pip install -e .[browser]
python -m playwright install
```

## Available agents

The engine ships the following built-in agents registered in `jl_engine_core/data/agents/JL_Agents.mpf.json`.

| Agent | Type | Default backend | Description |
|-------|------|-----------------|-------------|
| `SparkByte` | fat-agent | ollama-local | Fast-talking, creative assistant. The default agent on first launch. |
| `SparkByte Modular` | fat-agent (modular) | ollama-local | Modular variant of SparkByte that expands from a base shell at load time. |
| `Slappy` | fat-agent | ollama-local | Chaotic hillbilly-gremlin energy. Good for unfiltered creative problem-solving. |
| `The Gremlin` | fat-agent | ollama-local | High-energy builder agent for rapid prototyping and unconventional solutions. |
| `Supervisor` | fat-agent | ollama-local | Conservative operational mode running on the SparkByte payload. |
| `SaaS Copywriter` | jl-agent | ollama-local | Conversion-focused copy for landing pages, email sequences, and feature announcements. |
| `Cold Outreach Assistant` | jl-agent | ollama-local | Cold email and sales sequence writer optimized for reply-rate improvement. |
| `YouTube Scriptwriter` | jl-agent | ollama-local | Structures and writes YouTube scripts: hooks, arcs, and chapter breakdowns. |
| `Brand Voice Generator` | jl-agent | ollama-local | Produces style guides and tone-of-voice documents from reference material. |
| `Startup Pitch Writer` | jl-agent | ollama-local | Structures investor pitches, one-pagers, and pitch decks for early-stage startups. |
| `Forgebinder` | jl-agent | ollama-local | Tool-forge specialist for creating and promoting tools. |

Switch agents from the UI selector, the CLI (`j-engine --agent "The Gremlin"`), or the API (`POST /quest/switch`). See [`docs/AGENTS.md`](docs/AGENTS.md) for full details on each agent and how to add a custom one.

## Backend providers

Each agent has a `default_backend_id` in the registry. You can override it at launch:

| Provider | Backend ID | Key variable |
|----------|-----------|--------------|
| Ollama (local) | `ollama-local` | _(none — requires Ollama running locally)_ |
| OpenAI | `openai` | `OPENAI_API_KEY` |
| OpenRouter | `openrouter` | `OPENROUTER_API_KEY` |
| Google Gemini | `google-gemini` | `GEMINI_API_KEY` |

No API key is needed when using a local Ollama model. Install [Ollama](https://ollama.com/) and pull a model to get started without any cloud dependency.

## Environment variables

Copy `.env.example` to `.env` and set only the variables you need.

| Variable | Default | Description |
|----------|---------|-------------|
| `JL_ENGINE_BRAIN_BACKEND` | `ollama-local` | Inference backend for conversational turns |
| `JL_ENGINE_TOOL_BACKEND` | `ollama-local` | Inference backend for tool-call turns |
| `JL_OLLAMA_MODEL` | _(auto-detected)_ | Ollama model name override |
| `JL_OPENAI_MODEL` | `gpt-5.2` | OpenAI model name override |
| `JL_OPENROUTER_MODEL` | `openrouter/auto` | OpenRouter model override |
| `OPENAI_API_KEY` | _(empty)_ | Required when using the `openai` backend |
| `OPENROUTER_API_KEY` | _(empty)_ | Required when using the `openrouter` backend |
| `GEMINI_API_KEY` | _(empty)_ | Required when using the `google-gemini` backend |
| `JL_PLATFORM_UI_PATH` | `/ui/` | Which UI to open when launching the command deck |
| `JL_PLATFORM_LAUNCH_MODE` | `standalone` | `standalone` (app window) or `browser` (tab) |
| `JL_PLATFORM_USE_VENV` | _(unset)_ | Set to `1` to force venv creation in the Windows launcher |

Never commit a populated `.env` file.

## Runtime layout

The current source-of-truth runtime files are:

- `jl_engine_core/data/config/JLframe_Engine_Framework.headless.json`
- `jl_engine_core/data/agents/JL_Agents.mpf.json`
- `jl_engine_core/data/behavior_states.json`

The MPF registry is the short pointer layer. It maps names such as `SparkByte` or `SparkByte Modular` to full payload files under the runtime data tree.

## Fat agents and modular agents

JL Engine does not treat fat agents as a sidecar. The engine loads them as the active persona payload for a session.

- `SparkByte`, `Slappy`, `Supervisor`, and `The Gremlin` are fat-agent entries in the MPF registry
- `SparkByte Modular` is a modular fat agent that expands from a `base_shell` into a resolved payload at load time
- quest chat and mission routes create sessions through `FatQuestRuntime`, which in turn loads the requested fat agent into `JLEngineCore`

See [`docs/MPF_OPEN_STANDARD.md`](docs/MPF_OPEN_STANDARD.md) for the full registry and payload format.

## API surfaces

There are two API layers in this repo:

1. Full local platform API: `jl_platform.services.api.main:app`
   This is the primary runtime for `/ui/`, `/ui-easy/`, quest chat, browser bridge, workspace review, and operator tooling.
2. Compatibility API: `jl_engine_core.api_app:app`
   This remains for older integrations and smoke checks, but it is not the main product surface anymore.

> **Security note:** The platform API is designed for trusted local use. Do not expose it to the public internet without adding authentication and network controls. See [`SECURITY.md`](SECURITY.md) for details.

## Project layout

```text
jl_engine_core/         Core engine runtime, data, compatibility API
src/jl_platform/        Full platform runtime and FastAPI service
src/jl_engine_cli/      CLI wrappers and entrypoints (j-engine, j-agent)
ui_web/                 Main command deck (served at /ui/)
ui_easy/                Lightweight flow deck (served at /ui-easy/)
ui/                     PySide desktop UI
game_integrations/      Game persona integration layer
modules/                Utility modules (MPF card converter, etc.)
tools/                  Shared utility scripts
tests/                  Regression and smoke tests
docs/                   Architecture, MPF standard, tool forge, error-handling notes
agents/                 Fat-agent payload files and MPF registry pointer
config/                 JSON schema files for agents and registry
```

## Verification

Useful checks:

```bash
python -m pytest tests/test_smoke.py tests/test_web_ui_easy.py tests/test_web_ui_shell.py
python -m uvicorn jl_platform.services.api.main:app --host 127.0.0.1 --port 8000
```

## More docs

| Document | Contents |
|----------|----------|
| [`ONBOARDING.md`](ONBOARDING.md) | Step-by-step first-run guide and key concepts |
| [`CONTRIBUTING.md`](CONTRIBUTING.md) | Dev setup, code style, and pull request process |
| [`ARCHITECTURE.md`](ARCHITECTURE.md) | Runtime layers, system map, and entrypoints |
| [`TROUBLESHOOTING.md`](TROUBLESHOOTING.md) | Startup and runtime problem fixes |
| [`SECURITY.md`](SECURITY.md) | Local-only boundary and route safety notes |
| [`docs/AGENTS.md`](docs/AGENTS.md) | Built-in agents, switching, and adding custom agents |
| [`docs/MPF_OPEN_STANDARD.md`](docs/MPF_OPEN_STANDARD.md) | Registry and payload format reference |
| [`docs/TOOL_FORGE.md`](docs/TOOL_FORGE.md) | Temporary tool lifecycle and promotion flow |
| [`docs/ERROR_HANDLING.md`](docs/ERROR_HANDLING.md) | API error shapes and guidance for new routes |

## License

See [`LICENSE.md`](LICENSE.md).
