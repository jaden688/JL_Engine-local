@echo off
title JL Engine (Python 3.11)

REM Run from the directory this script lives in
cd /d "%~dp0"

echo Starting JL Engine with Python 3.11...
py -3.11 main_app.py
