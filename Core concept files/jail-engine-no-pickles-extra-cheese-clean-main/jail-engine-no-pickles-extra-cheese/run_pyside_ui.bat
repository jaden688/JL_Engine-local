@echo off
setlocal

REM Change directory to the location of this batch file to ensure all paths are correct.
cd /d "%~dp0"

REM Check for Ollama.
where ollama >nul 2>&1
if %errorlevel% neq 0 (
    echo Ollama was not found on PATH.
    echo Install Ollama from https://ollama.com/ and rerun this file.
    pause
    exit /b 1
)

echo [1/2] Starting local Ollama server in the background...
start "Ollama Server" ollama serve
echo The Ollama server window will open separately. You can minimize it.
echo Waiting 10 seconds for the server to initialize...
timeout /t 10 /nobreak >nul
echo.

echo [2/2] Starting JL Engine PySide UI...
if exist ".venv\Scripts\python.exe" (
    ".venv\Scripts\python.exe" pyside_ui.py
) else (
    where py >nul 2>&1
    if %errorlevel%==0 (
        py -3 pyside_ui.py
    ) else (
        where python >nul 2>&1
        if %errorlevel%==0 (
            python pyside_ui.py
        ) else (
            echo Python was not found on PATH and no .venv was detected.
            echo Install Python 3.10+ and rerun this file.
            pause
            exit /b 1
        )
    )
)

pause
