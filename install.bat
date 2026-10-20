@echo off
setlocal enabledelayedexpansion
cd /d "%~dp0"

echo ========================================
echo   JL Engine - SparkByte Setup
echo ========================================

:: Check Julia
julia --version >nul 2>&1
if %errorlevel% neq 0 (
    echo [ERROR] Julia not found. Please install Julia from https://julialang.org/
    pause
    exit /b 1
)

:: Check Python
python --version >nul 2>&1
if %errorlevel% neq 0 (
    echo [ERROR] Python not found. Please install Python 3.10+ from https://python.org/
    pause
    exit /b 1
)

echo [1/3] Instantiating Julia project dependencies...
julia --project=. -e "import Pkg; Pkg.instantiate()"
if %errorlevel% neq 0 (
    echo [ERROR] Julia package instantiation failed.
    pause
    exit /b 1
)

echo [2/3] Installing Python dependencies...
if exist requirements.txt (
    python -m pip install -r requirements.txt
) else (
    echo [INFO] No requirements.txt found, skipping python package install.
)

echo [3/3] Setting up environment configuration...
if not exist .env (
    if exist .env.example (
        copy .env.example .env >nul
        echo [INFO] Created .env from .env.example
    ) else (
        echo [WARN] .env.example not found. Please create a .env file manually.
    )
) else (
    echo [INFO] .env already exists.
)

echo.
echo ========================================
echo   Installation Complete
echo ========================================
echo Run start.bat to launch the engine.
pause
endlocal
