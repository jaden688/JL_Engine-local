@echo off
setlocal enableextensions
pushd "%~dp0"

set "SCRIPT_DIR=%CD%"
for %%I in ("%SCRIPT_DIR%\..") do set "ROOT=%%~fI"
set "VENV_DIR=%ROOT%\.venv"
set "VENV_PYTHON=%VENV_DIR%\Scripts\python.exe"
set "BOOTSTRAP_PYTHON="
set "BOOTSTRAP_ARGS="
set "ACTIVE_PYTHON="
set "ACTIVE_ARGS="
set "USE_VENV=0"  REM fully disable local virtualenv usage for this project

call :resolve_python
if errorlevel 1 goto :fail

REM Force using system interpreter; ignore JL_PLATFORM_USE_VENV
REM if /I "%JL_PLATFORM_USE_VENV%"=="1" set "USE_VENV=1"
REM if /I "%JL_PLATFORM_USE_VENV%"=="true" set "USE_VENV=1"
REM if /I "%JL_PLATFORM_USE_VENV%"=="yes" set "USE_VENV=1"
REM if /I "%JL_PLATFORM_USE_VENV%"=="on" set "USE_VENV=1"

if "%USE_VENV%"=="1" (
    if not exist "%VENV_PYTHON%" (
        echo [JL Engine] Creating local virtual environment...
        "%BOOTSTRAP_PYTHON%" %BOOTSTRAP_ARGS% -m venv "%VENV_DIR%"
        if errorlevel 1 goto :fail
    )
    set "ACTIVE_PYTHON=%VENV_PYTHON%"
    set "ACTIVE_ARGS="
) else (
    set "ACTIVE_PYTHON=%BOOTSTRAP_PYTHON%"
    set "ACTIVE_ARGS=%BOOTSTRAP_ARGS%"
)

echo [JL Engine] Installing runtime dependencies...
"%ACTIVE_PYTHON%" %ACTIVE_ARGS% -m pip install --disable-pip-version-check --upgrade pip
if errorlevel 1 goto :fail

"%ACTIVE_PYTHON%" %ACTIVE_ARGS% -m pip install --disable-pip-version-check -e ".[api]"
if errorlevel 1 goto :fail

if "%USE_VENV%"=="1" (
    set "PATH=%VENV_DIR%\Scripts;%PATH%"
)

echo [JL Engine] Launching standalone command deck...
call "%SCRIPT_DIR%\run_command_deck.bat" %*
set "EXITCODE=%errorlevel%"
goto :end

:resolve_python
where py >nul 2>nul
if not errorlevel 1 (
    set "BOOTSTRAP_PYTHON=py"
    set "BOOTSTRAP_ARGS=-3"
    exit /b 0
)

where python >nul 2>nul
if not errorlevel 1 (
    set "BOOTSTRAP_PYTHON=python"
    set "BOOTSTRAP_ARGS="
    exit /b 0
)

echo [JL Engine] Python 3 was not found.
echo Install Python 3.10+ and then run this file again.
exit /b 1

:fail
set "EXITCODE=%errorlevel%"
echo.
echo [JL Engine] Startup failed.
echo Press any key to exit...
pause >nul

:end
popd
exit /b %EXITCODE%
