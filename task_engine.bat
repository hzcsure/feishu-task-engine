@echo off
chcp 65001 >nul 2>nul
title 飞书任务引擎
python -X utf8 "%~dp0task_engine.py"
pause
