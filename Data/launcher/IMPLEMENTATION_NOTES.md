# LEVIATHAN backend host — implementation notes

Baseline `origin/main` at the start of this work:

`95fe8658638ff016115d9a05c9a2a8d835ccfb97`

Branch: `cursor/run-leviathan-native-host-5fc9`

`run_leviathan.exe` is the operator launcher and backend host. It is not the user-facing LEVIATHAN frontend.

## Inventory used to drive the host

| Concern | Current repository truth |
| --- | --- |
| Canonical launcher | `run_leviathan.bat` starts `.venv\Scripts\python.exe leviathan.py`. The exe now absorbs that path. The bat launches the exe when present. `LEVIATHAN_LEGACY_CONSOLE=1` keeps the console path. |
| API startup | `leviathan.py` selects API-only or API plus the generic Worker Supervisor. The host spawns that file. It does not call `cmd.exe /c run_leviathan.bat`. |
| Supervisor startup | One consolidated supervisor inside the `leviathan.py` process tree. The host does not open `run_leviathan_workers.bat`. |
| Worker ownership | Worker Fabric leases remain authoritative. The host reads `GET /api/workers/dashboard`. |
| Source-ingestion ownership | Existing JobStore and source-ingestion containers. The host adds a read-only projection. It does not start `scripts/source_ingestion_worker.py`. |
| Job read model | `GET /api/jobs` plus the bounded host ingestion projection. |
| Observability | `GET /api/events/stream` (`event: event`, `Last-Event-ID`). |
| Performance | `GET /api/performance/snapshot`. Missing disk and network stay unmeasured. |
| Databases | CONTROL, KNOWLEDGE, MARKET via SQLite Manager and `/api/host/overview`. No PostgreSQL, Redis, or Qdrant cards. |
| Native compute | `leviathan-data-plane` is an accelerator. Probe status is authoritative. A binary path is not availability. There is no native daemon. |
| Frontend address | Settings host/port, default `127.0.0.1:8765`, opened in the system browser. |
| Logs | Child stdout/stderr stay in the GUI. The host also writes `Data/logs/launcher/run_leviathan_host.log`. |
| Shutdown | Graceful process-group signal, bounded wait, then owned-job termination only. No `taskkill /IM python.exe`. |
| Installer | `installer.bat` builds the exe only when `LEVIATHAN_BUILD_HOST_EXE=1`. A failed host build fails the install. Otherwise it prints `NOT BUILT`. |

## Safe Mode

Safe Mode is process-local. It does not rewrite `.env`. The overrides live in `host-core` `SAFE_MODE_ENV`:

- `LEVIATHAN_BOOTSTRAP_MODE=api`
- outbound network off
- chaos off
- module-manager subprocess off
- native compute spawn disabled
- source-ingestion, dataset, research, agents, and market-sim runners set to `none`
- `LEVIATHAN_WORKERS_AUTOSTART=0`

The UI shows `SAFE MODE` while the preference is armed or the owned process was started with it.

## Host states

`STOPPED`, `PREFLIGHT`, `STARTING`, `RUNNING`, `DEGRADED`, `STOPPING`, `FAILED`, `ATTACHED_EXTERNAL`.

`RUNNING` requires `/api/health` with `ok=true`. An already-healthy external listener is attached. Start, Stop, Restart, and Emergency Shutdown stay disabled for that instance. Closing the window does not stop it.

## Read-only endpoints

Added only where existing APIs did not expose a bounded operator projection:

- `GET /api/host/overview`
- `GET /api/host/source-ingestion`
- `GET /api/host/native-operations`

They do not mutate jobs, create schema, or open SQLite from the renderer.

## Build

On Windows, double-click `build_run_leviathan_exe.bat` in the install root. It does not call Python. It runs the launcher tests, then the Tauri release build, and copies the result to:

- `run_leviathan.exe` next to the batch file
- `dist\run_leviathan.exe`

WebView2 is required at runtime. The exe is gitignored. `scripts/build_run_leviathan_exe.py` remains a non-interactive equivalent for automation. On any OS other than Windows that script exits 3 after portable checks and does not claim the exe exists. `--allow-host-binary` builds the current OS binary for inspection and still is not `run_leviathan.exe`.

Visual regression, fixture only:

```bash
cd Data/launcher
npm run visual:build
python3 tests/visual/compare.py http://127.0.0.1:4178/
```

`VITE_LEVIATHAN_VISUAL_FIXTURE=1` is set only by `.env.fixture` and Vite mode `fixture`. The production bundle must not contain that screen.

## Windows behavior that this Linux workspace did not execute

These paths exist in `cfg(windows)` code and were not marked as passed:

- Job Object `KILL_ON_JOB_CLOSE` and `TerminateJobObject`
- `CREATE_NO_WINDOW` / `CREATE_NEW_PROCESS_GROUP`
- AttachConsole / `CTRL_BREAK_EVENT` graceful stop
- WebView2 window, single-instance focus, Explorer `ShellExecute`
- launching the produced `run_leviathan.exe`

On this host, portable process tests use a real Python child, process-group `SIGTERM`, and then `SIGKILL` after the graceful wait. A second instance takes the lock file and exits 0. It does not focus an existing window.

## Measured on this workspace

- Launcher `npm run typecheck`, `npm test` (12), and production `npm run build` passed. Production `dist` has no `FixtureRoot` or `visualFixture` chunk.
- Fixture visual diff at 1672×941: mean absolute difference 24.889, mismatch 27.55% where a channel delta is greater than 18. The gap is the generated concept art and its placeholder service names versus the truthful labels. The report is `Data/launcher/tests/visual/output/report.txt` and is not a pass/fail gate.
- `cargo test` in `Data/launcher/host-core`: 19 passed.
- `pytest Data/backend/tests/test_host_console.py`: 7 passed.
- `Data/frontend`: `npm test` 187 passed, then `npm run typecheck`, `npm run lint`, and `npm run build` passed.
- `scripts/build_run_leviathan_exe.py` on this Linux host exited 3 after the portable checks. It printed that `run_leviathan.exe` was not produced.
- `libwebkit2gtk` is not installed here, and `cargo check` for the Tauri crate could not resolve `tauri` from the offline registry. `run_leviathan.exe` was not produced.
- `cargo test` for `Data/native` did not run. Rust 1.83 cannot parse the current `arrow-cmp` crate (`edition2024`). That is a toolchain limit, not a host-core result.
