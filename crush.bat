@echo off
setlocal
cd /d "%~dp0"
julia --project=. scripts\crush.jl %*
endlocal
