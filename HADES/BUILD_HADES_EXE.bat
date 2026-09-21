@echo off
setlocal
cd /d "%~dp0"

if not exist "backend\.venv\Scripts\python.exe" (
  echo HADES is nog niet voorbereid. PREPARE_HADES.bat wordt gestart.
  call PREPARE_HADES.bat || exit /b 1
)

set "BUILD_VENV=%CD%\.hades-cache\pyinstaller-venv"
set "BUILD_PYTHON=%BUILD_VENV%\Scripts\python.exe"
set "PYI_ROOT=%CD%\.hades-cache\pyinstaller"
set "PYI_DIST=%PYI_ROOT%\dist"
set "PYI_WORK=%PYI_ROOT%\work"
set "PYI_SPEC=%PYI_ROOT%\spec"

echo [1/3] Geisoleerde PyInstaller build-omgeving voorbereiden...
if not exist "%BUILD_PYTHON%" (
  "backend\.venv\Scripts\python.exe" -m venv "%BUILD_VENV%" || goto :error
)

echo [2/3] Gepinde PyInstaller build-toolchain installeren...
"%BUILD_PYTHON%" -m pip install -r "tools\requirements-pyinstaller.txt" || goto :error

if not exist "%PYI_SPEC%" (
  mkdir "%PYI_SPEC%"
  if errorlevel 1 goto :error
)

echo [3/3] HADES.exe bouwen...
"%BUILD_PYTHON%" -m PyInstaller --noconfirm --clean --onefile --windowed --name HADES --distpath "%PYI_DIST%" --workpath "%PYI_WORK%" --specpath "%PYI_SPEC%" "%CD%\HADES_LAUNCHER.py" || goto :error

if not exist "%PYI_DIST%\HADES.exe" (
  echo [FOUT] PyInstaller meldde succes maar HADES.exe ontbreekt in "%PYI_DIST%".
  goto :error
)
copy /Y "%PYI_DIST%\HADES.exe" ".\HADES.exe" >nul || goto :error

echo.
echo [OK] HADES.exe staat in deze map. PyInstaller build-artifacts staan onder .hades-cache\.
echo Dubbelklik voortaan op HADES.exe.
pause
exit /b 0

:error
echo.
echo [FOUT] HADES.exe bouwen is mislukt.
pause
exit /b 1
