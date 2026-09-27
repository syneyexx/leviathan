@echo off
setlocal EnableExtensions
cd /d "%~dp0"
title LEVIATHAN — build run_leviathan.exe

REM Double-click this file on Windows to compile run_leviathan.exe.
REM The executable is not in git. This script builds it next to this file.

set "NOPAUSE="
if /I "%~1"=="/nopause" set "NOPAUSE=1"

echo.
echo  ============================================
echo    Build run_leviathan.exe
echo  ============================================
echo.
echo  The exe is not downloaded. This compiles it on this PC.
echo  Requires Node.js 20+, Rust, the Visual Studio C++ build tools, and WebView2.
echo.

where node >nul 2>&1
if errorlevel 1 goto :missing_node
where npm >nul 2>&1
if errorlevel 1 goto :missing_node

where cargo >nul 2>&1
if errorlevel 1 (
  if exist "%USERPROFILE%\.cargo\bin\cargo.exe" (
    set "PATH=%USERPROFILE%\.cargo\bin;%PATH%"
  )
)
where cargo >nul 2>&1
if errorlevel 1 goto :missing_cargo

if not exist "Data\launcher\package.json" (
  echo  [ERROR] Data\launcher is missing. Run this from the LEVIATHAN install root.
  goto :fail
)

pushd "Data\launcher"
echo [1/5] npm ci
call npm ci
if errorlevel 1 goto :fail_pop
echo [2/5] launcher tests
call npm test
if errorlevel 1 goto :fail_pop
echo [3/5] typecheck
call npm run typecheck
if errorlevel 1 goto :fail_pop
echo [4/5] host-core tests
call cargo test --manifest-path host-core\Cargo.toml
if errorlevel 1 goto :fail_pop
echo [5/5] Tauri release build
call npm run tauri -- build
if errorlevel 1 goto :fail_pop
popd

set "BUILT="
if exist "Data\launcher\src-tauri\target\release\run_leviathan.exe" (
  set "BUILT=Data\launcher\src-tauri\target\release\run_leviathan.exe"
)
if not defined BUILT (
  for /r "Data\launcher\src-tauri\target\release\bundle" %%F in (run_leviathan.exe) do (
    if not defined BUILT set "BUILT=%%~fF"
  )
)
if not defined BUILT goto :missing_exe

if not exist "dist" mkdir "dist"
copy /Y "%BUILT%" "dist\run_leviathan.exe" >nul
if errorlevel 1 goto :fail
copy /Y "%BUILT%" "run_leviathan.exe" >nul
if errorlevel 1 goto :fail

powershell -NoProfile -Command ^
  "$src = (Resolve-Path '%BUILT%').Path;" ^
  "$root = (Resolve-Path 'run_leviathan.exe').Path;" ^
  "$dist = (Resolve-Path 'dist\run_leviathan.exe').Path;" ^
  "$hs = (Get-FileHash -Algorithm SHA256 $src).Hash;" ^
  "$hr = (Get-FileHash -Algorithm SHA256 $root).Hash;" ^
  "$hd = (Get-FileHash -Algorithm SHA256 $dist).Hash;" ^
  "Write-Host ('SOURCE EXE: ' + $src);" ^
  "Write-Host ('SOURCE SIZE: ' + (Get-Item $src).Length);" ^
  "Write-Host ('SOURCE SHA256: ' + $hs);" ^
  "Write-Host ('ROOT EXE: ' + $root);" ^
  "Write-Host ('ROOT SIZE: ' + (Get-Item $root).Length);" ^
  "Write-Host ('ROOT SHA256: ' + $hr);" ^
  "Write-Host ('DIST EXE: ' + $dist);" ^
  "Write-Host ('DIST SIZE: ' + (Get-Item $dist).Length);" ^
  "Write-Host ('DIST SHA256: ' + $hd);" ^
  "if ($hs -ne $hr -or $hs -ne $hd) { exit 1 }"
if errorlevel 1 (
  echo  [ERROR] Copied run_leviathan.exe hash does not match the release binary.
  goto :fail
)

echo.
echo  ============================================
echo    run_leviathan.exe is ready
echo  ============================================
echo.
echo    %CD%\run_leviathan.exe
echo    %CD%\dist\run_leviathan.exe
echo.
echo  Start it directly, or run run_leviathan.bat.
echo.
if not defined NOPAUSE pause
exit /b 0

:fail_pop
popd
goto :fail

:missing_node
echo  [ERROR] Node.js 20+ and npm are required.
echo  Install Node.js LTS from https://nodejs.org/ and reopen this window.
goto :fail

:missing_cargo
echo  [ERROR] Rust/cargo was not found.
echo  Install Rust from https://rustup.rs/ and reopen this window.
echo  Tauri also needs the Visual Studio C++ build tools.
goto :fail

:missing_exe
echo  [ERROR] The Tauri build finished without run_leviathan.exe.
goto :fail

:fail
echo.
echo  ============================================
echo    run_leviathan.exe was NOT built
echo  ============================================
echo.
if not defined NOPAUSE pause
exit /b 1
