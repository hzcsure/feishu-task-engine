@echo off
setlocal
set PY=C:\Users\lm\AppData\Local\Programs\Python\Python312\python.exe

echo ============================================================
echo  Install project deps to LOCAL system CPython 3.12 (--user)
echo  Target: %PY%
echo ============================================================
echo.

echo [1/3] Upgrade pip...
"%PY%" -m pip install --user --upgrade pip
if %errorlevel% neq 0 (
    echo [FAIL] pip upgrade failed
    pause
    exit /b 1
)

echo [2/3] Install requirements.txt (pywin32, pyautogui, pillow, psutil, opencv, etc.)...
"%PY%" -m pip install --user -r "%~dp0requirements.txt"
if %errorlevel% neq 0 (
    echo [FAIL] requirements install failed
    pause
    exit /b 1
)

echo [3/3] Install yt-dlp and ffmpeg binary...
"%PY%" -m pip install --user yt-dlp imageio-ffmpeg
if %errorlevel% neq 0 (
    echo [WARN] yt-dlp / imageio-ffmpeg install failed, you can retry manually
)

echo.
echo ============================================================
echo  Done. Dependencies installed to user site-packages of 3.12.
echo.
echo  Run scripts with the SAME python, e.g.:
echo    "%PY%" run_workflow.py
echo.
echo  OPTIONAL (only needed for update_cookies.py):
echo    "%PY%" -m playwright install chromium
echo ============================================================
echo.
pause
