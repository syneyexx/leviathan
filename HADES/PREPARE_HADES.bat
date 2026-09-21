@echo off
setlocal
cd /d "%~dp0"

where node >nul 2>nul || (
  echo [FOUT] Node.js is niet gevonden. Installeer Node.js 22.13 of nieuwer.
  pause
  exit /b 1
)

where python >nul 2>nul || (
  echo [FOUT] Python is niet gevonden. Installeer Python 3.11 of nieuwer.
  pause
  exit /b 1
)

echo [INFO] Runtimeversies controleren...
node tools\check_runtime_versions.mjs || goto :error

echo [1/6] Frontend-afhankelijkheden installeren...
call npm ci --include=dev --no-audit --no-fund || goto :error

if not exist "node_modules\.bin\vite.cmd" (
  echo [FOUT] npm meldde succes maar Vite ontbreekt. De installatie is incompleet.
  goto :error
)
if not exist "node_modules\.bin\tsc.cmd" (
  echo [FOUT] npm meldde succes maar TypeScript ontbreekt. Controleer npm omit/production-instellingen.
  goto :error
)
if not exist "node_modules\@vitejs\plugin-react\package.json" (
  echo [FOUT] npm meldde succes maar @vitejs/plugin-react ontbreekt.
  echo [INFO] PREPARE_HADES forceert devDependencies met --include=dev; controleer package.json/package-lock.json als dit blijft optreden.
  goto :error
)

echo [2/6] Python-omgeving maken...
if not exist "backend\.venv\Scripts\python.exe" python -m venv "backend\.venv" || goto :error
set "HADES_PYTHON=backend\.venv\Scripts\python.exe"
node tools\check_runtime_versions.mjs || goto :error
set "HADES_PYTHON="

echo [3/6] Backend-afhankelijkheden installeren...
"backend\.venv\Scripts\python.exe" -m pip install --upgrade pip || goto :error
"backend\.venv\Scripts\python.exe" -m pip install -r "backend\requirements.txt" || goto :error
if not exist "backend\.env" copy "backend\.env.example" "backend\.env" >nul

echo [4/6] Optionele native runtime bouwen...
if /I "%HADES_SKIP_NATIVE%"=="1" (
  echo [INFO] HADES_SKIP_NATIVE=1 — native build overgeslagen; Python-fallback blijft actief.
) else if exist "BUILD_HADES_NATIVE.bat" (
  echo [INFO] Eerste MSVC-build kan enkele minuten duren; "Generating Code..." is normaal.
  echo [INFO] Vastgelopen? Stop met Ctrl+C, verwijder native\build\windows-release, of zet HADES_SKIP_NATIVE=1.
  call BUILD_HADES_NATIVE.bat
  if errorlevel 1 (
    echo [WAARSCHUWING] Native runtime niet gebouwd. HADES blijft werken met Python-fallback ^(native_runtime_mode=auto^).
    echo Installeer Visual Studio Build Tools + CMake + Ninja voor native supervisie. Zie docs\NATIVE_RUNTIME.md
  ) else (
    echo [OK] Native runtime geinstalleerd onder runtime\native\
  )
) else (
  echo [INFO] Geen BUILD_HADES_NATIVE.bat gevonden; native stap overgeslagen.
)

echo [5/6] Frontend setup-checks uitvoeren...
call npm run typecheck || goto :error
call npm run lint || goto :error
call npm run build || goto :error
call npm run test:frontend:release || goto :error

echo [6/6] Backend setup-checks uitvoeren...
pushd backend
".venv\Scripts\python.exe" -m unittest discover -s tests -v
if errorlevel 1 (popd & goto :error)
popd

echo.
echo [OK] HADES is voorbereid en de setup-checks zijn geslaagd.
echo [INFO] Voor de canonical volledige releaseverificatie: VERIFY_HADES.bat
echo Gebruik voortaan START_HADES.bat om HADES te starten.
pause
exit /b 0

:error
echo.
echo [FOUT] Voorbereiden/setup-checks is mislukt. HADES is NIET als gereed gemarkeerd.
echo Lees de foutmelding hierboven; los die eerst op.
pause
exit /b 1
