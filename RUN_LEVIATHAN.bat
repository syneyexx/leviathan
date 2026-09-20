@echo off
setlocal
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
  echo [LEVIATHAN] Python environment missing.
  echo Run: python -m venv .venv
  echo Then: .venv\Scripts\python -m pip install -r requirements.txt
  exit /b 1
)

if not exist ".env" (
  copy /Y ".env.example" ".env" >nul
  echo [LEVIATHAN] Created .env from .env.example
)

echo [LEVIATHAN] Starting on http://127.0.0.1:8765
".venv\Scripts\python.exe" -m uvicorn Data.backend.main:app --host 127.0.0.1 --port 8765
