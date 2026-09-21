# Local developer verification (no GitHub required)

GitHub Actions may be unavailable (`BLOCKED_EXTERNAL` billing). Local verification is the source of truth.

## Quick map

| Goal | Command |
|---|---|
| Frontend | `npm run dev` |
| Backend | `backend/.venv/bin/python -m uvicorn main:app --app-dir backend --reload --port 8000` |
| Build native | `tools/build_native.sh` or `cmake -S native -B native/build && cmake --build native/build` |
| Native tests | `ctest --test-dir native/build --output-on-failure` |
| Native bench | `native/build/native_bench 1000` |
| Python tests | `backend/.venv/bin/python -m unittest discover -s backend/tests -v` |
| Frontend tests | `npm run typecheck && npm run lint && npm test` |
| Full local gate | `python verify_hades.py` or `python verify_hades.py --quick` |

## Native environment variables

| Variable | Meaning |
|---|---|
| `HADES_NATIVE_WORKERS` | Bounded worker count (default: clamp(hardware, 2..16)) |
| `HADES_NATIVE_QUEUE` | Pending RPC queue capacity (default 256) |
| `HADES_NATIVE_MAX_PROCESSES` | Max concurrent child processes (default 32) |
| `HADES_NATIVE_DEV_SEARCH` | Allow searching `native/build/` for the binary |

## Sanitizers (optional, non-MSVC)

```bash
cmake -S native -B native/build-asan -DHADES_NATIVE_SANITIZE_ADDRESS=ON -DHADES_NATIVE_SANITIZE_UNDEFINED=ON
cmake --build native/build-asan
ctest --test-dir native/build-asan --output-on-failure
```

ThreadSanitizer is separate (`HADES_NATIVE_SANITIZE_THREAD=ON`) and must not combine with ASan.

## Architecture docs

- `docs/architecture/python-cpp-boundary.md` — ownership & failure model
- `docs/NATIVE_RUNTIME.md` — companion overview
- `docs/NATIVE_RUNTIME_PROTOCOL.md` — RPC contract
- `docs/engineering/ARCHITECTURE_HOTSPOTS.md` — megafile extraction status
