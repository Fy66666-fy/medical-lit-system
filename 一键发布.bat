@echo off
title 医学文献智能摘要系统 - 一键发布
chcp 65001 >nul

REM v2.8.1：解释器查找逻辑与 一键启动.bat 保持一致，
REM 找不到就明确报错，而不是双击后一闪而过。

set "PYTHON="
set "PYEXE=%USERPROFILE%\.workbuddy\binaries\python\envs\default\Scripts\python.exe"
if exist "%PYEXE%" set "PYTHON=%PYEXE%"
if not defined PYTHON if exist "D:\python\python.exe" set "PYTHON=D:\python\python.exe"
if not defined PYTHON for %%P in (python.exe) do (
    if not defined PYTHON if exist "%%~$PATH:P" set "PYTHON=%%~$PATH:P"
)

if not defined PYTHON (
    echo [错误] 没找到可用的 Python 解释器，无法发布。
    echo   已尝试：WorkBuddy 自带环境 -^> D:\python\python.exe -^> PATH 里的 python.exe
    pause
    exit /b 9
)

cd /d "%~dp0"

echo ============================================
echo   一键发布：测试 -^> 改版本 -^> 同步部署目录
echo            -^> 提交打标签 -^> 推送（自动绕行网络问题）
echo ============================================
echo.
echo   常用参数（直接回车使用默认 patch）：
echo     patch    小修（默认）
echo     minor    新功能
echo     major    大版本
echo     nopush   只本地提交，不推远程
echo.
echo   注意：会自动先跑 7 个测试脚本，全通过才会提交。
echo.

set /p PART=发布类型:
if "%PART%"=="" set PART=patch

set /p MSG=发布说明(可留空):

if "%PART%"=="nopush" (
    "%PYTHON%" release.py --bump patch --message "%MSG%" --no-push
) else (
    "%PYTHON%" release.py --bump %PART% --message "%MSG%"
)

echo.
pause