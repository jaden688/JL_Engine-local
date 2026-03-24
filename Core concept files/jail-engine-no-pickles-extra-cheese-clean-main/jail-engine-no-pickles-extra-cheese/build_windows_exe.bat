@echo off
setlocal
set SCRIPT_DIR=%~dp0
cd /d "%SCRIPT_DIR%"

echo Setting up build environment...
if not exist .venv-win (
    python -m venv .venv-win
)
call .venv-win\Scripts\activate.bat

echo Installing dependencies...
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
python -m pip install pyinstaller

echo Cleaning previous build...
if exist dist rmdir /s /q dist
if exist build rmdir /s /q build
if exist JL_Engine.spec del JL_Engine.spec

echo Building Executable...
:: Add all necessary data folders and files
:: Note: Adapting paths to be relative to this script
pyinstaller --noconfirm --windowed --name "JL_Engine" ^
  --add-data "site;site" ^
  --add-data "framework;framework" ^
  --add-data "docs;docs" ^
  --add-data "personas;personas" ^
  --add-data "models;models" ^
  --add-data "behavior_states.json;." ^
  --add-data "JLframe_Engine_Framework.json;." ^
  --add-data "tts_config.json;." ^
  --collect-all "PySide6" ^
  --collect-all "open_interpreter" ^
  main_app.py

echo Build complete.
echo Output: dist\JL_Engine\JL_Engine.exe
endlocal