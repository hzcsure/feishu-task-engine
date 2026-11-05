@echo off
rem ============================================================
rem  Install project deps to LOCAL system CPython (--user)
rem
rem  变更说明：
rem   1. [P0] 移除硬编码用户名，改用 %LOCALAPPDATA% 锚定；
rem   2. [P1] 默认 3.12 路径不存在时，用 py 启动器兜底；
rem   3. [P1] 仍失败时，自动枚举系统候选 Python 供用户选择；
rem   4. [P1] 校验 requirements.txt 是否存在；
rem   5. [P2] 启用延迟展开，errorlevel 在 if 前独立捕获；
rem   6. [P2] 设置 UTF-8 代码页，避免中文输出乱码。
rem ============================================================
setlocal EnableExtensions EnableDelayedExpansion
chcp 65001 >nul

set "CAND=%TEMP%\install_deps_candidates.txt"
if exist "%CAND%" del /q "%CAND%" >nul 2>nul

rem ---- 1. 首选：默认路径的 CPython 3.12 ------------------------
set "PY=%LOCALAPPDATA%\Programs\Python\Python312\python.exe"

rem ---- 2. 兜底：py 启动器定位 3.12 ----------------------------
if not exist "%PY%" (
    echo [WARN] 未在默认路径找到 CPython 3.12，尝试 py 启动器...
    for /f "delims=" %%P in ('py -3.12 -c "import sys;print(sys.executable)" 2^>nul') do set "PY=%%P"
)

rem ---- 3. 仍失败：枚举候选并让用户选择 ------------------------
if not exist "%PY%" call :pick_python

if not exist "%PY%" (
    echo.
    echo [FAIL] 未选择有效的 Python 解释器，已退出。
    pause
    exit /b 1
)

rem ---- 4. verify requirements.txt -----------------------------
if not exist "%~dp0requirements.txt" (
    echo [FAIL] 未找到 requirements.txt：%~dp0requirements.txt
    pause
    exit /b 1
)

echo ============================================================
echo  Install project deps to LOCAL system CPython (--user)
echo  Target: %PY%
echo ============================================================
echo.

rem ---- 5. upgrade pip -----------------------------------------
echo [1/3] Upgrade pip...
"%PY%" -m pip install --user --upgrade pip
set "RC=!errorlevel!"
if not "!RC!"=="0" (
    echo [FAIL] pip upgrade failed ^(exit !RC!^)
    pause
    exit /b 1
)

rem ---- 6. install requirements.txt ----------------------------
echo [2/3] Install requirements.txt (pywin32, pyautogui, pillow, psutil, opencv, etc.)...
"%PY%" -m pip install --user -r "%~dp0requirements.txt"
set "RC=!errorlevel!"
if not "!RC!"=="0" (
    echo [FAIL] requirements install failed ^(exit !RC!^)
    pause
    exit /b 1
)

rem ---- 7. install yt-dlp + ffmpeg -----------------------------
echo [3/3] Install yt-dlp and ffmpeg binary...
"%PY%" -m pip install --user yt-dlp imageio-ffmpeg
set "RC=!errorlevel!"
if not "!RC!"=="0" (
    echo [WARN] yt-dlp / imageio-ffmpeg install failed ^(exit !RC!^), you can retry manually
)

echo.
echo ============================================================
echo  Done. Dependencies installed to user site-packages.
echo.
echo  Run scripts with the SAME python, e.g.:
echo    "%PY%" run_workflow.py
echo.
echo  OPTIONAL (only needed for update_cookies.py):
echo    "%PY%" -m playwright install chromium
echo ============================================================
echo.
pause
exit /b 0

rem ============================================================
rem  pick_python：枚举候选 Python，编号展示，用户输入选择
rem ============================================================
:pick_python
echo.
echo [WARN] 无法自动定位 CPython 3.12，正在扫描本机已安装的 Python 环境...
echo.

rem 候选来源 A：%LOCALAPPDATA%\Programs\Python\Python*\python.exe
for /d %%D in ("%LOCALAPPDATA%\Programs\Python\Python*") do (
    if exist "%%D\python.exe" echo %%D\python.exe>>"%CAND%"
)

rem 候选来源 B：WorkBuddy 管理的 Python（3.13 等）
for /d %%D in ("%USERPROFILE%\.workbuddy\binaries\python\versions\*") do (
    if exist "%%D\python.exe" echo %%D\python.exe>>"%CAND%"
)

rem 候选来源 C：where python 命中的路径
for /f "delims=" %%P in ('where python 2^>nul') do (
    echo %%P>>"%CAND%"
)

rem 去重并过滤掉 .cmd/.bat 包装脚本，只保留 python.exe
if exist "%CAND%" (
    sort "%CAND%" > "%CAND%.sorted" 2>nul
    del /q "%CAND%" >nul 2>nul
    set "PREV="
    for /f "delims=" %%L in ('type "%CAND%.sorted" 2^>nul') do (
        set "LINE=%%L"
        if /i "!LINE:~-4!"==".exe" if not "!LINE!"=="!PREV!" echo !LINE!>>"%CAND%"
        set "PREV=!LINE!"
    )
    del /q "%CAND%.sorted" >nul 2>nul
)

if not exist "%CAND%" (
    echo   未在常见位置发现任何 Python。请安装后重试，或手动设置。
    set "PY="
    goto :eof
)

rem 编号展示
echo   可选的 Python 解释器：
echo.
set /a "IDX=0"
for /f "delims=" %%L in ('type "%CAND%"') do (
    set /a "IDX+=1"
    echo   [!IDX!] %%L
)
echo   [0] 退出，稍后手动处理
echo.
set /p "CHOICE=请输入序号（默认 1）："
if not defined CHOICE set "CHOICE=1"

if "%CHOICE%"=="0" (
    set "PY="
    goto :eof
)

rem 校验输入是否为纯数字
echo %CHOICE%| findstr /r "^[0-9][0-9]*$" >nul
if errorlevel 1 (
    echo [FAIL] 输入无效，已退出。
    set "PY="
    goto :eof
)

set /a "IDX=0"
set "PY="
for /f "delims=" %%L in ('type "%CAND%"') do (
    set /a "IDX+=1"
    if "!IDX!"=="%CHOICE%" set "PY=%%L"
)

if not defined PY (
    echo [FAIL] 序号超出范围，已退出。
    goto :eof
)

if not exist "%PY%" (
    echo [FAIL] 所选路径不存在：%PY%
    set "PY="
    goto :eof
)

echo.
echo [OK] 已选择：%PY%
goto :eof
