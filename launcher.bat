@echo off
rem Licensed under the Apache License, Version 2.0. See LICENSE.md and NOTICE.
setlocal enableextensions
pushd "%~dp0"

set "ROOT=%CD%"
set "LAST_EXITCODE=0"

rem ============================================================================
rem Initialize configuration state
rem ============================================================================

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

if /I "%JL_PLATFORM_ALLOW_NETWORK%"=="0" (
    set "LAUNCHER_NETWORK=0"
) else (
    set "LAUNCHER_NETWORK=1"
)

if /I "%JL_ENGINE_SAFETY_ON%"=="0" (
    set "LAUNCHER_SAFETY=0"
) else (
    set "LAUNCHER_SAFETY=1"
)

if /I "%JL_ENGINE_SUPERVISOR_ON%"=="0" (
    set "LAUNCHER_SUPERVISOR=0"
) else (
    set "LAUNCHER_SUPERVISOR=1"
)

call :sync_env

rem ============================================================================
rem Main Menu Loop
rem ============================================================================

:menu
cls
echo.
echo   ╔════════════════════════════════════════════════════════════════╗
echo   ║                                                                ║
echo   ║                    ✦ JL ENGINE LOCAL v1.0.0 ✦                ║
echo   ║                  Fat Agents. Independent. Ready.              ║
echo   ║                                                                ║
echo   ╚════════════════════════════════════════════════════════════════╝
echo.
echo   ┌─ RUNTIME CONFIGURATION ──────────────────────────────────────┐
echo   │                                                              │
echo   │   Unsafe Tools .......... %LAUNCHER_UNSAFE_LABEL%                         │
echo   │   Deck Logs ............ %LAUNCHER_LOGS_LABEL%                         │
echo   │   Network Access ....... %LAUNCHER_NETWORK_LABEL%                         │
echo   │   Safety Mode .......... %LAUNCHER_SAFETY_LABEL%                         │
echo   │   Supervisor/Gating .... %LAUNCHER_SUPERVISOR_LABEL%                         │
echo   │                                                              │
echo   └──────────────────────────────────────────────────────────────┘
echo.
echo   ┌─ TOGGLES ─────────────────────────────────────────────────────┐
echo   │                                                              │
echo   │   [U]  Unsafe Tools              [S]  Safety Mode           │
echo   │   [L]  Deck Logs                 [V]  Supervisor/Gating     │
echo   │   [N]  Network Access                                       │
echo   │                                                              │
echo   └──────────────────────────────────────────────────────────────┘
echo.
echo   ┌─ LAUNCH OPTIONS ──────────────────────────────────────────────┐
echo   │                                                              │
echo   │   [1]  Install Dependencies + Command Deck                  │
echo   │   [2]  Command Deck (Web UI)                                │
echo   │   [3]  CLI (Terminal)                                       │
echo   │   [4]  PySide6 Desktop UI                                   │
echo   │                                                              │
echo   └──────────────────────────────────────────────────────────────┘
echo.
echo   [Q]  Quit
echo.
set /p CHOICE=  ► Select option:
if errorlevel 1 goto end
if /I "%CHOICE%"=="U" goto toggle_unsafe
if /I "%CHOICE%"=="L" goto toggle_logs
if /I "%CHOICE%"=="N" goto toggle_network
if /I "%CHOICE%"=="S" goto toggle_safety
if /I "%CHOICE%"=="V" goto toggle_supervisor
if /I "%CHOICE%"=="1" goto install
if /I "%CHOICE%"=="2" goto deck
if /I "%CHOICE%"=="3" goto cli
if /I "%CHOICE%"=="4" goto pyside
if /I "%CHOICE%"=="Q" goto end
goto menu

rem ============================================================================
rem Toggle Functions
rem ============================================================================

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

:toggle_network
if "%LAUNCHER_NETWORK%"=="1" (
    set "LAUNCHER_NETWORK=0"
) else (
    set "LAUNCHER_NETWORK=1"
)
call :sync_env
goto menu

:toggle_safety
if "%LAUNCHER_SAFETY%"=="1" (
    set "LAUNCHER_SAFETY=0"
) else (
    set "LAUNCHER_SAFETY=1"
)
call :sync_env
goto menu

:toggle_supervisor
if "%LAUNCHER_SUPERVISOR%"=="1" (
    set "LAUNCHER_SUPERVISOR=0"
) else (
    set "LAUNCHER_SUPERVISOR=1"
)
call :sync_env
goto menu

rem ============================================================================
rem Sync Environment Variables
rem ============================================================================

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

if "%LAUNCHER_NETWORK%"=="1" (
    set "JL_PLATFORM_ALLOW_NETWORK=1"
    set "LAUNCHER_NETWORK_LABEL=ON"
) else (
    set "JL_PLATFORM_ALLOW_NETWORK=0"
    set "LAUNCHER_NETWORK_LABEL=OFF"
)

if "%LAUNCHER_SAFETY%"=="1" (
    set "JL_ENGINE_SAFETY_ON=1"
    set "LAUNCHER_SAFETY_LABEL=ON"
) else (
    set "JL_ENGINE_SAFETY_ON=0"
    set "LAUNCHER_SAFETY_LABEL=OFF"
)

if "%LAUNCHER_SUPERVISOR%"=="1" (
    set "JL_ENGINE_SUPERVISOR_ON=1"
    set "LAUNCHER_SUPERVISOR_LABEL=ON"
) else (
    set "JL_ENGINE_SUPERVISOR_ON=0"
    set "LAUNCHER_SUPERVISOR_LABEL=OFF"
)

exit /b 0

rem ============================================================================
rem Launch Paths
rem ============================================================================

:install
cls
echo.
echo   ⏳ Installing dependencies and launching command deck...
echo.
call "%ROOT%\legacy_launchers\install_and_run_windows.bat"
set "LAST_EXITCODE=%errorlevel%"
echo.
echo   ✓ Command deck session ended (exit code: %LAST_EXITCODE%)
echo.
pause
goto menu

:deck
cls
echo.
echo   ⏳ Launching command deck...
echo.
call "%ROOT%\legacy_launchers\run_command_deck.bat"
set "LAST_EXITCODE=%errorlevel%"
echo.
echo   ✓ Command deck session ended (exit code: %LAST_EXITCODE%)
echo.
pause
goto menu

:cli
cls
echo.
echo   ⏳ Launching CLI...
echo.
call "%ROOT%\legacy_launchers\start.bat"
set "LAST_EXITCODE=%errorlevel%"
echo.
echo   ✓ CLI session ended (exit code: %LAST_EXITCODE%)
echo.
pause
goto menu

:pyside
cls
echo.
echo   ⏳ Launching PySide6 Desktop UI...
echo.
call "%ROOT%\legacy_launchers\run_pyside_ui.bat"
set "LAST_EXITCODE=%errorlevel%"
echo.
echo   ✓ Desktop UI session ended (exit code: %LAST_EXITCODE%)
echo.
pause
goto menu

rem ============================================================================
rem Exit
rem ============================================================================

:end
cls
echo.
echo   ╔════════════════════════════════════════════════════════════════╗
echo   ║                    JL Engine signing off ✦                    ║
echo   ╚════════════════════════════════════════════════════════════════╝
echo.
popd
exit /b %LAST_EXITCODE%
