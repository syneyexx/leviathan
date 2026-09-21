@echo off
setlocal
cd /d "%~dp0"

echo ========================================
echo   LEVIATHAN Layout Editor
echo   Live preview: code -^> resultaat
echo ========================================
echo.

where python >nul 2>&1
if errorlevel 1 (
  where py >nul 2>&1
  if errorlevel 1 (
    echo [EDITOR] Python niet gevonden. Installeer Python 3.
    pause
    exit /b 1
  )
  echo [EDITOR] Start op http://127.0.0.1:5199
  py -3 server.py
  goto :eof
)

echo [EDITOR] Start op http://127.0.0.1:5199
python server.py

if errorlevel 1 (
  echo.
  echo [EDITOR] Server gestopt met een fout.
  pause
)
