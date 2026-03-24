@echo off
title JL Engine Launcher

REM Change directory to the location of this batch file to ensure all paths are correct.
cd /d "%~dp0"

echo.
echo [1/2] Starting local Ollama server in the background...
start "Ollama Server" ollama serve
echo The Ollama server window will open separately. You can minimize it.
echo Waiting 10 seconds for the server to initialize...
timeout /t 10 /nobreak >nul
echo.

echo [2/2] Starting JL Engine application...
py -3 main_app.py

pause