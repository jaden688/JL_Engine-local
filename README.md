# JL Engine Local

JL Engine Local is the local-first JL Engine runtime and UI stack. The engine is the product surface, and `SparkByte` is the default active fat-agent voice loaded on top of it.

This repository is source-available under the non-commercial license in `LICENSE.md`. It is not an OSI open-source license.

## What ships here

- `jl_engine_core/`: the core engine, MPF registry loader, backends, and compatibility API
- `src/jl_platform/`: the full local platform runtime, quest/interpreter flow, browser bridge, and operator tools
- `ui_web/`: the main command deck served at `/ui/`
- `ui_easy/`: the lighter flow deck served at `/ui-easy/`
- `src/jl_engine_cli/`: CLI entrypoints such as `j-engine`

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

```powershell
pip install -e .[api]
python -m uvicorn jl_platform.services.api.main:app --host 127.0.0.1 --port 8000
```

Then open:

- `http://127.0.0.1:8000/ui/`
- `http://127.0.0.1:8000/ui-easy/`
- `http://127.0.0.1:8000/health`

### CLI path

```powershell
pip install -e .
j-engine --agent SparkByte
```

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

## API surfaces

There are two API layers in this repo:

1. Full local platform API: `jl_platform.services.api.main:app`
   This is the primary runtime for `/ui/`, `/ui-easy/`, quest chat, browser bridge, workspace review, and operator tooling.
2. Compatibility API: `jl_engine_core.api_app:app`
   This remains for older integrations and smoke checks, but it is not the main product surface anymore.

## Project layout

```text
jl_engine_core/     Core engine runtime, data, compatibility API
src/jl_platform/    Full platform runtime and FastAPI service
src/jl_engine_cli/  CLI wrappers and entrypoints
ui_web/             Main command deck
ui_easy/            Lightweight flow deck
tests/              Regression and smoke tests
docs/               Architecture, MPF, forge, and error-handling notes
```

## Verification

Useful checks:

```powershell
python -m pytest tests/test_smoke.py tests/test_web_ui_easy.py tests/test_web_ui_shell.py
python -m uvicorn jl_platform.services.api.main:app --host 127.0.0.1 --port 8000
```

## More docs

- `ARCHITECTURE.md`
- `TROUBLESHOOTING.md`
- `docs/README.md`
- `docs/MPF_OPEN_STANDARD.md`
- `docs/TOOL_FORGE.md`
- `docs/ERROR_HANDLING.md`
- `SECURITY.md`

## License

See `LICENSE.md`.
