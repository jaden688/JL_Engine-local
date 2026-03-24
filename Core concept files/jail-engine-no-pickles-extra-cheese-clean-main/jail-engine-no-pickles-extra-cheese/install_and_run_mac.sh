#!/bin/bash
set -euo pipefail

# =================================================
#      JL Engine - Installer and Launcher for macOS
# =================================================
echo ""

# Change directory to the location of this script to ensure all paths are correct.
cd "$(dirname "$0")"

echo "[STEP 1] Checking prerequisites..."
echo ""

if ! command -v python3 >/dev/null 2>&1; then
  echo " - python3 not found. Install Python 3.10+ and rerun this script."
  exit 1
fi

if ! command -v ollama >/dev/null 2>&1; then
  echo " - ollama not found. Install Ollama and rerun this script."
  echo "   https://ollama.com/"
  exit 1
fi

echo "[STEP 2] Setting up a local virtual environment..."
if [ ! -d ".venv" ]; then
  python3 -m venv .venv
fi

echo ""
echo "[STEP 3] Installing Python dependencies..."
./.venv/bin/python -m pip install --upgrade pip
./.venv/bin/python -m pip install -r requirements.txt

echo ""
echo "[STEP 4] Starting the Ollama server..."
echo " - A new Terminal window for the Ollama server will open. Please keep it running."

# Use AppleScript to open a new Terminal window and run the server
osascript -e 'tell application "Terminal" to do script "ollama serve"'

echo ""
echo "[STEP 5] Waiting for Ollama to initialize (10 seconds)..."
sleep 10

echo ""
echo "[STEP 6] Starting the JL Engine application..."
./.venv/bin/python main_app.py
