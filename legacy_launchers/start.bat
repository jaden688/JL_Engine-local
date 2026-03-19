@echo off
rem Licensed under the MIT License. See LICENSE.md.
setlocal enableextensions
pushd "%~dp0"

set "SCRIPT_DIR=%CD%"
for %%I in ("%SCRIPT_DIR%\..") do set "ROOT=%%~fI"
set "PYTHONPATH=%ROOT%;%ROOT%\src;%PYTHONPATH%"

if not defined JL_ENGINE_BRAIN_BACKEND set "JL_ENGINE_BRAIN_BACKEND=ollama-local"
if not defined JL_ENGINE_TOOL_BACKEND set "JL_ENGINE_TOOL_BACKEND=ollama-local"
if not defined OLLAMA_URL set "OLLAMA_URL=http://127.0.0.1:11434"
if not defined JL_OLLAMA_MODEL set "JL_OLLAMA_MODEL=dolphin3:latest"
if not defined JL_OPENROUTER_MODEL set "JL_OPENROUTER_MODEL=openrouter/auto"
if not defined JL_LOCAL_UNSAFE_TOOLS set "JL_LOCAL_UNSAFE_TOOLS=1"
if not defined JL_ENGINE_CLI_AUTO_APPROVE set "JL_ENGINE_CLI_AUTO_APPROVE=1"

echo [J_engine] Starting Agent CLI...
if /I "%JL_LOCAL_UNSAFE_TOOLS%"=="0" (
    echo [J_engine] Unsafe tools: OFF
) else (
    echo [J_engine] Unsafe tools: ON
)
if /I "%JL_ENGINE_CLI_AUTO_APPROVE%"=="0" (
    echo [J_engine] Auto-approve: OFF
) else (
    echo [J_engine] Auto-approve: ON
)
set "CLI_ARGS="
if /I not "%JL_LOCAL_UNSAFE_TOOLS%"=="0" set "CLI_ARGS=%CLI_ARGS% --unsafe-tools"
if /I not "%JL_ENGINE_CLI_AUTO_APPROVE%"=="0" set "CLI_ARGS=%CLI_ARGS% --auto-approve"
python -m jl_engine_cli.main %CLI_ARGS% %*

if errorlevel 1 (
    echo.
    echo Press any key to exit...
    pause >nul
)

popd
exit /b %errorlevel%
