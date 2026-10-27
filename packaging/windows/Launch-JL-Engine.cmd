@echo off
setlocal
rem This script lives under packaging\windows in the installed tree; resolve the app root.
set "APP_DIR=%~dp0..\..\"
set "JULIA_EXE=%APP_DIR%runtime\bin\julia.exe"
if not exist "%JULIA_EXE%" (
  echo JL Engine runtime is missing: "%JULIA_EXE%"
  echo Reinstall JL Engine or contact support with this message.
  pause
  exit /b 1
)
cd /d "%APP_DIR%"
set "JULIA_CONDAPKG_BACKEND=Null"
set "JULIA_PYTHONCALL_EXE=python"
set "JULIA_DEPOT_PATH=%APP_DIR%depot"
set "SPARKBYTE_SKIP_PKG_INSTANTIATE=1"
"%JULIA_EXE%" "%APP_DIR%sparkbyte.jl"
set "EXIT_CODE=%ERRORLEVEL%"
if not "%EXIT_CODE%"=="0" (
  echo.
  echo JL Engine stopped with exit code %EXIT_CODE%.
  pause
)
exit /b %EXIT_CODE%
