@echo off
chcp 65001 >nul 2>&1
title Carimans AI Assistant - Setup

:: Request admin elevation if not already running as admin
net session >nul 2>&1
if %errorlevel% neq 0 (
    echo Requesting administrator permissions...
    powershell.exe -NoProfile -Command "Start-Process -Verb RunAs -FilePath '%~f0'"
    exit /b
)

echo.
echo ============================================
echo   Carimans AI Assistant - Setup
echo ============================================
echo.

:: Check if Claude Desktop is installed (standard or Windows Store/MSIX path)
set CLAUDE_FOUND=0
if exist "%APPDATA%\Claude" set CLAUDE_FOUND=1
if %CLAUDE_FOUND%==0 (
    for /d %%d in ("%LOCALAPPDATA%\Packages\Claude_*") do set CLAUDE_FOUND=1
)
if %CLAUDE_FOUND%==0 (
    echo [ERROR] Claude Desktop does not appear to be installed.
    echo.
    echo Please install Claude Desktop first from:
    echo   https://claude.ai/download
    echo.
    echo After installing and opening it at least once, run this setup again.
    echo.
    pause
    exit /b 1
)

echo [1/3] Running MCP configuration updater...
echo.
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0updater.ps1"
if %errorlevel% neq 0 (
    echo.
    echo [ERROR] Configuration update failed.
    echo Check the log at: %TEMP%\carimans-mcp-connectors-updater.log
    echo.
    pause
    exit /b 1
)

echo.
echo [2/3] Registering auto-updater scheduled task...
echo.
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0register-task.ps1"
if %errorlevel% neq 0 (
    echo.
    echo [WARNING] Could not register scheduled task.
    echo The MCP servers are configured, but auto-updates won't run.
    echo You can re-run this installer later to try again.
    echo.
)

echo.
echo [3/3] Done!
echo.
echo ============================================
echo   Carimans AI Assistant is now configured.
echo   Claude Desktop will restart automatically.
echo ============================================
echo.
echo If Claude doesn't restart, open it manually.
echo Future MCP updates will be applied automatically.
echo.
pause
