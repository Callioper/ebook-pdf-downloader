@echo off
chcp 65001 >nul
title Book Downloader

set SCRIPT_DIR=%~dp0
cd /d "%SCRIPT_DIR%"

if exist "backend\dist\BookDownloader.exe" (
    echo Starting Book Downloader...
    start "" "backend\dist\BookDownloader.exe"
    timeout /t 3 /nobreak >nul
    start http://localhost:8000
) else (
    echo BookDownloader.exe not found!
    echo Please run build_exe.py first or place the exe in backend\dist\
    pause
)
