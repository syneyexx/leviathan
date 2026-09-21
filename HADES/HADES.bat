@echo off
setlocal
cd /d "%~dp0"
if not exist "node_modules\.bin\vite.cmd" goto prepare
if not exist "backend\.venv\Scripts\python.exe" goto prepare
goto start

:prepare
call PREPARE_HADES.bat || exit /b 1

:start
"backend\.venv\Scripts\python.exe" "HADES_LAUNCHER.py"
exit /b %errorlevel%
