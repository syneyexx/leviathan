@echo off
setlocal
cd /d "%~dp0"

if not exist "node_modules\.bin\vite.cmd" (
  echo HADES frontend is niet of incompleet voorbereid. PREPARE_HADES.bat wordt gestart.
  call PREPARE_HADES.bat || exit /b 1
)

if not exist "backend\.venv\Scripts\python.exe" (
  echo HADES backend is niet voorbereid. PREPARE_HADES.bat wordt gestart.
  call PREPARE_HADES.bat || exit /b 1
)

start "HADES Backend" /d "%~dp0backend" "%~dp0backend\.venv\Scripts\python.exe" -m uvicorn main:app --host 127.0.0.1 --port 8000
if /I "%HADES_FRONTEND_MODE%"=="dev" goto hades_frontend_dev
if exist "dist\index.html" goto hades_frontend_production
:hades_frontend_dev
start "HADES Frontend" /d "%~dp0" cmd /k npm run dev -- --host 127.0.0.1 --port 3000
goto hades_frontend_started
:hades_frontend_production
start "HADES Frontend" /d "%~dp0" cmd /k npm run start
:hades_frontend_started

echo Wachten tot HADES backend en frontend echt bereikbaar zijn...
"backend\.venv\Scripts\python.exe" "tools\local_startup_health.py"
if errorlevel 1 (
  echo [FOUT] HADES is gestart maar niet als gereed bevestigd.
  echo Controleer de backend- en frontendvensters voor de echte foutmelding.
  exit /b 1
)

echo HADES draait lokaal.
echo Frontend: http://127.0.0.1:3000
echo Backend:  http://127.0.0.1:8000
echo API docs: http://127.0.0.1:8000/docs
exit /b 0
