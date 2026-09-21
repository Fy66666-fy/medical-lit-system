@echo off
title Medical Literature System - One Click Start
chcp 65001 >nul

set PYTHON=%USERPROFILE%\.workbuddy\binaries\python\envs\default\Scripts\python.exe
set PORT=8501

if not exist "%PYTHON%" (
    echo [INFO] WorkBuddy python env not found, trying system python...
    set PYTHON=python
)

cd /d "%~dp0"

echo ============================================
echo   Medical Literature Summary ^& Search System
echo   Starting at http://localhost:%PORT%
echo   Press Ctrl+C in this window to stop.
echo ============================================
echo.

start "" cmd /c "timeout /t 4 >nul & start http://localhost:%PORT%"

"%PYTHON%" -m streamlit run app.py --server.port %PORT% --server.address localhost --server.headless true --browser.gatherUsageStats false

echo.
echo Server stopped.
pause
