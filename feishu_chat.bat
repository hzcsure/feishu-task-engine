@echo off
chcp 65001 >nul 2>nul
python -X utf8 "%~dp0feishu_send.py" %*
