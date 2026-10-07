@echo off
title 医学文献智能摘要系统 - 一键停止
chcp 65001 >nul

set "PYEXE=%USERPROFILE%\.workbuddy\binaries\python\envs\default\Scripts\python.exe"
if not exist "%PYEXE%" set "PYEXE=D:\python\python.exe"
if not exist "%PYEXE%" set "PYEXE=python"

cd /d "%~dp0"

echo ============================================
echo   停止本地服务
echo ============================================
echo.

"%PYEXE%" stop.py --port 8501 --all

echo.
pause