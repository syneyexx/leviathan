@echo off
setlocal EnableExtensions
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
  echo [LEVIATHAN] Not installed yet.
  echo Run installer.bat first.
  exit /b 1
)

if not exist "Data\frontend\dist\index.html" (
  echo [LEVIATHAN] Frontend build missing.
  echo Run installer.bat first ^(or: cd Data\frontend ^&^& npm run build^).
  exit /b 1
)

if not exist ".env" (
  if exist ".env.example" (
    copy /Y ".env.example" ".env" >nul
    echo [LEVIATHAN] Created .env from .env.example
  ) else (
    echo [LEVIATHAN] Missing .env and .env.example
    exit /b 1
  )
)

echo [LEVIATHAN] Starting on http://127.0.0.1:8765
".venv\Scripts\python.exe" -m uvicorn Data.backend.main:app --host 127.0.0.1 --port 8765
