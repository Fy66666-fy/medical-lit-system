@echo off
title 医学文献智能摘要系统 - 一键启动
chcp 65001 >nul

set PYTHON=%USERPROFILE%\.workbuddy\binaries\python\envs\default\Scripts\python.exe
set PORT=8501

if not exist "%PYTHON%" (
    echo [INFO] 未找到 WorkBuddy Python 环境，改用系统 python...
    set PYTHON=python
)

cd /d "%~dp0"

echo ============================================
echo   医学文献智能摘要系统
echo   就绪后自动打开 http://localhost:%PORT%
echo   按 Ctrl+C 或关闭本窗口即可停止服务
echo ============================================
echo.

REM v2.5.0：改由 launch.py 轮询端口真实就绪后再打开浏览器。
REM 旧版固定 timeout /t 4 太乐观，浏览器常打到尚未监听的端口，
REM 表现为一直转圈 / "连接很慢"，实际是服务还没起来。
"%PYTHON%" launch.py --port %PORT%

echo.
echo 服务已停止。
pause
