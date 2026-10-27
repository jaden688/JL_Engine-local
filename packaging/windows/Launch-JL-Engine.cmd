@echo off
setlocal
rem Resolve the installed application root from packaging\windows.
for %%I in ("%~dp0..\..") do set "APP_DIR=%%~fI"
set "JULIA_EXE=%APP_DIR%\runtime\bin\julia.exe"
set "BUNDLED_PYTHON=%APP_DIR%\python\python.exe"

if not exist "%JULIA_EXE%" (
  echo JL Engine runtime is missing: "%JULIA_EXE%"
  echo Reinstall JL Engine or contact support with this message.
  pause
  exit /b 1
)
if not exist "%BUNDLED_PYTHON%" (
  echo JL Engine bundled Python runtime is missing: "%BUNDLED_PYTHON%"
  echo Reinstall JL Engine or contact support with this message.
  pause
  exit /b 1
)
if not exist "%APP_DIR%\sparkbyte.jl" (
  echo JL Engine entry point is missing: "%APP_DIR%\sparkbyte.jl"
  pause
  exit /b 1
)

cd /d "%APP_DIR%"
set "JULIA_PROJECT=%APP_DIR%"
set "JULIA_CONDAPKG_BACKEND=Null"
set "JULIA_PYTHONCALL_EXE=%BUNDLED_PYTHON%"
set "JULIA_DEPOT_PATH=%APP_DIR%\depot"
set "SPARKBYTE_SKIP_PKG_INSTANTIATE=1"
set "PATH=%APP_DIR%\python;%APP_DIR%\python\DLLs;%PATH%"
"%JULIA_EXE%" "%APP_DIR%\sparkbyte.jl"
set "EXIT_CODE=%ERRORLEVEL%"
if not "%EXIT_CODE%"=="0" (
  echo.
  echo JL Engine stopped with exit code %EXIT_CODE%.
  pause
)
exit /b %EXIT_CODE%
