@echo off
setlocal EnableExtensions
cd /d "%~dp0"
title LEVIATHAN

REM Relocatable: ensure Data.* imports resolve from this install root on any drive.
set "PYTHONPATH=%~dp0"
set "PY=.venv\Scripts\python.exe"
set "LOG=%~dp0leviathan_startup.log"

echo [%DATE% %TIME%] LEVIATHAN start > "%LOG%"

if not exist "%PY%" (
  echo [LEVIATHAN] Not installed yet.
  echo Run installer.bat first.
  echo [%DATE% %TIME%] Missing .venv\Scripts\python.exe >> "%LOG%"
  goto :fail
)

if not exist "Data\frontend\dist\index.html" (
  echo [LEVIATHAN] Frontend build missing.
  echo Run installer.bat first ^(or: cd Data\frontend ^&^& npm run build^).
  echo [%DATE% %TIME%] Missing Data\frontend\dist\index.html >> "%LOG%"
  goto :fail
)

if not exist ".env" (
  if exist ".env.example" (
    copy /Y ".env.example" ".env" >nul
    echo [LEVIATHAN] Created .env from .env.example
  ) else (
    echo [LEVIATHAN] Missing .env and .env.example
    echo [%DATE% %TIME%] Missing .env and .env.example >> "%LOG%"
    goto :fail
  )
)

echo [LEVIATHAN] Checking Python packages...
"%PY%" -c "import fastapi, uvicorn" >> "%LOG%" 2>&1
if errorlevel 1 (
  echo [LEVIATHAN] Required packages missing or broken ^(fastapi/uvicorn^).
  echo Run installer.bat again.
  echo See leviathan_startup.log for details.
  goto :fail
)

echo [LEVIATHAN] Checking app import...
"%PY%" -c "from Data.backend.main import app" >> "%LOG%" 2>&1
if errorlevel 1 (
  echo [LEVIATHAN] Failed to import Data.backend.main:app
  echo See leviathan_startup.log for the Python traceback.
  type "%LOG%"
  goto :fail
)

echo [LEVIATHAN] Starting via leviathan.py (host/port from settings)
echo [LEVIATHAN] Keep this window open. Press Ctrl+C to stop.
echo [LEVIATHAN] Heavy jobs: use run_leviathan_workers.bat for external Worker Supervisor
echo [LEVIATHAN] ^(unless workers are already autostarted via leviathan.py bootstrap^).
echo.

REM Optional: when LEVIATHAN_SOURCE_INGESTION_RUNNER=external, start the shared
REM source-ingestion worker in a second window (same DB; do not double inprocess).
findstr /B /C:"LEVIATHAN_SOURCE_INGESTION_RUNNER=external" ".env" >nul 2>&1
if not errorlevel 1 (
  echo [LEVIATHAN] Starting source ingestion worker ^(external mode^)
  start "LEVIATHAN Source Ingestion" /D "%~dp0" "%PY%" scripts\source_ingestion_worker.py
)

REM Optional autostart of full Worker Supervisor when configured.
findstr /B /C:"LEVIATHAN_WORKERS_AUTOSTART=1" ".env" >nul 2>&1
if not errorlevel 1 (
  echo [LEVIATHAN] Autostarting Worker Supervisor ^(LEVIATHAN_WORKERS_AUTOSTART=1^)
  start "LEVIATHAN Workers" /D "%~dp0" "%~dp0run_leviathan_workers.bat"
)

"%PY%" leviathan.py
set "EXITCODE=%ERRORLEVEL%"

if not "%EXITCODE%"=="0" (
  echo.
  echo [LEVIATHAN] Server exited with error code %EXITCODE%.
  echo [%DATE% %TIME%] uvicorn exit code %EXITCODE% >> "%LOG%"
  echo If the traceback scrolled away, re-run this file from a Command Prompt:
  echo   cd /d "%~dp0"
  echo   run_leviathan.bat
  echo Or open leviathan_startup.log after the preflight checks above.
  goto :fail
)

exit /b 0

:fail
echo.
echo ============================================
echo   LEVIATHAN failed to start
echo ============================================
echo This window stays open so you can read the error.
echo.
pause
exit /b 1
