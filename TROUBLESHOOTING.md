# Troubleshooting

## The launcher opens nothing

If this is a fresh Windows checkout, start with:

```powershell
.\launcher.bat
```

Choose option `1` to install `.[api]` and launch the normal command deck flow.

If the first install prints lines like:

```text
Defaulting to user installation because normal site-packages is not writeable
Checking if build backend supports build_editable ... done
```

that is still normal. The launcher is in the `pip install -e ".[api]"` phase, not the JL Engine boot phase yet.

- `Defaulting to user installation...` means Python is installing into the current user's site-packages instead of system-wide
- `build_editable` is the standard editable-install check for the repo itself
- paths like `file:///C:/...%20%28...%29/...` are just URL-encoded folder names, not corruption

If that step really hangs for several minutes, run the install command manually with verbose output:

```powershell
py -3 -m pip install --disable-pip-version-check -e ".[api]" -v
```

That will show the exact dependency or wheel-build step that is stalled.

If you explicitly want a virtual environment, set:

```powershell
$env:JL_PLATFORM_USE_VENV = "1"
.\launcher.bat
```

Use the Windows launcher from the repo root:

```powershell
.\launcher.bat
```

Choose option `2` to start `jl_platform.services.api.main:app`, wait for `/health`, and open the selected UI.

If you want a normal browser tab instead of an app-style window:

```powershell
$env:JL_PLATFORM_LAUNCH_MODE = "browser"
.\launcher.bat
```

If you want the main command deck:

```powershell
$env:JL_PLATFORM_UI_PATH = "/ui/"
.\launcher.bat
```

## `/health` fails

Make sure you are starting the full platform API, not only the older compatibility API:

```powershell
pip install -e .[api]
python -m uvicorn jl_platform.services.api.main:app --host 127.0.0.1 --port 8000
curl http://127.0.0.1:8000/health
```

The compatibility API at `jl_engine_core.api_app:app` still exists, but it is not the main web product surface.

## `ModuleNotFoundError` for `jl_engine`, `jl_platform`, or `jl_engine_core`

Install from the repository root:

```powershell
pip install -e .
python -m pytest tests/test_smoke.py
```

## The wrong UI opens

The launcher defaults to `/ui/`. Override it before starting:

```powershell
$env:JL_PLATFORM_UI_PATH = "/ui/"
.\launcher.bat
```

or

```powershell
$env:JL_PLATFORM_UI_PATH = "/ui/"
.\launcher.bat
```

## The browser bridge is unavailable

If the UI reports `playwright_unavailable`, install the browser extra and Playwright browsers:

```powershell
pip install -e .[browser]
python -m playwright install
```

Then restart the platform API.

## A quest action says confirmation is required

That is expected for privileged operations. The interpreter/quest path can return a confirmation gate before running shell, browser, or file actions.

- approve with the matching confirm endpoint from the UI
- or retry with a non-privileged task if you only wanted a plain answer

## Ollama or model calls fail

Check the configured local backend and the running Ollama service:

```powershell
python C:/Users/J_lin/.codex/skills/jl-engine/scripts/jl_engine_probe.py --repo . ollama
j-engine --brain-backend ollama-local --tool-backend ollama-local
```

Also verify `.env` and `jl_engine_core/gemini_config.json` if you have customized providers.

## Clean local rebuild

```powershell
Get-ChildItem -Recurse -Directory -Force | Where-Object {
    $_.Name -in @('__pycache__', '.pytest_cache', '.mypy_cache')
} | Remove-Item -Recurse -Force

Get-ChildItem -Recurse -File -Filter *.pyc | Remove-Item -Force
pip install -e .[api]
python -m pytest tests/test_smoke.py
```
