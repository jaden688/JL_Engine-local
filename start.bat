@echo off
setlocal enableextensions
pushd "%~dp0"

set "ROOT=%CD%"
set "PYTHONPATH=%ROOT%;%ROOT%\src;%PYTHONPATH%"

if not defined JL_ENGINE_BRAIN_BACKEND set "JL_ENGINE_BRAIN_BACKEND=ollama-local"
if not defined JL_ENGINE_TOOL_BACKEND set "JL_ENGINE_TOOL_BACKEND=ollama-local"
if not defined OLLAMA_URL set "OLLAMA_URL=http://127.0.0.1:11434"
if not defined JL_OLLAMA_MODEL set "JL_OLLAMA_MODEL=dolphin3:latest"
if not defined JL_OPENROUTER_MODEL set "JL_OPENROUTER_MODEL=openrouter/auto"

echo [J_engine] Starting Agent CLI...
python -m jl_engine_cli.main --unsafe-tools --auto-approve %*

if errorlevel 1 (
    echo.
    echo Press any key to exit...
    pause >nul
)

popd
exit /b %errorlevel%
