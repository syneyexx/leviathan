@echo off
setlocal
cd /d "%~dp0"

echo ========================================
echo   LEVIATHAN Visual Editor (ADMIN)
echo   Los van normale Leviathan-start
echo ========================================
echo.
echo  Wijzigingen worden opgeslagen in de
echo  echte Leviathan-bestanden.
echo  Normale start = zonder editor-UI.
echo.

where node >nul 2>&1
if errorlevel 1 (
  echo [EDITOR] Node.js/npm niet gevonden.
  echo Installeer Node.js en probeer opnieuw.
  pause
  exit /b 1
)

where python >nul 2>&1
if errorlevel 1 (
  where py >nul 2>&1
  if errorlevel 1 (
    echo [EDITOR] Python niet gevonden. Installeer Python 3.
    pause
    exit /b 1
  )
  echo [EDITOR] API : http://127.0.0.1:5199
  echo [EDITOR] App : http://127.0.0.1:5173
  py -3 server.py
  goto :eof
)

echo [EDITOR] API : http://127.0.0.1:5199
echo [EDITOR] App : http://127.0.0.1:5173
python server.py

if errorlevel 1 (
  echo.
  echo [EDITOR] Gestopt met een fout.
  pause
)
