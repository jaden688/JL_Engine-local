@echo off
setlocal
cd /d "%~dp0"
set "SPARKBYTE_HOST=127.0.0.1"
set "SPARKBYTE_PORT=8081"
set "SPARKBYTE_LAUNCH_BROWSER=1"
echo === JL Engine / SparkByte ===
echo UI: http://127.0.0.1:8081
julia --project=. start.jl
if errorlevel 1 (
  echo.
  echo JL Engine stopped with an error.
  pause
  exit /b 1
)
endlocal
