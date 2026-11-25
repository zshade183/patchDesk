@echo off
setlocal
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" goto :setup
if not exist "frontend\dist\index.html" goto :setup
".venv\Scripts\python.exe" -m patchdesk
if errorlevel 1 pause
exit /b

:setup
echo PatchDesk dependencies or frontend build missing. See README.md.
pause
exit /b 1
