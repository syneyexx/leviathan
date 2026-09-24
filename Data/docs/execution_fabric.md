# LEVIATHAN Execution Fabric (operator notes)

Control plane (FastAPI) validates, authorizes, enqueues, cancels, and streams status.
Durable work runs in the **Job Kernel** (`Data/modules/jobs`) under a **generic Worker Supervisor**.

**Not replaced:** Model Control Plane / ServingSupervisor still owns model-serving processes.
One Brain remains the single canonical knowledge fabric. This layer only moves *when and where*
domain work runs (API threads vs worker pools).

## Bootstrap

```bash
python leviathan.py
```

With `LEVIATHAN_WORKERS_ENABLED` + `LEVIATHAN_WORKERS_SUPERVISOR_ENABLED` (defaults: on),
`leviathan.py` starts API + supervisor via `Data.modules.workers.bootstrap` (`run_all`).

Optional mode override: `LEVIATHAN_BOOTSTRAP_MODE=api|supervisor|all`.

Legacy path (workers disabled): uvicorn only; FastAPI may start in-process domain runners.

## Env flags (`LEVIATHAN_WORKERS_*`)

| Flag | Default | Role |
|------|---------|------|
| `LEVIATHAN_WORKERS_ENABLED` | true | Master switch for fabric workers |
| `LEVIATHAN_WORKERS_SUPERVISOR_ENABLED` | true | Spawn generic supervisor |
| `LEVIATHAN_WORKERS_EXTERNALIZE_API` | true | FastAPI must **not** start heavy domain daemon threads |
| `LEVIATHAN_WORKERS_HEARTBEAT_SECONDS` | 5 | Worker heartbeat interval |
| `LEVIATHAN_WORKERS_LEASE_TTL_SECONDS` | 30 | Job claim lease TTL |
| `LEVIATHAN_WORKERS_POLL_SECONDS` | 0.5 | Claim poll interval |
| `LEVIATHAN_WORKERS_SHUTDOWN_GRACE_SECONDS` | 30 | Graceful stop window |
| `LEVIATHAN_WORKERS_RESTART_*` | (see settings) | Supervisor restart budget / backoff |
| `LEVIATHAN_WORKERS_SUPERVISOR_LEASE_TTL_SECONDS` | 20 | Singleton supervisor lease |
| `LEVIATHAN_WORKERS_POOL_<NAME>_COUNT` | pool default | Desired workers per pool |

Settings bindings: `Data/modules/settings/bindings.py` (`workers.*`).

## Domain runner overrides

Per-domain `inprocess|external|none` (or empty → follow externalize / defaults):

| Env | Typical use |
|-----|-------------|
| `LEVIATHAN_RESEARCH_RUNNER` | Research advance outside API |
| `LEVIATHAN_SOURCE_INGESTION_RUNNER` | Source ingestion worker |
| `LEVIATHAN_DATASET_JOBS_RUNNER` | Dataset job claim loop |
| `LEVIATHAN_AGENTS_RUNNER` | Agent fleet missions |
| `LEVIATHAN_MARKET_SIM_RUNNER` | Market sim advance |

Bootstrap `setdefault`s dataset + source_ingestion runners to `external` when launching workers.
`LEVIATHAN_WORKERS_EXTERNALIZE_API=true` is the global “API enqueues only” switch.

## Compute tiers

| Tier | Owner | Examples |
|------|-------|----------|
| 0 | Deterministic framework | parse, chunk, hash, SQL, math, dedupe, citations |
| 1 | Specialist | embeddings, rerank, OCR, NER |
| 2 | Small/utility model role | rewrite, extract, normalize |
| 3 | Main reasoning model | plan, adjudicate, synthesize |

Escalation: Tier0 → Tier1 → Tier2 → Tier3. No infinite loops. Main LLM is not used for Tier0 work.

## Job Kernel semantics

Canonical scheduler: `Data/modules/jobs`.

- States: CREATED, QUEUED, RUNNING, RETRY_WAIT, CANCEL_REQUESTED, COMPLETED, FAILED, CANCELLED
- Atomic claim + lease; heartbeat; expired lease recovery
- Delivery: **at-least-once** (handlers must be idempotent where re-delivery matters)
- Cancel: QUEUED/RETRY_WAIT → CANCELLED; RUNNING → CANCEL_REQUESTED → worker ack → CANCELLED
- Retry: transient failures → RETRY_WAIT with backoff until `max_attempts`; non-retryable → FAILED

## Worker pools

See `Data/modules/workers/pools.py`. Counts via `LEVIATHAN_WORKERS_POOL_<NAME>_COUNT`.
Pool workers must not import `Data.backend.main` (architecture tests enforce this).

### Provider I/O (`provider_io`)

Outbound external API / SaaS work (remote OpenAI-compatible chat, bounded HTTP,
market OHLCV fetch, Alpaca paper trading, HF dataset *listing*) runs in the
`provider_io` pool under the same WorkerSupervisor. Default count: 2
(`LEVIATHAN_WORKERS_POOL_PROVIDER_IO_COUNT`).

- Control Plane submits durable jobs via `Data.modules.provider_io.facade.ProviderExecutionClient`
- Workers own process-local HTTP clients, retries, circuits, and stream events
- Secrets use `credential_ref` / ephemeral file refs — never raw keys in job JSON
- Streaming deltas: `GET /api/jobs/{id}/provider-stream` (bounded SQLite event channel)
- Bulk HF dataset downloads remain in the **dataset** worker (not provider_io)
- Bulk model downloads remain in the **model_download** worker (not provider_io)
- Local model residency remains Model Control Plane (not provider_io)
- When provider_io workers are unavailable, production paths raise
  `PROVIDER_EXECUTION_UNAVAILABLE` — they do **not** fall back to Control Plane HTTP

Provider health ≠ worker health. An open circuit for one SaaS must not restart workers.

### Model download (`model_download`)

Heavy Hugging Face / Ollama model acquisition runs in the `model_download` pool
(default count: 1). Control Plane validates and enqueues; workers own transfer,
resume (`.part` + Range), verification, progress, and cancellation.

### MCP execution (`mcp_execution`)

Long `tools/call` execution prefers the `mcp_execution` pool when API runners
are externalized. Connect / handshake / `tools/list` / health remain Control
Plane control traffic on `McpBridge`.

## Knowledge commit

Single serialized commit lane: `knowledge.commit` pool → `KnowledgeCommitter`.
Artifacts carry provenance; assimilation goes through existing KnowledgeAssimilationService / KnowledgeStore.

## APIs / operator

- `GET/POST /api/jobs`, `GET /api/jobs/{id}`, `POST .../cancel`, `POST .../retry`, `GET .../children`
- `GET /api/workers`, `GET /api/workers/pools`
- Operator CLI: `jobs list|cancel`, `workflows list|run|cancel`, workers status commands

## Troubleshooting

- Stale worker rows ≠ live workers (PID alone is not health).
- Second supervisor fails with lease held — recover after TTL.
- OCR/rerank pool count 0 until backends configured — capability unavailable is honest.
- If work piles in QUEUED with no RUNNING: check pool counts and `EXTERNALIZE_API` / domain runner env.
