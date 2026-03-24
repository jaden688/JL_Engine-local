@echo off
title JL Engine - Production Agentic Mode

:: Run the interactive PowerShell script in the same directory
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0START_PRODUCTION.ps1"

if errorlevel 1 (
    pause
)
