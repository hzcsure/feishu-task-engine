@echo off
rem ============================================================
rem  feishu-task-engine - environment check (read-only)
rem  Wrapper exists only to bypass PowerShell ExecutionPolicy
rem  (this machine is Restricted, so .ps1 cannot be run directly).
rem
rem  Usage:
rem    check-env.bat              normal report
rem    check-env.bat -Json        machine-readable output
rem    check-env.bat -DryRun      list checks without running them
rem    check-env.bat -Online      also probe network reachability
rem    check-env.bat -PythonPath "C:\...\python.exe"
rem
rem  Exit code: 0 = all OK, 1 = has FAIL, 2 = only WARN
rem ============================================================
setlocal
chcp 65001 >nul

set "PS1=%~dp0scripts\check_env.ps1"
if not exist "%PS1%" (
    echo [FAIL] not found: %PS1%
    exit /b 1
)

powershell -NoProfile -ExecutionPolicy Bypass -File "%PS1%" %*
set "RC=%errorlevel%"

rem ??? pause???????CI??????????
rem ?????????????????????????????
if "%~1"=="" (
    echo.
    echo Tip: window closes on exit. To keep the report on screen, run it from an open cmd window.
)

exit /b %RC%
