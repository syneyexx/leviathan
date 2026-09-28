# Source Ingestion — authority map

Canonical production owner: **Worker Fabric → `source_ingestion` pool**
Entrypoint: `Data.modules.workers.entrypoints.source_ingestion`

## Ingress paths (excluding HADES/editor)

| Product path | Creates research source? | Enqueues `source_ingestion.process`? | Notes |
|---|---|---|---|
| Research upload `POST …/sources/upload` → `accept_upload` | Yes | **Yes** (JobRuntime) | Canonical SI ingress |
| Same upload when SI unavailable + not externalized | Yes (legacy UploadIngestor) | No | Sync parse — fail-closed when fabric externalized |
| SI archive child `_ensure_child_source` | Yes | No | Same parent job processes children |
| `add_url_source` / web research | Yes | No | Uses `research.fetch_url` / coordinator paths |
| Research coordinator local/seed/web hits | Yes | No | Not SI pipeline |
| SI `retry` | Reuses | Yes (`.process`) | |
| SI brain-retry | Reuses | `.brain_retry` | |

## Forbidden pattern

Source row created with a product claim of “in ingestion pipeline” but **no** durable job and no explicit non-queued state.

## Idle semantics

`queue=0` + worker READY ⇒ `IDLE_NO_WORK` / `NO_QUEUED_WORK` — healthy, not an error.
