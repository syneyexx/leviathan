# Python ↔ C++ boundary

HADES uses **Python for high-level AI orchestration** and **C++ for deterministic OS-bound and performance-sensitive execution**.

```text
React / TypeScript UI
        │  typed HTTP / events
        ▼
FastAPI transport
        ▼
Application / reasoning / policy (Python)
        ▼
NativeRuntimeFacade  (backend/infrastructure/native/)
        │  versioned JSON-RPC (stdin/stdout)
        ▼
hades_native_runtime (C++20)
        │
        ├── bounded executor (workers + queue)
        ├── process tree / Job Objects
        ├── filesystem / repo scan / hash / search
        └── host metrics
```

## Why C++ exists

- Supervised subprocess trees with reliable cancellation and cleanup
- Bounded concurrency (no thread-per-RPC)
- High-volume local filesystem / hashing / search hot paths
- Truthful OS capability reporting (Job Objects on Windows; process groups on Linux)

C++ must **not** own LLM policy, plugin permission decisions, or agent planning.

## Ownership

| Concern | Owner |
|---|---|
| Model calls, reasoning, agents, workflows | Python |
| Plugin / tool permission & policy | Python (`PluginManager`, execution gateway) |
| Application state, SQLite | Python |
| Request deadlines / cancellation initiation | Python (propagates to native) |
| Process launch argv (no shell) | Native (after Python validation) |
| Process-tree kill / Job Objects | Native |
| Filesystem batch scan/hash/search | Native |
| Bounded RPC workers / overload | Native |
| Companion crash detection / restart backoff | Python supervisor |
| Service reconciliation after native crash | Python (never fake reattach) |

## Failure model

### Native companion crashes
1. stdout reader ends → pending RPCs fail with stable `INTERNAL_ERROR` / connection-closed
2. Supervisor records `crash_count`, `last_crash_reason`, increments `generation`
3. Services owned by the dead generation are **not** considered alive — callers must reconcile/restart
4. Bounded restart/backoff prevents tight crash loops

### Python crashes / shutdown
1. Lifespan shutdown sends `runtime.shutdown`
2. Native cancels active jobs (process trees) then exits
3. Orphan prevention: Job Object kill-on-close (Windows) / process group SIGKILL (Linux)

### Overload
- Bounded queue → `QUEUE_FULL` (non-blocking reject)
- Max concurrent processes → `OVERLOADED`
- Callers must back off; silent unbounded queuing is forbidden

### Cancellation
```text
User cancel OR Python deadline
        ▼
NativeRuntimeFacade timeout/cancel hook
        ▼
RPC process.cancel (idempotent)
        ▼
Native CancellationToken / RunningProcess.cancel_requested
        ▼
OS process-tree termination
        ▼
Resources reclaimed; result cancelled=true or CANCELLED error
```

Python timeouts **must** attempt native cancel for cancellable jobs — removing a waiter alone is insufficient.

## Protocol

See `docs/NATIVE_RUNTIME_PROTOCOL.md`. Protocol version is independent of the HADES app version.

## Compatibility shim

`backend/native_runtime.py` re-exports `infrastructure.native` so existing imports keep working during incremental migration.
