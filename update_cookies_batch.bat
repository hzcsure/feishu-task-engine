@echo off
REM update_cookies_batch.bat - 定时更新YouTube cookies
REM 可配合Windows任务计划程序使用
REM
REM 使用方法:
REM   1. 手动双击运行，或
REM   2. 添加到Windows任务计划程序，每天/每周自动执行

cd /d "%~dp0"

REM 设置Python路径（使用managed Python）
set PYTHON=python

echo ========================================
echo YouTube Cookies 自动更新
echo %date% %time%
echo ========================================

"%PYTHON%" update_cookies.py

echo.
echo 更新完成，退出码: %errorlevel%
echo ========================================
