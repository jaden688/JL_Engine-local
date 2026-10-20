@echo off
title SparkByte EXE Builder
color 0A

echo.
echo  ==========================================
echo   SPARKBYTE ^| Building standalone .exe
echo  ==========================================
echo.
echo  This will take 10-30 minutes.
echo  Do NOT close this window.
echo.

:: Prevent PythonCall from trying to install Conda during build
set JULIA_CONDAPKG_BACKEND=Null
set JULIA_PYTHONCALL_EXE=python
set SPARKBYTE_SKIP_PKG_INSTANTIATE=1

cd /d "%~dp0.."
julia scripts\build_exe.jl

if %ERRORLEVEL% NEQ 0 (
    echo.
    echo  [ERROR] Build failed. Check output above.
    pause
    exit /b 1
)

echo.
echo  Zipping snapshot...
for /f "tokens=*" %%d in ('dir /b /od /ad build\sparkbyte-*') do set LAST_BUILD=%%d
powershell -NoProfile -Command "Compress-Archive -Path 'build\%LAST_BUILD%\*' -DestinationPath 'build\%LAST_BUILD%.zip' -Force"

if %ERRORLEVEL% EQU 0 (
    echo  Zip: build\%LAST_BUILD%.zip
) else (
    echo  (Zip skipped — distribute the build\%LAST_BUILD%\ folder directly)
)

echo.
echo  Done!
echo  Exe:  build\%LAST_BUILD%\bin\sparkbyte.exe
echo  Zip:  build\%LAST_BUILD%.zip
echo.
pause
