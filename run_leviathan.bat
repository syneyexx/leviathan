@echo off
setlocal EnableExtensions
cd /d "%~dp0"
title LEVIATHAN

REM Canonical operator path is run_leviathan.exe when it has been built.
REM LEVIATHAN_LEGACY_CONSOLE=1 keeps this console launcher for recovery.
if /I not "%LEVIATHAN_LEGACY_CONSOLE%"=="1" (
  if exist "%~dp0run_leviathan.exe" (
    start "" "%~dp0run_leviathan.exe"
    exit /b 0
  )
  if exist "%~dp0dist\run_leviathan.exe" (
    start "" "%~dp0dist\run_leviathan.exe"
    exit /b 0
  )
  echo [LEVIATHAN] run_leviathan.exe was not found. Using the legacy console path.
  echo [LEVIATHAN] Set LEVIATHAN_LEGACY_CONSOLE=1 to force this path after the exe exists.
)

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
echo [LEVIATHAN] WorkerSupervisor: owned by leviathan.py bootstrap when WORKERS_ENABLED=true
echo [LEVIATHAN] Manual recovery path: run_leviathan_workers.bat (singleton lease — never dual-own)
echo.

REM Source Ingestion production owner is Worker Fabric (source_ingestion pool).
REM Do NOT autostart the legacy standalone worker when Worker Supervisor is enabled.
REM Deprecated: LEVIATHAN_SOURCE_INGESTION_RUNNER=external means fabric ownership,
REM not "start scripts\source_ingestion_worker.py".
REM
REM Dual-supervisor mitigation:
REM   leviathan.py (default) already starts API + WorkerSupervisor under a lease.
REM   LEVIATHAN_WORKERS_AUTOSTART=1 is LEGACY recovery for API-only mode.
REM   Prefer NOT spawning a second supervisor window when bootstrap already owns it.
findstr /B /C:"LEVIATHAN_WORKERS_AUTOSTART=1" ".env" >nul 2>&1
if not errorlevel 1 (
  findstr /B /C:"LEVIATHAN_WORKERS_ENABLED=false" ".env" >nul 2>&1
  if not errorlevel 1 goto :autostart_workers
  findstr /B /C:"LEVIATHAN_WORKERS_ENABLED=0" ".env" >nul 2>&1
  if not errorlevel 1 goto :autostart_workers
  findstr /B /C:"LEVIATHAN_WORKERS_SUPERVISOR_ENABLED=false" ".env" >nul 2>&1
  if not errorlevel 1 goto :autostart_workers
  findstr /B /C:"LEVIATHAN_WORKERS_SUPERVISOR_ENABLED=0" ".env" >nul 2>&1
  if not errorlevel 1 goto :autostart_workers
  echo [LEVIATHAN] Skipping LEVIATHAN_WORKERS_AUTOSTART — leviathan.py bootstrap owns WorkerSupervisor
  echo [LEVIATHAN] Source Ingestion owned by Worker Fabric — standalone worker NOT started
  goto :after_workers_autostart
)

:autostart_workers
findstr /B /C:"LEVIATHAN_WORKERS_AUTOSTART=1" ".env" >nul 2>&1
if not errorlevel 1 (
  echo [LEVIATHAN] LEGACY AUTOSTART: separate Worker Supervisor window ^(API-only / recovery^)
  echo [LEVIATHAN] Source Ingestion owned by Worker Fabric — standalone worker NOT started
  start "LEVIATHAN Workers" /D "%~dp0" "%~dp0run_leviathan_workers.bat"
  goto :after_workers_autostart
)
REM Legacy diagnostics only: explicit standalone_legacy without fabric autostart.
findstr /B /C:"LEVIATHAN_SOURCE_INGESTION_RUNNER=standalone_legacy" ".env" >nul 2>&1
if not errorlevel 1 (
  echo [LEVIATHAN] Starting LEGACY standalone source ingestion worker ^(diagnostics only^)
  start "LEVIATHAN Source Ingestion LEGACY" /D "%~dp0" "%PY%" scripts\source_ingestion_worker.py
)

:after_workers_autostart

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
