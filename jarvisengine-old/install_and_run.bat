@echo off
title JL Engine Installer and Launcher

echo =================================================
echo      JL Engine - Installer and Launcher
echo =================================================
echo.

REM Change directory to the location of this batch file to ensure all paths are correct.
cd /d "%~dp0"

echo [STEP 1] Checking for required Python packages...
echo.

REM --- Check for 'requests' package ---
pip show requests >nul 2>&1
if %errorlevel% neq 0 (
    echo  - 'requests' not found. Installing now...
    py -3 -m pip install requests
) else (
    echo  - 'requests' is already installed.
)

REM --- Check for 'tkinterdnd2' package ---
pip show tkinterdnd2 >nul 2>&1
if %errorlevel% neq 0 (
    echo  - 'tkinterdnd2' not found. Installing now...
    py -3 -m pip install tkinterdnd2
) else (
    echo  - 'tkinterdnd2' is already installed.
)

REM --- Check for 'watchdog' package ---
pip show watchdog >nul 2>&1
if %errorlevel% neq 0 (
    echo  - 'watchdog' not found. Installing now...
    py -3 -m pip install watchdog
) else (
    echo  - 'watchdog' is already installed.
)

REM --- Check for 'open-interpreter' package (for Open Interpreter backend) ---
pip show open-interpreter >nul 2>&1
if %errorlevel% neq 0 (
    echo  - 'open-interpreter' not found. Installing now...
    py -3 -m pip install open-interpreter
) else (
    echo  - 'open-interpreter' is already installed.
)

echo.
echo [STEP 2] NOTE: If using the 'Ollama (Local)' backend,
echo please ensure the Ollama server is running manually before launching.
echo [STEP 2] Starting local Ollama server in the background...
start "Ollama Server" ollama serve
echo The Ollama server window will open separately. You can minimize it.
echo Waiting 10 seconds for the server to initialize...
timeout /t 10 /nobreak >nul

echo.
echo [STEP 3] Starting the JL Engine application...
py -3 main_app.py

pause
