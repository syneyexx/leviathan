@echo off
setlocal EnableExtensions
cd /d "%~dp0"
title LEVIATHAN Workers

REM Relocatable: ensure Data.* imports resolve from this install root on any drive.
set "PYTHONPATH=%~dp0"
set "PY=.venv\Scripts\python.exe"
set "LOG=%~dp0leviathan_workers_startup.log"

echo [%DATE% %TIME%] LEVIATHAN workers start > "%LOG%"

if not exist "%PY%" (
  echo [LEVIATHAN Workers] Not installed yet.
  echo Run installer.bat first.
  echo [%DATE% %TIME%] Missing .venv\Scripts\python.exe >> "%LOG%"
  exit /b 1
)

if not exist ".env" (
  if exist ".env.example" (
    copy /Y ".env.example" ".env" >nul
    echo [LEVIATHAN Workers] Created .env from .env.example
  ) else (
    echo [LEVIATHAN Workers] Missing .env and .env.example
    echo [%DATE% %TIME%] Missing .env >> "%LOG%"
    exit /b 1
  )
)

REM Canonical externalization: this process owns JobRuntime pools — not the web API.
set "LEVIATHAN_WORKERS_ENABLED=1"
set "LEVIATHAN_WORKERS_SUPERVISOR_ENABLED=1"
set "LEVIATHAN_WORKERS_EXTERNALIZE_API=1"
set "LEVIATHAN_DATASET_JOBS_RUNNER=external"
set "LEVIATHAN_SOURCE_INGESTION_RUNNER=external"

echo [LEVIATHAN Workers] Checking Python packages...
"%PY%" -c "import fastapi" >> "%LOG%" 2>&1
if errorlevel 1 (
  echo [LEVIATHAN Workers] Required packages missing.
  echo Run installer.bat again.
  exit /b 1
)

echo [LEVIATHAN Workers] Checking supervisor import...
"%PY%" -c "from Data.modules.workers.bootstrap import run_supervisor" >> "%LOG%" 2>&1
if errorlevel 1 (
  echo [LEVIATHAN Workers] Failed to import worker supervisor.
  type "%LOG%"
  exit /b 1
)

echo [LEVIATHAN Workers] Starting Worker Supervisor ^(separate OS process^)
echo [LEVIATHAN Workers] Does NOT start the web backend.
echo [LEVIATHAN Workers] Connects to the canonical durable job DB from settings.
echo [LEVIATHAN Workers] Keep this window open. Press Ctrl+C to stop.
echo.

"%PY%" -m Data.modules.workers.bootstrap supervisor
set "EXITCODE=%ERRORLEVEL%"

if not "%EXITCODE%"=="0" (
  echo.
  echo [LEVIATHAN Workers] Supervisor exited with error code %EXITCODE%.
  echo [%DATE% %TIME%] supervisor exit code %EXITCODE% >> "%LOG%"
  exit /b %EXITCODE%
)

exit /b 0
