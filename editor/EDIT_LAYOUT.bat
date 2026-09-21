@echo off
setlocal
cd /d "%~dp0"

echo ========================================
echo   LEVIATHAN Visual Builder
echo   Tekst · Images · Layout · Styles
echo ========================================
echo.
echo  Opent de ECHTE Leviathan UI.
echo  Klik / dubbelklik / sleep op de layout.
echo  Alles wordt in de echte bestanden gezet.
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
