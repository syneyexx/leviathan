# LEVIATHAN Execution Fabric

Control plane (FastAPI) validates, authorizes, enqueues, cancels, and streams status.
Durable work runs in the **Job Kernel** under a **generic Worker Supervisor**.

Model-serving processes remain owned by the **Model Control Plane / ServingSupervisor**.
One Brain remains the single canonical knowledge fabric.

## Compute tiers

| Tier | Owner | Examples |
|------|-------|----------|
| 0 | Deterministic framework | parse, chunk, hash, SQL, math, dedupe, citations |
| 1 | Specialist | embeddings, rerank, OCR, NER |
| 2 | Small/utility model role | rewrite, extract, normalize |
| 3 | Main reasoning model | plan, adjudicate, synthesize |

Escalation: Tier0 → Tier1 → Tier2 → Tier3. No infinite loops. Main LLM is not used for Tier0 work.

## Processes

```text
run_leviathan.bat / leviathan.py
  → bootstrap all
      → API process (FastAPI)
      → generic worker supervisor
          → pool workers (research, coding, datasets, …)
```

Set `LEVIATHAN_WORKERS_EXTERNALIZE_API=true` (default) so FastAPI does not start heavy domain daemon threads.

## Job Kernel

Canonical scheduler: `Data/modules/jobs`.

- States: CREATED, QUEUED, RUNNING, RETRY_WAIT, CANCEL_REQUESTED, COMPLETED, FAILED, CANCELLED
- Atomic claim + lease; heartbeat; expired lease recovery
- Delivery: **at-least-once**
- Cancel: RUNNING → CANCEL_REQUESTED → worker ack → CANCELLED

## Worker pools

See `Data/modules/workers/pools.py`. Counts via `LEVIATHAN_WORKERS_POOL_<NAME>_COUNT`.

## Knowledge commit

Single serialized commit lane: `knowledge.commit` pool → `KnowledgeCommitter`.
Artifacts carry provenance; assimilation goes through existing KnowledgeAssimilationService / KnowledgeStore.

## APIs

- `GET/POST /api/jobs`, `GET /api/jobs/{id}`, `POST .../cancel`, `POST .../retry`, `GET .../children`
- `GET /api/workers`, `GET /api/workers/pools`

## Troubleshooting

- Stale worker rows ≠ live workers (PID alone is not health).
- Second supervisor fails with lease held — recover after TTL.
- OCR/rerank pool count 0 until backends configured — capability unavailable is honest.
