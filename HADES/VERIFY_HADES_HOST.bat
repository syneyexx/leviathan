@echo off
setlocal EnableExtensions EnableDelayedExpansion
REM HADES host capability verification (Windows-first).
REM Distinguishes available vs enforced vs not physically verified.

cd /d "%~dp0"
set "FAILED=0"

echo === HADES HOST VERIFY ===
echo.

where python >nul 2>&1
if errorlevel 1 (
  echo [FAIL] Python not on PATH
  set "FAILED=1"
) else (
  echo [OK] Python on PATH
  python --version
)

where node >nul 2>&1
if errorlevel 1 (
  echo [FAIL] Node.js 22.13+ not on PATH
  set "FAILED=1"
) else (
  echo [OK] Node on PATH
  node --version
)

where npm >nul 2>&1
if errorlevel 1 (
  echo [FAIL] npm not on PATH
  set "FAILED=1"
) else (
  echo [OK] npm on PATH
  npm --version
)

where git >nul 2>&1
if errorlevel 1 (
  echo [FAIL] Git not on PATH
  set "FAILED=1"
) else (
  echo [OK] Git on PATH
)

echo.
echo --- Path edge cases ---
set "PROBE=tmp host verify unicode café"
mkdir "%PROBE%" 2>nul
echo probe> "%PROBE%\file with spaces.txt"
if exist "%PROBE%\file with spaces.txt" (
  echo [OK] Unicode/spaces path write
) else (
  echo [FAIL] Unicode/spaces path write
  set "FAILED=1"
)
rmdir /s /q "%PROBE%" 2>nul

echo.
echo --- Python host capability report ---
if exist "backend\host_capability.py" (
  python -c "import sys; sys.path.insert(0,'backend'); from host_capability import check_host_capabilities; import json; r=check_host_capabilities(); print(json.dumps(r, indent=2)); raise SystemExit(0 if r.get('status')=='ready' else 1)"
  if errorlevel 1 (
    echo [FAIL] host_capability required-runtime check
    set "FAILED=1"
  ) else (
    echo [OK] host_capability required runtime ready
  )
) else (
  echo [FAIL] backend\host_capability.py missing
  set "FAILED=1"
)

REM Also run Python simulation (works on Windows and as CI parity check).
if exist "backend\host_verify_sim.py" (
  echo.
  echo --- Host verify simulation ---
  python -c "import sys; sys.path.insert(0,'backend'); from host_verify_sim import run_host_verify_simulation; import json; r=run_host_verify_simulation(); print(json.dumps(r, indent=2)); raise SystemExit(0 if r.get('status')=='passed' else 1)"
  if errorlevel 1 (
    echo [FAIL] host_verify_sim
    set "FAILED=1"
  ) else (
    echo [OK] host_verify_sim
  )
)

echo.
echo Isolation note: app-level envelopes are available; OS Job Object/AppContainer not claimed unless separately verified.
echo Physical LM Studio disconnect/resume: operator-run on this host.

if "%FAILED%"=="1" (
  echo.
  echo HOST VERIFY FAILED
  exit /b 1
)
echo.
echo HOST VERIFY PASSED required runtime essentials
exit /b 0
