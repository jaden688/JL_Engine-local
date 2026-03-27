@echo off
rem Licensed under the Apache License, Version 2.0. See LICENSE.md and NOTICE.
setlocal enableextensions
pushd "%~dp0"

set "SCRIPT_DIR=%CD%"
for %%I in ("%SCRIPT_DIR%\..") do set "ROOT=%%~fI"
set "PYTHONPATH=%ROOT%;%ROOT%\src;%PYTHONPATH%"

echo [J_engine] Starting PySide6 desktop UI...
python "%ROOT%\ui\pyside_ui.py" %*

if errorlevel 1 (
    echo.
    echo Press any key to exit...
    pause >nul
)

popd
exit /b %errorlevel%
