@echo off
rem Licensed under the MIT License. See LICENSE.md.
setlocal enableextensions
pushd "%~dp0"

set "ROOT=%CD%"
set "LAST_EXITCODE=0"

if /I "%JL_LOCAL_UNSAFE_TOOLS%"=="0" (
    set "LAUNCHER_UNSAFE=0"
) else (
    set "LAUNCHER_UNSAFE=1"
)

if /I "%JL_COMMAND_DECK_TRANSCRIPT%"=="0" (
    set "LAUNCHER_LOGS=0"
) else (
    set "LAUNCHER_LOGS=1"
)

call :sync_env

:menu
echo.
echo [JL Engine Launcher]
echo   Unsafe tools: %LAUNCHER_UNSAFE_LABEL%
echo   Deck logs:    %LAUNCHER_LOGS_LABEL%
echo.
echo   U^) Toggle unsafe tools
echo   L^) Toggle command-deck logs
echo   1^) Install dependencies and run the command deck
echo   2^) Run the command deck
echo   3^) Start the CLI
echo   4^) Open the PySide6 desktop UI
echo   Q^) Exit
set "CHOICE="
set /p CHOICE=Select an option (U/L/1-4, Q to quit):
if errorlevel 1 goto end
if /I "%CHOICE%"=="U" goto toggle_unsafe
if /I "%CHOICE%"=="L" goto toggle_logs
if /I "%CHOICE%"=="1" goto install
if /I "%CHOICE%"=="2" goto deck
if /I "%CHOICE%"=="3" goto cli
if /I "%CHOICE%"=="4" goto pyside
if /I "%CHOICE%"=="Q" goto end
goto menu

:toggle_unsafe
if "%LAUNCHER_UNSAFE%"=="1" (
    set "LAUNCHER_UNSAFE=0"
) else (
    set "LAUNCHER_UNSAFE=1"
)
call :sync_env
goto menu

:toggle_logs
if "%LAUNCHER_LOGS%"=="1" (
    set "LAUNCHER_LOGS=0"
) else (
    set "LAUNCHER_LOGS=1"
)
call :sync_env
goto menu

:sync_env
if "%LAUNCHER_UNSAFE%"=="1" (
    set "JL_LOCAL_UNSAFE_TOOLS=1"
    set "LAUNCHER_UNSAFE_LABEL=ON"
) else (
    set "JL_LOCAL_UNSAFE_TOOLS=0"
    set "LAUNCHER_UNSAFE_LABEL=OFF"
)
if "%LAUNCHER_LOGS%"=="1" (
    set "JL_COMMAND_DECK_TRANSCRIPT=1"
    set "LAUNCHER_LOGS_LABEL=ON"
) else (
    set "JL_COMMAND_DECK_TRANSCRIPT=0"
    set "LAUNCHER_LOGS_LABEL=OFF"
)
exit /b 0

:install
call "%ROOT%\legacy_launchers\install_and_run_windows.bat"
set "LAST_EXITCODE=%errorlevel%"
echo.
echo [JL Engine Launcher] Install path finished with exit code %LAST_EXITCODE%.
goto menu

:deck
call "%ROOT%\legacy_launchers\run_command_deck.bat"
set "LAST_EXITCODE=%errorlevel%"
echo.
echo [JL Engine Launcher] Command deck finished with exit code %LAST_EXITCODE%.
goto menu

:cli
call "%ROOT%\legacy_launchers\start.bat"
set "LAST_EXITCODE=%errorlevel%"
echo.
echo [JL Engine Launcher] CLI finished with exit code %LAST_EXITCODE%.
goto menu

:pyside
call "%ROOT%\legacy_launchers\run_pyside_ui.bat"
set "LAST_EXITCODE=%errorlevel%"
echo.
echo [JL Engine Launcher] PySide6 UI finished with exit code %LAST_EXITCODE%.
goto menu

:end
popd
exit /b %LAST_EXITCODE%
