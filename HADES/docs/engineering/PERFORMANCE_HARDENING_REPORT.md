# HADES performance hardening report

Base `main` SHA: `42334c4bcb3df1fed8e2f3c3a7c04d3b2525990c`  
Branch: `cursor/performance-hardening-4414`  
Host: Linux 6.12, Python 3.12, Node 22.14 (Cloud Agent). No LM Studio, no Windows desktop, no GPU telemetry.

## How this was measured

Counters live in `backend/perf.py`. SQLite/WAL before/after used the same test loop with `wal_owner` strategies `truncate_on_close` (legacy) vs `owned` (shipped). Memory FTS vs linear used 1500 inserted rows. Stream coalescing was unit-tested without a browser. Live Chat TTFT against LM Studio is **UNVERIFIED_ON_HOST**.

| Area | Baseline | After | Delta | Confidence | Tests |
| ---- | -------: | ----: | ----: | ---------- | ----- |
| WAL truncates / 40 chat persists | 120 (`truncate_on_close`) | 0 (`owned`) | −120 truncates | high | `test_sqlite_wal_performance` |
| 40 chat persist wall ms | 1237 ms | 1162 ms | −6% this host | medium | same (SSD; TRUNCATE cheaper here than on contended Windows HDD) |
| SQLite busy during concurrent R/W | 0 | 0 | none | high | concurrent read/write test |
| `list_messages` 50 / 250 / 1000 | 4.40 / 4.38 / 4.64 ms | same path | no UX cliff | high | scale test — **pagination not shipped** |
| Memory FTS vs Python scan (1504 rows) | 10.51 ms list+scan | 1.10 ms FTS MATCH | ~9.5× | high | `test_memory_fts` |
| Discovery upstream per TTL window | 1 miss + N repeats | 1 miss then hits | extra `/models` avoided | high | `test_model_discovery_cache` |
| Chat vision rediscovery | second `discover_models()` | reuse `_discovered_models` | 1 fewer upstream/chat when cache warm | medium (source + cache tests; live Chat UNVERIFIED_ON_HOST) | `test_model_discovery_cache`, `test_chatbot_llm_pipeline_fixes` |
| Stream React commits | 1 commit / delta | first immediate, then ~25 Hz + terminal flush | grouped updates | high (unit) / UNVERIFIED_ON_HOST (browser Hz) | `tests/stream-coalesce.test.mjs` |
| Plugin dependency poll | 850 ms | 2500 ms | −66% request rate when that overlay is open | high (constants) | poll contract test |
| Research/Tasks active poll | 1500 ms | 4000 ms + hidden-tab skip | −62.5% | high (constants) | same |
| Chat usage telemetry poll | 1000 ms always | 2000 ms while sending, 12000 ms idle | less Chat-path HTTP | high (constants) | same |
| Chat approvals poll | 4000 ms | 8000 ms | −50% | high | same |
| RunEventBus RAM (40 terminal runs × 25 deltas) | 40 full buckets | compact after grace (`reap(force)`) | events bounded to terminals | high | `test_run_event_bus_lifecycle` |
| Live model TTFT / tokens/s | — | — | — | UNVERIFIED_ON_HOST | needs LM Studio |
| Chat incoming deltas/sec in UI | — | — | — | UNVERIFIED_ON_HOST | needs browser |
| GPU / VRAM scheduling | — | not implemented | — | n/a | Phase 12 deferred |

## Optimizations rejected after measurement

- **Message pagination / timeline virtualization:** `list_messages` for 1000 rows stayed ~4.6 ms on this host (same order as 50). No SQLite cliff. DOM cost in the browser is **UNVERIFIED_ON_HOST**; do not ship pagination without that UI measurement (Phase 10).
- **Conversation snapshot endpoint:** no evidence that Chat-open latency is API fanout; Phase 11 skipped.
- **`synchronous` PRAGMA / extra connection pooling:** not changed; durability left alone.
- **Inference HTTP connection pooling:** skipped to keep per-run cancellation isolation (Phase 9 later).
- **Hardware-aware model concurrency:** no GPU/VRAM samples on this host (Phase 12).
- **Derived-work lane / Knowledge `executemany` rewrite:** no ingestion bottleneck measured here.
- **Static frontend serving instead of Vite preview:** startup/RAM of preview process **UNVERIFIED_ON_HOST**.

## Remaining bottlenecks (honest)

- LM Studio generation still dominates real Chat latency; this pass removes *unnecessary* work around it.
- WAL TRUNCATE removal is more important on lock-contended Windows disks than on this Linux SSD (−6% persist time only).
- Memory FTS gain grows with collection size; 84-item sets are already sub-millisecond either way.
- Frontend Chat still mounts the full message list; browser 5k-message DOM is unmeasured.
- Health/diagnostics still does real work when opened; `/api/health/live` remains the cheap probe.

## Regression risks

- WAL files can grow until PASSIVE interval or shutdown TRUNCATE; shutdown now truncates explicitly.
- Stale model list for up to `model_refresh_seconds` (default 60s); empty lists and LM errors invalidate; connection test / diagnostics force refresh.
- Stream coalescing must flush on terminal/cancel; covered by unit tests, reconnect path unchanged (sequence still applied immediately).
- RunEventBus compact after 90s may empty in-memory reconnect history; durable Flight Recorder remains the owner. Grace + subscriber hold prevent eviction during live reconnect.

## Benchmarks actually executed

```
PYTHONPATH=backend python3 -m unittest tests.test_sqlite_wal_performance tests.test_model_discovery_cache tests.test_memory_fts tests.test_run_event_bus_lifecycle tests.test_database tests.test_events_and_voice_p0 tests.test_run_event_bus_backpressure_honesty tests.test_chatbot_llm_pipeline_fixes tests.test_health_probes tests.test_conversation_forget_atomicity -v
→ 51 tests OK (plus later Memory FTS 1500-row bench OK)

node --test tests/stream-coalesce.test.mjs
→ 2 tests pass
```

Full `verify_hades.py`, Windows PREPARE/VERIFY, live LM Studio Chat, and browser stream Hz: **UNVERIFIED_ON_HOST**.
