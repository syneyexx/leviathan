# Native runtime installation requirements (Windows)

HADES runs without a native binary (`native_runtime_mode=auto` falls back to Python).
Build the companion only when you want native process/service supervision and filesystem acceleration.

## Required

1. **Visual Studio Build Tools 2022 or newer**
   - Workload: **Desktop development with C++**
2. **MSVC x64/x86 build tools**
3. **Windows 10/11 SDK**
4. **CMake** (standalone or VS CMake tools)
5. **Ninja** (recommended generator)

## Not required for native runtime

- CUDA / NVIDIA drivers (LM Studio inference stays separate)
- Docker
- Internet at runtime (offline-first; vendored JSON dependency)

## Verify toolchain

```powershell
powershell -File tools\check_native_toolchain.ps1
```

## Build

```bat
BUILD_HADES_NATIVE.bat
```

Successful builds install:

```text
runtime\native\hades_native_runtime.exe
```

## Modes

Set in Settings → Python & Runtime → Native runtime:

- `auto` — use when present
- `enabled` — require native
- `disabled` — force Python paths

See `docs/NATIVE_RUNTIME.md`.
