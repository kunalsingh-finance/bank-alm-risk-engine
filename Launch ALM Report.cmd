@echo off
cd /d "%~dp0"
python scripts\build_report.py
if errorlevel 1 exit /b 1
python scripts\verify_release.py
if errorlevel 1 exit /b 1
start "" "%~dp0output\report.html"
