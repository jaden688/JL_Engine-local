@echo off
setlocal
cd /d "%~dp0"
echo ========================================
echo   Booting JL Engine - SparkByte
echo ========================================
echo.
julia --project=. sparkbyte.jl
echo.
echo Engine stopped.
pause
endlocal
