@echo off
setlocal EnableExtensions
cd /d "%~dp0"
title LEVIATHAN Database Upgrade

REM Canonical upgrade entrypoint for Control / Knowledge / Market SQLite DBs.
REM Does NOT contain schema SQL — calls Data.backend.db_upgrade.
REM Safe to rerun. Never deletes product databases.
REM Prefer a BackupService snapshot before destructive reconciliation on production hosts.
REM Domain migration DM3 (external_capability_fabric) owns CONTROL tables:
REM   external_modules, external_module_versions, external_process_records,
REM   external_skills, external_skill_catalogs, external_plugin_bindings,
REM   external_log_windows — never a fourth product database.

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
echo [LEVIATHAN] Legacy single-DB installs are migrated; product DB files are never deleted.
echo [LEVIATHAN] Misplaced-table UNKNOWN/CONFLICT states block completion ^(operator review^).
echo.

"%PY%" -m Data.backend.db_upgrade %*
set "EXITCODE=%ERRORLEVEL%"

echo [%DATE% %TIME%] exit=%EXITCODE% >> "%LOG%"

if not "%EXITCODE%"=="0" (
  echo.
  echo [LEVIATHAN] Database upgrade FAILED or BLOCKED ^(exit %EXITCODE%^).
  echo Check misplaced_table_reconcile_receipt.json under the CONTROL data directory
  echo and leviathan_db_upgrade.log. Do NOT delete databases.
  exit /b %EXITCODE%
)

echo.
echo [LEVIATHAN] Database upgrade completed successfully.
echo [LEVIATHAN] CONTROL / KNOWLEDGE / MARKET paths remain the sole product authorities.
exit /b 0
