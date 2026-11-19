@echo off
chcp 65001 >nul
cd /d "%~dp0"
set PYTHONUTF8=1
".runtime-venv\Scripts\python.exe" login-local.py
pause
