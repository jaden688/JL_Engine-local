# Contributing to JL Engine Local

Thank you for your interest in contributing. This document covers the development setup, project conventions, and the pull request process.

## Code of conduct

Be respectful and constructive in all interactions. Issues and pull requests are the primary collaboration channels.

## Licensing

This repository is available under the Apache License, Version 2.0. See `LICENSE.md` before contributing. By submitting a pull request you agree that your contribution will be released under the same license.

## Development setup

### 1. Fork and clone

```bash
git clone https://github.com/<your-fork>/JL_Engine-local.git
cd JL_Engine-local
```

### 2. Create a virtual environment

```bash
python -m venv .venv
# Windows
.venv\Scripts\activate
# macOS / Linux
source .venv/bin/activate
```

### 3. Install in editable mode with all extras

```bash
pip install -e .[api,browser]
```

### 4. Copy the environment file

```bash
cp .env.example .env
```

Fill in any provider keys you need. The smoke tests only require the base install (no API keys needed for offline tests).

### 5. Verify the baseline

```bash
python -m pytest tests/test_smoke.py tests/test_web_ui_shell.py
```

All tests should pass before you make any changes.

## Project layout

```text
jl_engine_core/     Core engine runtime, MPF registry, data, and compatibility API
src/jl_platform/    Full platform runtime, FastAPI service, quest runtime, interpreter
src/jl_engine_cli/  CLI entrypoints (j-engine, j-agent)
ui_web/             Main command deck (served at /ui/)
ui/                 PySide desktop UI
tests/              Smoke and regression tests
docs/               Architecture, MPF standard, tool forge, error handling notes
agents/             Fat-agent payload files and MPF registry pointer
config/             JSON schema files for agents and registry
tools/              Shared utility scripts
```

The canonical runtime data tree is `jl_engine_core/data/`. Edits to agent payloads and config should target files under that path, not the root-level mirrors.

## Branching strategy

- `main` — stable branch; direct commits are not accepted
- Feature work: `feature/<short-description>`
- Bug fixes: `fix/<short-description>`
- Docs: `docs/<short-description>`

Open a pull request from your branch into `main`.

## Commit style

Use short, imperative subject lines (50 characters or fewer):

```
Add SparkByte modular shell support
Fix quest session not resetting on agent switch
Update ONBOARDING.md with venv step
```

Reference issue numbers where applicable: `Closes #42`.

## Code style

- Python: follow [PEP 8](https://peps.python.org/pep-0008/). Black-compatible formatting is preferred for new files.
- Keep lines at 100 characters or fewer.
- Add docstrings to public classes and functions.
- Avoid silent broad `except` clauses; catch specific exception types and log or re-raise.
- Do not commit `.env`, `*.pyc`, `__pycache__/`, `.pytest_cache/`, or anything under `src/tools_runtime/`.

## Testing

- Add or update tests in `tests/` when changing behavior.
- Keep tests fast and side-effect-free where possible. Mock external services (Ollama, OpenAI) in unit tests.
- Run the full smoke suite before opening a PR:

```bash
python -m pytest tests/test_smoke.py tests/test_web_ui_shell.py
```

## Pull request checklist

Before submitting:

- [ ] Tests pass locally (`python -m pytest tests/`)
- [ ] New behavior has test coverage
- [ ] Docs are updated if the change affects a user-visible feature or API
- [ ] No secrets, keys, or populated `.env` files are included
- [ ] `src/tools_runtime/` is not committed
- [ ] The PR description explains what changed and why

## Areas of the codebase and who to involve

| Area | Key files |
|------|-----------|
| Engine core and MPF | `jl_engine_core/engine_core.py`, `jl_engine_core/data/agents/` |
| Quest and interpreter | `src/jl_platform/quest_runtime.py`, `src/jl_platform/interpreter.py` |
| Platform API routes | `src/jl_platform/services/api/main.py` |
| Tool forge | `src/jl_platform/core/tools/`, `docs/TOOL_FORGE.md` |
| Browser bridge | `src/jl_platform/browser/` |
| Web UI | `ui_web/` |
| CLI | `src/jl_engine_cli/main.py` |
| Desktop UI | `ui/pyside_ui.py` |

## Adding a new agent

1. Create a payload file under `jl_engine_core/data/agents/fat_agents/` (or `jl_agents/` for non-fat agents).
2. Add a registry entry to `jl_engine_core/data/agents/JL_Agents.mpf.json` pointing to that file.
3. Test by selecting the agent in a quest session.
4. Document the agent in `docs/AGENTS.md`.

## Adding or promoting a tool

See `docs/TOOL_FORGE.md` for the full lifecycle. Short summary:

1. Use `POST /tools/forge/create` to create a temporary tool.
2. Iterate and test with `POST /tools/forge/run`.
3. When stable, promote with `POST /tools/forge/promote`.
4. Promoted tools land in `src/jl_platform/core/tools/promoted/`.

## Reporting bugs

Open a GitHub issue with:

- A clear title describing the symptom
- Steps to reproduce
- Expected versus actual behavior
- Platform, Python version, and install method

For security issues, see `SECURITY.md` — do not open a public issue.

