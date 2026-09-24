# Background workers

## Topology

```
API/control plane  →  durable JobStore/JobRuntime
                   →  Worker Supervisor (separate OS process)
                   →  pool entrypoints (dataset, knowledge_*, embedding, research, …)
                   →  atomic Brain/result commit
```

Do **not** introduce Celery/Redis/RQ. Use existing `Data/modules/jobs` + `Data/modules/workers`.

## Windows launch

- `run_leviathan.bat` — web/control plane; may report worker health; optional `LEVIATHAN_WORKERS_AUTOSTART=1`
- `run_leviathan_workers.bat` — Worker Supervisor only (no web backend)

Both are relocatable (`PYTHONPATH=%~dp0`, `.venv\Scripts\python.exe`).

## Pools

Knowledge: source_ingestion, document_ai, knowledge_prepare, embedding, rerank, knowledge_commit  
Dataset: dataset (+ provider_io where relevant)  
Research / Training / Utility: existing entrypoints mapped in `pools.py`

Interactive chat stays in-process (settings snapshot, gate, fast search, context, stream normalize, persist).

## Atomic index generations

`Data/modules/knowledge/index_generations.py` — build N+1 → validate → atomic ACTIVE pointer switch. Chat sees only complete generations.
