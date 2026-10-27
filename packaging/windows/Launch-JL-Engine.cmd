@echo off
setlocal
for %%I in ("%~dp0..\..") do set "APP_DIR=%%~fI"
if not exist "%APP_DIR%\runtime\bin\julia.exe" (
  echo JL Engine bundled Julia runtime is missing.
  pause
  exit /b 1
)
if not exist "%APP_DIR%\python\python.exe" (
  echo JL Engine bundled Python runtime is missing.
  pause
  exit /b 1
)
set "JULIA_DEPOT_PATH=%APP_DIR%\depot"
set "JULIA_CONDAPKG_BACKEND=Null"
set "JULIA_PYTHONCALL_EXE=%APP_DIR%\python\python.exe"
set "JL_ENGINE_APP_DIR=%APP_DIR%"
cd /d "%APP_DIR%"
echo Starting JL Engine. First launch installs the app-local Julia dependencies.
"%APP_DIR%\runtime\bin\julia.exe" --project="%APP_DIR%" "%APP_DIR%\packaging\windows\launch_engine.jl"
if errorlevel 1 pause
endlocal
