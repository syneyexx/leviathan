@echo off
setlocal EnableExtensions
set "ROOT=%~dp0"
for %%I in ("%ROOT%.") do set "INSTALL_PREFIX=%%~fI"

if not defined INSTALL_PREFIX (
  echo [ERROR] Failed to resolve the HADES install prefix.
  exit /b 1
)

where cmake >nul 2>nul
if errorlevel 1 (
  echo [ERROR] CMake was not found on PATH.
  exit /b 1
)

set "MSVC_ACTIVE=0"
where cl >nul 2>nul
if errorlevel 1 (
  echo [INFO] MSVC cl.exe is not active. CMake will use the Visual Studio generator to locate Build Tools.
) else (
  set "MSVC_ACTIVE=1"
  echo [INFO] MSVC compiler: available
)

set "GENERATOR=Visual Studio 17 2022"
set "ARCH_ARGS=-A x64"
if "%MSVC_ACTIVE%"=="1" (
  where ninja >nul 2>nul
  if errorlevel 1 (
    echo [INFO] Ninja not found; using Visual Studio generator ^(x64^).
    echo [INFO] Tip: install Ninja for faster, clearer native builds.
  ) else (
    set "GENERATOR=Ninja"
    set "ARCH_ARGS="
    echo [INFO] Ninja + active MSVC environment: available
  )
) else (
  echo [INFO] Using Visual Studio 17 2022 generator ^(x64^) because MSVC is not active in this shell.
)

set "BUILD_DIR=%ROOT%native\build\windows-release"
set "PARALLEL=%NUMBER_OF_PROCESSORS%"
if not defined PARALLEL set "PARALLEL=4"

echo [INFO] Native install prefix: "%INSTALL_PREFIX%"
echo [INFO] Configuring native runtime...
cmake -S "%ROOT%native" -B "%BUILD_DIR%" -G "%GENERATOR%" %ARCH_ARGS% -DCMAKE_BUILD_TYPE=Release -DBUILD_TESTING=ON -DCMAKE_INSTALL_PREFIX:PATH="%INSTALL_PREFIX%"
if errorlevel 1 exit /b %errorlevel%

echo [INFO] Building native runtime ^(Release, parallel=%PARALLEL%^)...
echo [INFO] First MSVC build can take several minutes. "Generating Code..." is normal; with /MP it should not stall indefinitely.
cmake --build "%BUILD_DIR%" --config Release --parallel %PARALLEL%
if errorlevel 1 (
  echo [ERROR] Native build failed. Stale objects can leave MSVC stuck on "Generating Code...".
  echo [INFO] Cleaning "%BUILD_DIR%" and retrying once...
  rmdir /s /q "%BUILD_DIR%" 2>nul
  cmake -S "%ROOT%native" -B "%BUILD_DIR%" -G "%GENERATOR%" %ARCH_ARGS% -DCMAKE_BUILD_TYPE=Release -DBUILD_TESTING=ON -DCMAKE_INSTALL_PREFIX:PATH="%INSTALL_PREFIX%"
  if errorlevel 1 exit /b %errorlevel%
  cmake --build "%BUILD_DIR%" --config Release --parallel %PARALLEL%
  if errorlevel 1 exit /b %errorlevel%
)

echo [INFO] Running native tests...
ctest --test-dir "%BUILD_DIR%" -C Release --output-on-failure --timeout 120
if errorlevel 1 exit /b %errorlevel%

echo [INFO] Installing native runtime...
cmake --install "%BUILD_DIR%" --config Release
if errorlevel 1 exit /b %errorlevel%
echo [OK] HADES native runtime installed to "%INSTALL_PREFIX%\runtime\native".
