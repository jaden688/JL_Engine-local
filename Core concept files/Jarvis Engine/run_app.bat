@echo off
REM This batch file starts the Jarvis Engine application.

echo Locating Jarvis Engine...

REM Change directory to the location of this batch file.
cd /d "%~dp0"

echo Starting application...
python main_app.py
pause