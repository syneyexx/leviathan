@echo off
setlocal EnableExtensions EnableDelayedExpansion
cd /d "%~dp0"

echo.
echo  ============================================
echo    LEVIATHAN Installer
echo  ============================================
echo.

REM ---- Prerequisites: Python 3.11+ ----
echo [1/7] Checking Python...
where python >nul 2>&1
if errorlevel 1 (
  echo.
  echo  [ERROR] Python not found on PATH.
  echo  Install Python 3.11+ from https://www.python.org/downloads/
  echo  During setup, enable "Add python.exe to PATH".
  goto :fail
)

for /f "tokens=*" %%V in ('python -c "import sys; print(sys.version.split()[0])" 2^>nul') do set "PY_VER=%%V"
if not defined PY_VER (
  echo  [ERROR] Could not read Python version.
  goto :fail
)
python -c "import sys; raise SystemExit(0 if sys.version_info >= (3, 11) else 1)" 2>nul
if errorlevel 1 (
  echo  [ERROR] Python 3.11+ required. Found: %PY_VER%
  goto :fail
)
echo        OK - Python %PY_VER%

REM ---- Prerequisites: Node.js 20+ ----
echo [2/7] Checking Node.js...
where node >nul 2>&1
if errorlevel 1 (
  echo.
  echo  [ERROR] Node.js not found on PATH.
  echo  Install Node.js 20+ LTS from https://nodejs.org/
  goto :fail
)
where npm >nul 2>&1
if errorlevel 1 (
  echo  [ERROR] npm not found on PATH ^(comes with Node.js^).
  goto :fail
)

for /f "tokens=*" %%V in ('node -v 2^>nul') do set "NODE_VER=%%V"
for /f "tokens=1 delims=." %%M in ("%NODE_VER:v=%") do set "NODE_MAJOR=%%M"
if not defined NODE_MAJOR set "NODE_MAJOR=0"
if !NODE_MAJOR! LSS 20 (
  echo  [ERROR] Node.js 20+ required. Found: %NODE_VER%
  goto :fail
)
echo        OK - Node.js %NODE_VER%

REM ---- Python virtual environment ----
echo [3/7] Python virtual environment...
if not exist ".venv\Scripts\python.exe" (
  echo        Creating .venv ...
  python -m venv .venv
  if errorlevel 1 (
    echo  [ERROR] Failed to create .venv
    goto :fail
  )
) else (
  echo        .venv already present
)

echo        Upgrading pip...
".venv\Scripts\python.exe" -m pip install --upgrade pip
if errorlevel 1 (
  echo  [ERROR] pip upgrade failed
  goto :fail
)

echo        Installing requirements.txt ...
".venv\Scripts\python.exe" -m pip install -r requirements.txt
if errorlevel 1 (
  echo  [ERROR] pip install failed
  goto :fail
)
echo        OK - Python packages installed

REM ---- Environment file ----
echo [4/7] Environment file...
if not exist ".env" (
  if not exist ".env.example" (
    echo  [ERROR] .env.example missing
    goto :fail
  )
  copy /Y ".env.example" ".env" >nul
  echo        Created .env from .env.example
  echo        Edit .env to point LEVIATHAN_LLM_BASE_URL at your local LLM.
) else (
  echo        .env already present - left unchanged
)

REM ---- Local data directories ----
echo [5/7] Data directories...
if not exist "Data\backend\data" mkdir "Data\backend\data"
if not exist "Data\backend\data\artifacts" mkdir "Data\backend\data\artifacts"
if not exist "Data\backend\data\backups" mkdir "Data\backend\data\backups"

REM Create ModelData root from .env (LEVIATHAN_DATA_ROOT), default D:\ModelData
set "MODEL_DATA=D:\ModelData"
for /f "usebackq eol=# tokens=1,* delims==" %%A in (".env") do (
  if /I "%%~A"=="LEVIATHAN_DATA_ROOT" (
    if not "%%~B"=="" set "MODEL_DATA=%%~B"
  )
)
set "MODEL_DATA=%MODEL_DATA:/=\%"
if not exist "%MODEL_DATA%" (
  mkdir "%MODEL_DATA%" 2>nul
  if exist "%MODEL_DATA%" (
    echo        Created %MODEL_DATA%
  ) else (
    echo        [WARN] Could not create %MODEL_DATA% - create it manually if needed
  )
) else (
  echo        OK - %MODEL_DATA%
)

REM ---- Frontend dependencies ----
echo [6/7] Frontend npm install...
pushd "Data\frontend"
call npm install
if errorlevel 1 (
  popd
  echo  [ERROR] npm install failed
  goto :fail
)
echo        OK - node_modules ready

REM ---- Frontend production build ----
echo [7/7] Frontend build...
call npm run build
if errorlevel 1 (
  popd
  echo  [ERROR] npm run build failed
  goto :fail
)
popd

if not exist "Data\frontend\dist\index.html" (
  echo  [ERROR] Frontend dist missing after build
  goto :fail
)
echo        OK - Data\frontend\dist ready

echo.
echo  ============================================
echo    Install complete
echo  ============================================
echo.
echo  Start Leviathan with:
echo    run_leviathan.bat
echo.
echo  Then open:
echo    http://127.0.0.1:8765/
echo.
echo  LLM default endpoint ^(edit in .env^):
echo    http://127.0.0.1:1234/v1
echo.
pause
exit /b 0

:fail
echo.
echo  ============================================
echo    Install failed
echo  ============================================
echo  Fix the errors above, then run installer.bat again.
echo.
pause
exit /b 1
