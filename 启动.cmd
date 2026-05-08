@echo off
chcp 65001 >nul
title Ebook PDF Downloader

set SCRIPT_DIR=%~dp0
cd /d "%SCRIPT_DIR%"

if exist "dist\ebook-pdf-downloader.exe" (
    echo Starting Ebook PDF Downloader...
    start "" "dist\ebook-pdf-downloader.exe" --no-browser
    echo Waiting for server...
    set /a RETRY=0
    :wait
    timeout /t 1 /nobreak >nul
    set /a RETRY+=1
    powershell -NoProfile -Command "try { $r = Invoke-WebRequest 'http://localhost:8000/api/v1/health' -UseBasicParsing -TimeoutSec 1; exit 0 } catch { exit 1 }" >nul 2>&1
    if errorlevel 1 (
        if %RETRY% LSS 15 goto :wait
        echo Server failed to start after 15 seconds.
        echo Check if port 8000 is already in use or blocked by firewall.
        pause
    ) else (
        echo Server ready. Opening browser...
        start http://localhost:8000
    )
) else if exist "backend\dist\ebook-pdf-downloader.exe" (
    echo Using development build...
    start "" "backend\dist\ebook-pdf-downloader.exe" --no-browser
    echo Waiting for server...
    set /a RETRY=0
    :wait2
    timeout /t 1 /nobreak >nul
    set /a RETRY+=1
    powershell -NoProfile -Command "try { $r = Invoke-WebRequest 'http://localhost:8000/api/v1/health' -UseBasicParsing -TimeoutSec 1; exit 0 } catch { exit 1 }" >nul 2>&1
    if errorlevel 1 (
        if %RETRY% LSS 15 goto :wait2
        echo Server failed to start after 15 seconds.
        pause
    ) else (
        echo Server ready. Opening browser...
        start http://localhost:8000
    )
) else (
    echo ebook-pdf-downloader.exe not found!
    echo Please run: python release.py 1.4.0
    pause
)
