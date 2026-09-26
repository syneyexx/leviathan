@echo off
setlocal EnableExtensions
cd /d "%~dp0"
title LEVIATHAN Database Upgrade

REM Canonical upgrade entrypoint for Control / Knowledge / Market SQLite DBs.
REM Does NOT contain schema SQL — calls Data.backend.db_upgrade.

set "PYTHONPATH=%~dp0"
set "PY=.venv\Scripts\python.exe"
set "LOG=%~dp0leviathan_db_upgrade.log"

echo [%DATE% %TIME%] LEVIATHAN database upgrade start > "%LOG%"

if not exist "%PY%" (
  echo [LEVIATHAN] Not installed yet.
  echo Run installer.bat first.
  echo [%DATE% %TIME%] Missing .venv\Scripts\python.exe >> "%LOG%"
  exit /b 1
)

echo [LEVIATHAN] Upgrading Control / Knowledge / Market databases...
echo [LEVIATHAN] Legacy single-DB installs are migrated; legacy file is never deleted.
echo.

"%PY%" -m Data.backend.db_upgrade %*
set "EXITCODE=%ERRORLEVEL%"

echo [%DATE% %TIME%] exit=%EXITCODE% >> "%LOG%"

if not "%EXITCODE%"=="0" (
  echo.
  echo [LEVIATHAN] Database upgrade FAILED ^(exit %EXITCODE%^).
  echo See leviathan_db_upgrade.log for details.
  exit /b %EXITCODE%
)

echo.
echo [LEVIATHAN] Database upgrade completed successfully.
exit /b 0
