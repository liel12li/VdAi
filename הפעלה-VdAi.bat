@echo off
chcp 65001 >nul
title VdAi
cd /d "%~dp0"

rem Try the Windows Python launcher first, then plain python.
where py >nul 2>nul
if %errorlevel%==0 (
    py run.py %*
) else (
    python run.py %*
)

if errorlevel 1 pause
