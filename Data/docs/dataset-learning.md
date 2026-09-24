# Dataset Learning

Integrated pipeline that turns registered datasets into searchable knowledge in the
**existing** KnowledgeStore / Brain — no second brain, no parallel job queue.

## Pipeline

Phases on the existing `dataset_jobs` INDEX path:

1. `source_check` — verify storage path
2. `materializing` — when RAW needs canonical JSONL
3. `parsing` / `indexing` — streaming records → KnowledgeStore documents + chunks
4. `embeddings` — honest status (`semantic_embeddings` | `non_semantic_fallback` | `lexical_only`)
5. `relations` — evidence-backed atoms only (`directional_relation_atoms`)
6. `verifying` / `publishing` — READY index + projection manifest + sidecar refresh

A dataset is **geleerd** only when a READY `dataset_indexes` row exists.

## Configuration

| Env | Default | Meaning |
|-----|---------|---------|
| `LEVIATHAN_DATASETS_AUTO_INDEX_READY_TO_KNOWLEDGE` | `true` | Auto-enqueue INDEX when a version becomes READY |
| `LEVIATHAN_DATASET_JOBS_RUNNER` | `inprocess` | `inprocess` \| `external` \| `none` |
| `LEVIATHAN_DATASET_INDEX_BATCH_SIZE` | `50` | Progress/checkpoint cadence while streaming |
| `LEVIATHAN_DATASET_MAX_RELATIONS_PER_DOC` | `24` | Cap verified relations per record |
| `LEVIATHAN_DATASET_EXTRACT_RELATIONS` | `true` | Enable grounded relation extraction |
| `LEVIATHAN_EMBEDDING_PROVIDER` | (settings) | Existing provider; null/hash are never labeled semantic |

## Worker (Windows / Unix)

Use **either** the API in-process runner **or** an external worker — never both.

**Claim owner when externalized:** Job Kernel capability `dataset.process`
(`worker_pool=dataset`). Domain `dataset_jobs` keeps metadata and progress;
`scripts/dataset_worker.py` / the `dataset` pool claims kernel leases and then
CAS-claims the linked domain row by id. Do not run a second domain
`claim_next_queued` loop while `LEVIATHAN_DATASET_JOBS_RUNNER=external`.

```bat
REM Windows — stop competing in-process runner first
set LEVIATHAN_DATASET_JOBS_RUNNER=external
python scripts\dataset_worker.py
```

```bash
# Unix
export LEVIATHAN_DATASET_JOBS_RUNNER=external
python scripts/dataset_worker.py
# or: python -m Data.modules.datasets.worker
```

Kernel linkage on enqueue: `domain_entity_type=dataset_job`,
`domain_entity_id=<domain job id>`,
`idempotency_key=dataset:process:{domain_job_id}`.

A PID lock file next to the DB refuses a second concurrent executor.

## Sidecars & recovery

Each dataset gets `datasets/raw/{datasetId}/.leviathan-dataset.json` (atomic write).
After a clean install, `POST /api/datasets/sidecars/reconcile` restores catalog rows from
validated sidecars under allowed roots only. Tombstones (`.leviathan-dataset.deleted`)
block auto-restore of intentionally deleted datasets. Sidecars do **not** replace the catalog
or KnowledgeStore.

## Agents page

System agent **Dataset Learning** (`metadata.systemKey=dataset_learning`) is ensured on every
boot (including upgraded DBs). `GET /api/agents/dataset-learning` returns that agent plus live
`dataset_jobs` activity (phase, progress, rows/chunks, relations accepted/rejected, embedding
mode, errors). No fictional missions or success percentages.

## Migrations

No new migration version is required — uses existing dataset / knowledge tables.
Relation upserts use `ON CONFLICT(atom_id)` on `directional_relation_atoms`.

## Limitations

- Relation extraction is rule/structure-based; optional model extractors are an extension point only.
- Hash / null embedding providers produce non-semantic vectors or lexical-only indexes — always labeled honestly.
- Mid-job resume skips through `checkpoint.lastRecordId` when retrying with `resume=true`.
- Transform/validate/dedupe handlers may still load materialized JSONL fully; materialize + index paths stream.
