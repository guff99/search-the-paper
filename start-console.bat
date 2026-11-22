@echo off
cd /d "%~dp0"
title paper-radar console
echo Starting paper-radar console at http://127.0.0.1:8766/
echo Close this window to stop the console.
echo.
".venv\Scripts\python.exe" console.py
pause
