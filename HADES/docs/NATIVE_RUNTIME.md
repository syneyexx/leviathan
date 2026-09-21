# HADES Native Runtime

Optional C++20 companion process for supervised process/service execution, filesystem scan/hash, and host metrics. It does **not** replace FastAPI, LM Studio, SQLite, or the Plugin Runtime policy engine.

## Architecture

```
React UI  →  FastAPI / PluginManager  →  NativeRuntimeFacade (Python)
                                              │
                                              │ stdin/stdout JSON-RPC
                                              ▼
                                    hades_native_runtime(.exe)
                                         bounded worker pool
```

- Canonical package: `backend/infrastructure/native/` (`NativeRuntimeFacade`, supervisor, transport, typed clients)
- Compatibility shim: `backend/native_runtime.py`
- Lifecycle owned by the single FastAPI lifespan (`backend/app_lifecycle.py`)
- PluginManager may route `_run_command` / service start through native when connected
- Policy (trust, block, Ready, approvals) remains deterministic in HADES Python code
- Deep dive: `docs/architecture/python-cpp-boundary.md`

## Modes (`native_runtime_mode`)

| Mode | Behavior |
|---|---|
| `auto` (default) | Use native when binary is present and healthy; otherwise Python fallback for **non-security-bound** host tiers. Fallback is recorded (`native_fallback`, `executor_requested` / `executor_effective`, sanitized `native_error`). Fallback must not weaken a requested isolation guarantee (e.g. `container` / `secured` still refuse). |
| `enabled` | Require native; `native.process_run` failure returns `native_executor_failed` — **no** silent `subprocess.run` downgrade |
| `disabled` | Always use Python paths |

## Build (Windows)

Required:

- Visual Studio Build Tools 2022+ with **Desktop development with C++**
- MSVC x64
- Windows 10/11 SDK
- CMake
- Ninja (recommended)

```bat
BUILD_HADES_NATIVE.bat
```

or:

```bat
powershell -File tools\check_native_toolchain.ps1
cmake -S native -B native\build -G Ninja -DCMAKE_BUILD_TYPE=Release
cmake --build native\build --config Release
ctest --test-dir native\build --output-on-failure
```

Stable output location used by Python:

```text
runtime/native/hades_native_runtime.exe
```

`PREPARE_HADES.bat` attempts a native build and continues with Python fallback if the toolchain is missing.

First MSVC builds can spend noticeable time on **Generating Code...** (MSVC backend). The project enables `/MP` and `/cgthreads8` so that phase should advance; install **Ninja** for clearer per-file progress. If a previous failed build leaves MSVC stuck, delete `native\build\windows-release` and rerun `BUILD_HADES_NATIVE.bat`, or set `HADES_SKIP_NATIVE=1` to finish prepare with Python fallback.

## Build (Linux CI)

```sh
tools/build_native.sh
# or
cmake -S native -B native/build -DCMAKE_BUILD_TYPE=Release
cmake --build native/build
ctest --test-dir native/build --output-on-failure
cp native/build/hades_native_runtime runtime/native/
```

Linux builds exercise protocol/fs/hash/process group supervision. Windows Job Objects are compiled for MSVC targets and are **UNVERIFIED_ON_HOST** until run on Windows.

## API

- `GET /api/native/status`
- `GET /api/native/diagnostics` — generation, workers, queue, crashes, observability counters
- `POST /api/native/restart`
- `GET /api/native/metrics`
- `POST /api/native/benchmark` — process-launch micro-benchmark only (not LM Studio tokens/s)

UI: Settings → Advanced → **Native supervised runtime**.

## Security honesty

This is **native process supervision / resource control**, not an OS sandbox. A permitted subprocess still runs under the HADES user account. Global `block` and ASK approvals are unchanged.

## Protocol

See `docs/NATIVE_RUNTIME_PROTOCOL.md`.

## Limitations

- Native binary is optional; HADES must run without it
- GPU metrics are not fabricated; optional GPU providers are out of scope for v1
- Windows Job Object paths require a Windows host for verification
- Service health remains proven by declared PluginManager healthchecks after native start
