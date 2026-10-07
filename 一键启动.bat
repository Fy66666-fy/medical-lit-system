@echo off
title 医学文献智能摘要系统 - 一键启动
chcp 65001 >nul

REM ---------------------------------------------------------------
REM 解释器选择：先用 WorkBuddy 自带环境，再退到系统 python / py / D:\python
REM v2.8.1：以前只认 WorkBuddy 环境，找不到就退化成裸 python，
REM 而本机 PATH 里没有 python，导致双击后一闪而过、什么都没发生。
REM ---------------------------------------------------------------
set "PYTHON="
set "PYEXE=%USERPROFILE%\.workbuddy\binaries\python\envs\default\Scripts\python.exe"
if exist "%PYEXE%" set "PYTHON=%PYEXE%"

if not defined PYTHON if exist "D:\python\python.exe" set "PYTHON=D:\python\python.exe"

if not defined PYTHON (
    for %%P in (python.exe) do (
        if not defined PYTHON if exist "%%~$PATH:P" set "PYTHON=%%~$PATH:P"
    )
)

if not defined PYTHON (
    echo [错误] 没找到可用的 Python 解释器。
    echo.
    echo   已尝试：WorkBuddy 自带环境 -^> D:\python\python.exe -^> PATH 里的 python.exe
    echo.
    echo   解决办法（任选其一）：
    echo     1) 安装 Python 3.10+ 并勾选 "Add to PATH"，然后重新双击本文件
echo     2) 打开 PowerShell 执行：  pip install -r requirements.txt
echo        再回到本目录用本文件启动
    echo.
    pause
    exit /b 9
)

cd /d "%~dp0"

echo ============================================
echo   医学文献智能摘要系统
echo   就绪后自动打开 http://localhost:8501
echo   按 Ctrl+C 或关闭本窗口即可停止服务
echo ============================================
echo.

REM v2.8.1：端口被占用时 launch.py 会自动判断：是自己就复用，是别人就换端口，不再直接失败。
REM 要重启服务请先双击 一键停止.bat（或运行 python stop.py）。
"%PYTHON%" launch.py --port 8501

echo.
echo 服务已停止。
pause