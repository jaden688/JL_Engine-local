@echo off
echo [1/3] Removing __pycache__ directories...
for /d /r . %%d in (__pycache__) do @if exist "%%d" rd /s /q "%%d"

echo [2/3] Removing PyInstaller build artifacts (build, dist, spec)...
if exist "build" rd /s /q "build"
if exist "dist" rd /s /q "dist"
del /q *.spec >nul 2>&1

echo [3/3] Cleanup complete.
pause