@echo off
setlocal
cd /d "%~dp0"

echo ========================================
echo HADES release-verificatie
echo ========================================

if not exist "node_modules\.bin\vite.cmd" (
  echo [FOUT] Frontend dependencies ontbreken of zijn incompleet.
  echo Voer eerst PREPARE_HADES.bat uit.
  exit /b 1
)
if not exist "backend\.venv\Scripts\python.exe" (
  echo [FOUT] Backend virtual environment ontbreekt.
  echo Voer eerst PREPARE_HADES.bat uit.
  exit /b 1
)

REM VERIFY_HADES.bat is altijd de volledige deterministic releasegate.
REM Alleen aanvullende host-probes zijn toegestaan; flags die releasefases
REM overslaan (--quick, --python-only, --host-only) horen rechtstreeks bij
REM verify_hades.py en mogen hier geen "alle releasechecks geslaagd" opleveren.
set "VERIFY_ARGS=%*"

:parse
if "%~1"=="" goto run
if /I "%~1"=="--host" goto next
if /I "%~1"=="--lm-studio" goto next
if /I "%~1"=="--browser" goto next
if /I "%~1"=="--voice" goto next
if /I "%~1"=="--sandbox" goto next
if /I "%~1"=="--host-report" goto host_report

echo [FOUT] Ongeldige VERIFY_HADES optie: %~1
echo [INFO] Deze wrapper voert altijd de volledige releasegate uit.
echo [INFO] Toegestaan: --host --lm-studio --browser --voice --sandbox --host-report PAD
exit /b 2

:host_report
if "%~2"=="" (
  echo [FOUT] --host-report vereist een pad.
  exit /b 2
)
shift

goto next

:next
shift
goto parse

:run
echo [canonical] Running verify_hades.py full gate ^(typecheck, ESLint, build, frontend tests, native CTest/install, backend suite, Ruff, Gen2 evals, OpenAPI drift^)...
"backend\.venv\Scripts\python.exe" verify_hades.py %VERIFY_ARGS%
if errorlevel 1 goto :error

echo.
echo [OK] Alle deterministic HADES releasechecks zijn geslaagd.
echo [NOTE] Host probes (--host / --lm-studio / --browser / --voice / --sandbox) schrijven host_capability_matrix.json.
echo [NOTE] Ontbrekende hardware/providers = UNVERIFIED_ON_HOST, nooit een vervalste release PASS.
exit /b 0

:error
echo.
echo [FOUT] Release-verificatie is mislukt. HADES wordt niet als gereed beschouwd.
exit /b 1
