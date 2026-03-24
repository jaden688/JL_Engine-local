#!/bin/bash

# =================================================
#      JL Engine - Installer and Launcher for macOS
# =================================================
echo ""

# Change directory to the location of this script to ensure all paths are correct.
cd "$(dirname "$0")"

echo "[STEP 1] Checking for required Python packages..."
echo ""

# --- Check for 'requests' package ---
if ! python3 -m pip show requests > /dev/null 2>&1; then
    echo " - 'requests' not found. Installing now..."
    python3 -m pip install requests
else
    echo " - 'requests' is already installed."
fi

# --- Check for 'tkinterdnd2' package ---
if ! python3 -m pip show tkinterdnd2 > /dev/null 2>&1; then
    echo " - 'tkinterdnd2' not found. Installing now..."
    python3 -m pip install tkinterdnd2
else
    echo " - 'tkinterdnd2' is already installed."
fi

echo ""
echo "[STEP 2] Starting the Ollama server..."
echo " - A new Terminal window for the Ollama server will open. Please keep it running."

# Use AppleScript to open a new Terminal window and run the server
osascript -e 'tell application "Terminal" to do script "ollama serve"'

echo ""
echo "[STEP 3] Waiting for Ollama to initialize (10 seconds)..."
sleep 10

echo ""
echo "[STEP 4] Starting the JL Engine application..."
python3 main_app.py