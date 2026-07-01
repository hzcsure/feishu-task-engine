@echo off
chcp 65001 >nul
title 项目依赖一键安装

echo ============================================
echo  飞书任务引擎 - 依赖一键安装脚本
echo ============================================
echo.

REM ---------- 1. Python 第三方包 ----------
echo [1/4] 安装 Python 依赖包...
pip install -r "%~dp0requirements.txt"
if %errorlevel% neq 0 (
    echo   [失败] pip install 出错，请检查网络或手动重试
    pause
    exit /b 1
)
echo   [完成] Python 依赖包安装成功
echo.

REM ---------- 2. yt-dlp ----------
echo [2/4] 安装 yt-dlp（YouTube 下载引擎）...
pip install yt-dlp
if %errorlevel% neq 0 (
    echo   [警告] yt-dlp 安装失败，可手动执行: pip install yt-dlp
) else (
    echo   [完成] yt-dlp 安装成功
)
echo.

REM ---------- 3. ffmpeg ----------
echo [3/4] 安装 ffmpeg（视频转码引擎）...
pip install imageio-ffmpeg
if %errorlevel% neq 0 (
    echo   [警告] ffmpeg 安装失败，可手动执行: pip install imageio-ffmpeg
) else (
    echo   [完成] ffmpeg 安装成功
)
echo.

REM ---------- 4. Playwright + Chromium ----------
echo [4/4] 安装 Playwright 浏览器（用于更新 YouTube cookies）...
pip install playwright
if %errorlevel% equ 0 (
    echo   正在下载 Chromium 浏览器（约 200MB，首次较慢）...
    python -m playwright install chromium
    if %errorlevel% equ 0 (
        echo   [完成] Playwright + Chromium 安装成功
    ) else (
        echo   [警告] Chromium 浏览器下载失败，可手动执行: python -m playwright install chromium
    )
) else (
    echo   [跳过] playwright 安装失败，跳过浏览器下载
)
echo.

REM ---------- 完成 ----------
echo ============================================
echo  全部安装完成！
echo.
echo  剩余需要手动配置的项目：
echo    1. 飞书 lark-cli 登录认证（参见飞书连接器配置）
echo    2. 运行 update_cookies.py 获取 YouTube cookies
echo    3. 配置 yt_config.json 中的工具路径和代理
echo    4. 人工登录微信视频号并保持窗口打开
echo ============================================
echo.
pause
