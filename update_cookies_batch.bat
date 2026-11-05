@echo off
REM update_cookies_batch.bat - 定时更新YouTube cookies
REM 可配合Windows任务计划程序使用
REM
REM 使用方法:
REM   1. 手动双击运行，或
REM   2. 添加到Windows任务计划程序，每天/每周自动执行
REM
REM 说明:
REM   - 优先使用本机 CPython 3.12；不存在时用 py 启动器定位
REM   - 两者均失败则回退到 PATH 中的 python，并明确告警

setlocal EnableExtensions EnableDelayedExpansion
chcp 65001 >nul

cd /d "%~dp0"

REM ---- 定位 Python 解释器 ----
set "PY=%LOCALAPPDATA%\Programs\Python\Python312\python.exe"
if not exist "!PY!" (
    for /f "delims=" %%P in ('py -3.12 -c "import sys;print(sys.executable)" 2^>nul') do set "PY=%%P"
)
if not exist "!PY!" (
    for /f "delims=" %%P in ('where python 2^>nul') do set "PY=%%P"
)
if not exist "!PY!" (
    echo [FAIL] 未找到可用的 Python 解释器，已退出。
    echo        请安装 Python 3.12，或修改本脚本的 PY 变量。
    exit /b 1
)

echo ========================================
echo YouTube Cookies 自动更新
echo %date% %time%
echo 解释器: !PY!
echo ========================================

"!PY!" update_cookies.py
set "RC=!errorlevel!"

echo.
if "!RC!"=="0" (
    echo 更新完成。
) else (
    echo 更新失败，退出码: !RC!
)
echo ========================================

exit /b !RC!
