@echo off
title 医学文献智能摘要系统 - 一键发布
chcp 65001 >nul

set PYTHON=%USERPROFILE%\.workbuddy\binaries\python\envs\default\Scripts\python.exe
if not exist "%PYTHON%" set PYTHON=python

cd /d "%~dp0"

echo ============================================
echo   一键发布：测试 -^> 改版本 -^> 同步部署目录
echo   -^> 提交打标签 -^> 推送
echo ============================================
echo.
echo   常用参数（直接回车使用默认 patch）：
echo     patch  小修（默认，v2.5.0 -^> v2.5.1）
echo     minor  新功能（v2.5.0 -^> v2.6.0）
echo     major  大版本（v2.5.0 -^> v3.0.0）
echo     nopush 只本地提交，不推远程
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
