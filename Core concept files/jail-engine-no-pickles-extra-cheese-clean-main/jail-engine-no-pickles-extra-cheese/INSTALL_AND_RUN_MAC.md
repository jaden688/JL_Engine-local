# JL Engine macOS Install and Run

This guide uses the helper script in this folder.

## Prereqs
- macOS with Python 3.10+ available as `python3`
- Ollama installed and on PATH (`ollama`)

## Quick start
```bash
cd JL_engine0ne/JL_Engine0ne.1/JL_Engine
chmod +x install_and_run_mac.sh
./install_and_run_mac.sh
```

What the script does:
- creates a local virtual environment in `.venv`
- installs dependencies from `requirements.txt`
- starts `ollama serve` in a new Terminal window
- launches `main_app.py`

## Manual run (no script)
```bash
cd JL_engine0ne/JL_Engine0ne.1/JL_Engine
python3 -m venv .venv
./.venv/bin/python -m pip install -r requirements.txt
ollama serve
```
In another Terminal:
```bash
cd JL_engine0ne/JL_Engine0ne.1/JL_Engine
./.venv/bin/python main_app.py
```

## Troubleshooting
- If `ollama` is missing, install it from https://ollama.com/
- If `python3` is missing, install Python 3.10+ and rerun
