# Onboarding Guide

Welcome to JL Engine Local. This guide walks you through getting the engine running for the first time, explains the core concepts, and points you toward the right docs for your next steps.

## Prerequisites

- Python 3.10 or newer
- Git
- Windows, macOS, or Linux (Windows launchers are provided for one-click startup)
- Optional: [Ollama](https://ollama.com/) for local model inference, or an API key for OpenAI, OpenRouter, or Gemini

## Step 1 — Clone the repository

```bash
git clone https://github.com/jaden688/JL_Engine-local.git
cd JL_Engine-local
```

## Step 2 — Set up your environment file

Copy the example environment file and fill in any keys you need:

```bash
cp .env.example .env
```

Open `.env` and configure:

- `JL_ENGINE_BRAIN_BACKEND` / `JL_ENGINE_TOOL_BACKEND` — set to `ollama-local` for a fully local setup, or `openai` / `openrouter` / `gemini` for cloud-hosted inference
- Model override variables are optional; sensible defaults are used if unset
- API keys are only needed when using a remote provider

You do not need any API key to run the engine with a local Ollama model.

## Step 3 — Install dependencies

### Windows one-click (recommended for first run)

Double-click `install_and_run_windows.bat` in the repository root. It will:

1. Install `.[api]` into your current Python environment
2. Start the JL Platform API
3. Open the command deck in a standalone window

### Manual install

```bash
pip install -e .[api]
```

To add browser automation support:

```bash
pip install -e .[browser]
python -m playwright install
```

## Step 4 — Start the engine

### Windows quick launcher (after first install)

```powershell
.\run_command_deck.bat
```

### Any platform

```bash
python -m uvicorn jl_platform.services.api.main:app --host 127.0.0.1 --port 8000
```

Then open one of:

- `http://127.0.0.1:8000/ui/` — main command deck
- `http://127.0.0.1:8000/ui-easy/` — lighter flow deck
- `http://127.0.0.1:8000/health` — quick health check

### CLI

```bash
pip install -e .
j-engine --agent SparkByte
```

## Step 5 — Verify the install

```bash
python -m pytest tests/test_smoke.py tests/test_web_ui_easy.py tests/test_web_ui_shell.py
```

All tests should pass on a clean install.

## Key concepts

### Fat agents and the MPF registry

The engine loads agents from the MPF registry at `jl_engine_core/data/agents/JL_Agents.mpf.json`. Each entry is a short pointer to a full payload file (for example, `SparkByte` points to `fat_agents/SparkByte_Full.json`). The payload file contains the complete persona, behavior rules, and model settings for that agent.

You select an agent when starting a session. The engine loads the registry entry, resolves the payload, and runs all requests through that active persona.

See `docs/AGENTS.md` for a description of each built-in agent and `docs/MPF_OPEN_STANDARD.md` for the full registry and payload format.

### Quest sessions and the interpreter

User requests flow through `FatQuestRuntime` → `JLEngineCore` → `InterpreterSession`. The interpreter handles tool calls, file actions, browser automation, and any step that needs user approval before execution.

Privileged actions return a confirmation-required response. Approve them from the UI or the confirm endpoint before they run.

### UI surfaces

| Path | Purpose |
|------|---------|
| `/ui/` | Full command deck with all features |
| `/ui-easy/` | Lightweight flow deck |
| `/health` | API health check |

### Configuration and secrets

Runtime config lives in `jl_engine_core/data/config/`. The `.env` file in the repo root is the right place for provider keys and backend overrides. Never commit a populated `.env`.

## Common issues

See `TROUBLESHOOTING.md` for a full list. The most common first-run issues are:

| Symptom | Fix |
|---------|-----|
| `ModuleNotFoundError: jl_platform` | Run `pip install -e .[api]` from the repo root |
| `/health` returns 404 | Make sure you started `jl_platform.services.api.main:app`, not the older compat API |
| Ollama calls fail | Start Ollama, then run `j-engine --brain-backend ollama-local` |
| Wrong UI opens | Set `JL_PLATFORM_UI_PATH=/ui-easy/` before launching |

## Next steps

| Goal | Read |
|------|------|
| Understand the codebase layers | `ARCHITECTURE.md` |
| Learn about agents and payloads | `docs/AGENTS.md` |
| Work with the MPF registry | `docs/MPF_OPEN_STANDARD.md` |
| Create or extend tools | `docs/TOOL_FORGE.md` |
| Contribute to the project | `CONTRIBUTING.md` |
| Understand API error shapes | `docs/ERROR_HANDLING.md` |
| Fix startup or runtime problems | `TROUBLESHOOTING.md` |
| Review security and network notes | `SECURITY.md` |
