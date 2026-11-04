@echo off
rem ============================================================
rem  feishu-task-engine - environment check (read-only)
rem  Wrapper exists only to bypass PowerShell ExecutionPolicy
rem  (this machine is Restricted, so .ps1 cannot be run directly).
rem
rem  Usage:
rem    check-env.bat              normal report
rem    check-env.bat -Json        machine-readable output (never pauses)
rem    check-env.bat -DryRun      list checks without running them
rem    check-env.bat -Online      also probe network reachability
rem    check-env.bat -PythonPath "C:\...\python.exe"
rem    check-env.bat -NoPause     never wait for a key (CI / scheduled task)
rem    check-env.bat -Pause       always wait for a key
rem
rem  Window behaviour:
rem    launched by double-click -> waits for a key, so the report stays visible
rem    run inside an open console -> does not wait (the window never closes)
rem    -Json / -NoPause -> never waits
rem
rem  Exit code: 0 = all OK, 1 = has FAIL, 2 = only WARN
rem ============================================================
setlocal EnableDelayedExpansion
chcp 65001 >nul

rem ---- 1. decide whether the window has to be kept open ------
rem  Double-click starts:  ...\system32\cmd.exe /c ""<path>\check-env.bat" "
rem  so the script name appears in CMDCMDLINE. When the script is typed in
rem  an already open console, CMDCMDLINE holds only the interpreter path.
rem  Read it into a local var first: referencing CMDCMDLINE straight inside
rem  an "if" does not expand reliably under delayed expansion.
set "DO_PAUSE=0"
set "FORCED=0"

for %%A in (%*) do (
    if /i "%%~A"=="-Json"    set "DO_PAUSE=0" & set "FORCED=1"
    if /i "%%~A"=="-NoPause" set "DO_PAUSE=0" & set "FORCED=1"
    if /i "%%~A"=="-Pause"   set "DO_PAUSE=1" & set "FORCED=1"
)

if not "!FORCED!"=="0" goto :pause_decided
set "SELF=%~nx0"
set "CL=!CMDCMDLINE!"
call set "CL_REST=%%CL:!SELF!=%%"
if not "!CL_REST!"=="!CL!" set "DO_PAUSE=1"
:pause_decided

rem ---- 2. run the real check ---------------------------------
set "PS1=%~dp0scripts\check_env.ps1"
set "RC=1"

if not exist "!PS1!" goto :no_script
powershell -NoProfile -ExecutionPolicy Bypass -File "!PS1!" %*
set "RC=!errorlevel!"
goto :maybe_pause

:no_script
echo [FAIL] not found: !PS1!

rem ---- 3. hold the window if needed --------------------------
:maybe_pause
if "!DO_PAUSE!"=="0" goto :done
echo.
echo ------------------------------------------------------------
echo  Exit code: !RC!   ^(0 = OK, 1 = FAIL, 2 = WARN only^)
echo  Press any key to close this window . . .
echo ------------------------------------------------------------
pause >nul

:done
exit /b !RC!
