# HADES native companion runtime

`hades_native_runtime` is an offline-first companion process for the Python HADES lifecycle owner. It accepts one JSON-RPC request per stdin line and emits exactly one JSON response per request line on stdout. Diagnostics only go to stderr.

## Build

On Windows, run `BUILD_HADES_NATIVE.bat`. It detects CMake, Ninja, and an active/installed Visual Studio C++ toolchain, builds, tests, then installs the executable under `runtime/native/`.

For Linux CI:

```sh
tools/build_native.sh
```

For an ad hoc build:

```sh
cmake -S native -B native/build -DCMAKE_BUILD_TYPE=Release
cmake --build native/build
ctest --test-dir native/build --output-on-failure
```

## Protocol

Every request must include `version: 1`, an `id`, `method`, and object `params`. Responses use the success/error envelopes documented in the repository task. Methods are:

- `runtime.hello`, `runtime.health`, `runtime.capabilities`, `runtime.shutdown`
- `process.run`, `process.cancel`
- `service.start`, `service.status`, `service.stop`, `service.logs`, `service.probe`
- `fs.scan`, `fs.hash`, `system.metrics`

`process.run` executes the `executable` directly (never through a shell). Its optional `argv`, `cwd`, `env`, `timeout_ms`, `max_stdout_bytes`, and `max_stderr_bytes` parameters control launch and bounded capture. Supply a caller-selected `job_id` to make a concurrently sent `process.cancel` request addressable. Requests are processed concurrently so a cancellation can arrive while a run request is waiting.

`service.start` has the same launch parameters plus a required safe service `id` and optional `log_dir`. It redirects output to per-service log files. `service.probe` returns the service PID, launch creation timestamp, and whether an optional `creation_time` matches the recorded identity. A service is runtime-owned: Python should restart it after companion restart.

`fs.scan` requires `path` and supports `max_entries`; it uses a non-symlink-following recursive iterator. `fs.hash` requires a regular-file `path` and returns SHA-256 calculated by the bundled implementation. `system.metrics` reports only platform data it can observe; GPU data is deliberately absent.

Linux implements processes and services with `fork`/`exec`, process groups, pipes, and `waitpid`. Windows uses native process and Job Object support; non-Windows builds do not attempt to expose Win32-only capability.
