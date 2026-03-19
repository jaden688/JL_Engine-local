@echo off
setlocal enableextensions
pushd "%~dp0"

set "SCRIPT_DIR=%CD%"
for %%I in ("%SCRIPT_DIR%\..") do set "ROOT=%%~fI"
set "PYTHONPATH=%ROOT%;%ROOT%\src;%PYTHONPATH%"

powershell -NoProfile -ExecutionPolicy Bypass -File "%SCRIPT_DIR%\run_command_deck.ps1" %*
set "EXITCODE=%errorlevel%"

if %EXITCODE% geq 1 (
    echo.
    echo Press any key to exit...
    pause >nul
)

popd
exit /b %EXITCODE%
