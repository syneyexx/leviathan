# Native Runtime Protocol (v1)

Transport: line-delimited JSON over stdin/stdout. **stdout is protocol-only**; diagnostics go to stderr.

Native runtime version (`runtime.hello.version`) is independent of the HADES app version. Protocol version stays `1` while remaining backward compatible.

## Request

```json
{
  "version": 1,
  "id": "uuid-or-string",
  "method": "process.run",
  "params": {
    "deadline_ms": 5000
  }
}
```

Optional RPC-level params (any method):

- `deadline_ms` / `rpc_timeout_ms` — wall deadline from enqueue; queued work past deadline returns `DEADLINE_EXCEEDED`

## Success

```json
{
  "version": 1,
  "id": "uuid-or-string",
  "ok": true,
  "result": {},
  "meta": {
    "duration_ms": 12,
    "queue_ms": 4,
    "worker_id": 2
  }
}
```

## Error

```json
{
  "version": 1,
  "id": "uuid-or-string",
  "ok": false,
  "error": {
    "code": "DEADLINE_EXCEEDED",
    "message": "…",
    "details": {}
  },
  "meta": {
    "duration_ms": 0,
    "queue_ms": 120,
    "worker_id": 1
  }
}
```

## Concurrency model

```text
stdin reader → parse → bounded queue → worker pool → response writer
```

- Workers: `HADES_NATIVE_WORKERS` or hardware-derived default
- Queue: `HADES_NATIVE_QUEUE` (default 256)
- Saturation returns `QUEUE_FULL` immediately (no unbounded thread-per-request)
- Process slots: `HADES_NATIVE_MAX_PROCESSES` → `OVERLOADED` when saturated

## Methods

| Method | Purpose |
|---|---|
| `runtime.hello` | Handshake / version |
| `runtime.health` | Liveness + executor/job counters |
| `runtime.capabilities` | Truthful feature flags |
| `runtime.shutdown` | Graceful stop + cancel active jobs |
| `process.run` | Argv process execution with capture |
| `process.cancel` | Cancel by job id (idempotent) |
| `service.start` / `status` / `stop` / `logs` / `probe` | Long-running supervised services |
| `fs.scan` | Recursive metadata scan (no symlink loops) |
| `fs.hash` | SHA-256 of a regular file |
| `fs.hash_many` | Batch SHA-256 |
| `fs.snapshot` / `repo.scan` | Compact repo snapshot (paginated) |
| `repo.search` | Bounded literal text search |
| `system.metrics` | Truthful host/process metrics |

## process.run params

- `executable` (required)
- `argv` (array, never shell-concatenated)
- `cwd`, `env`
- `timeout_ms`, `max_stdout_bytes`, `max_stderr_bytes`
- `job_id` (optional, for concurrent cancel; Python auto-assigns when omitted)

Never reconstruct untrusted arguments into a shell string. Never use `system()` / `cmd.exe /c` concatenation for plugin argv.

## Error codes

`INVALID_REQUEST`, `INVALID_PARAMS`, `UNSUPPORTED_VERSION`, `PARSE_ERROR`, `UNKNOWN_METHOD`, `EXECUTABLE_NOT_FOUND`, `PROCESS_START_FAILED`, `TIMEOUT`, `DEADLINE_EXCEEDED`, `CANCELLED`, `OVERLOADED`, `QUEUE_FULL`, `SHUTTING_DOWN`, `OUTPUT_LIMIT`, `SERVICE_NOT_FOUND`, `SERVICE_IDENTITY_MISMATCH`, `ACCESS_DENIED`, `INVALID_PATH`, `INTERNAL_ERROR`, `RUNTIME_ERROR`

## Capabilities honesty

`runtime.capabilities` must never claim unsupported controls. Example on Linux:

```json
{
  "process_tree_kill": true,
  "job_objects": false,
  "memory_limit": false,
  "bounded_executor": true,
  "cancellation": true,
  "deadlines": true,
  "fs_hash_many": true,
  "fs_snapshot": true,
  "repo_search": true
}
```
