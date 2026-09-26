# LEVIATHAN External Execution Fabric — Engineering Report

Generated: 2026-09-25 · Branch: `cursor/external-execution-fabric-8615` · PR: #163

## 1–2. Process topology

**Original (pre-change effective posture):** Workers/supervisor/externalize already existed, but Python/`resolve_runner_mode` defaults for dataset/source-ingestion were `inprocess`, Agents/Coding/outbound defaulted OFF, Master Gate treated outbound-enabled as unhealthy, BAT lacked fabric inventory, Agents “Active Workers” risked confusion, and there was no aggregate job-joined dashboard.

**Final:**

| Process | Role |
|---------|------|
| API / Control Plane | HTTP, validate, auth, enqueue, read models |
| Worker Supervisor | Spawn/lease/restart/drain all pools |
| Specialist workers | Heavy domain execution (one OS process per slot) |
| Model serving | Unchanged separate residency plane |

## 3–4. Responsibilities

- **API PID:** FastAPI composition root; no heavy research/dataset/PDF/chunk/embed/commit/coding/agent loops when externalize is ON.
- **Supervisor:** Singleton lease, pool reconcile, resource admission, consolidated terminal events + periodic `[FABRIC]` summary.

## 5–9. Pools (from live `POOL_CATALOG`)

25 pools · 21 enabled · **22 desired** · Runtime QA: **22 running**.

Disabled/optional: `knowledge_commit` (deprecated→db_commit), `rerank`, `document_ai`, `telemetry`.

## 10–19. Heavy paths

Already routed via JobRuntime + pools; this change **locks production defaults to EXTERNAL**, forbids inline fallback when externalize ON, and makes ownership observable (dashboard/BAT/UI).

## 20–26. Surfaces changed

- `main.py`: outbound gate honesty; `/api/workers/dashboard`, `/api/workers/{id}`
- Supervisor bootstrap: fabric banner, pool/worker inventory, periodic summary
- `run_leviathan_workers.bat`: single consolidated fabric window
- Agents `WorkerPoolsPanel`: Worker Fabric tabs (Pools/Workers/Jobs/Failures)
- Config/catalog/.env.example: external + always-on core + outbound ON

## 27–28. System Prompt / Outbound

- Live System Prompt hot-reload preserved (behavior revision / immutable snapshot — prior work).
- Outbound default **ON**; SSRF/private-network/ExecutionGateway still enforced. Master Gate no longer fails merely because outbound is allowed.

## 29–32. Files / migrations / tests

**Added:** `workers/dashboard.py`, `workers/console.py`, `workers/metrics.py`, `test_external_execution_fabric.py`

**Modified:** config, settings catalog, runners, bootstrap, BAT, Agents UI, architecture doc, related tests

**Migrations:** none required (derived from existing Job/Registry)

## 33–34. Commands & results

```
PYTHONPATH=/workspace python3 -m pytest Data/backend/tests -q
# 1405 passed, 5 xfailed (excluding pre-existing pypdf-installed env tests)

cd Data/frontend && npm run typecheck && npm test -- --run && npm run build
# typecheck OK · 156 tests passed · build OK
```

Pre-existing env failures (pypdf installed so “without_pypdf” tests fail) not introduced by this change.

## 35–38. Runtime QA (actual)

- API on `:18765` (control plane process)
- Supervisor PID **7601**
- **22** specialist workers with distinct PIDs (e.g. dataset-0=7606, coding-0=7613, research pool present, db_commit-0=7617, embedding-0=7618)
- Fabric summary: `pools=25 enabled=21 desired=22 running=22 busy=0 degraded=0 status=READY`
- Health latency while fabric up: **~46 ms**
- Worker PIDs ≠ supervisor PID ✓

## 39–42. Remaining

- Interactive Chat/model inference still orchestrated by API via model control plane (by design — not a domain job loop).
- Child worker stdout still primarily log-files; lifecycle/progress via WorkerEventEmitter + registry/jobs (canonical).
- Optional: deeper per-domain E2E job progress demos under load (fabric + API responsiveness verified at idle/start).

## 43–45. Confirmations

- No mocked workers in UI/BAT
- **HADES/** untouched
- **editor/** untouched
