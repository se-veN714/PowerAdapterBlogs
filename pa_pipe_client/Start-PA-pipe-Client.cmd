@echo off
setlocal
cd /d "%~dp0"
start "PA-pipe Client" /min powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0run.ps1"
timeout /t 2 /nobreak >nul
start "" "http://127.0.0.1:8744"
