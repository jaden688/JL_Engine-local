@echo off
setlocal enableextensions
pushd "%~dp0"

set "ROOT=%CD%"
set "PYTHONPATH=%ROOT%;%ROOT%\src;%PYTHONPATH%"

powershell -NoProfile -ExecutionPolicy Bypass -File "%ROOT%\run_command_deck.ps1" %*
set "EXITCODE=%errorlevel%"

if %EXITCODE% geq 1 (
    echo.
    echo Press any key to exit...
    pause >nul
)

popd
exit /b %EXITCODE%
