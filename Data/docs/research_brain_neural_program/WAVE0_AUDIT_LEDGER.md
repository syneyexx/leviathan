# WAVE 0 — Research / Brain / Neural Production Audit Ledger

**Baseline main SHA:** `4b2664fe0372bcd0975a380a94b30464dee0907e`  
**Fetched:** 2026-10-01 — `origin/main` matches exactly (no newer commits).  
**Branch:** `cursor/research-brain-neural-production-df9b`  
**Excluded trees:** `Data/HADES/`, `editor/` (not scanned).

Canonical authorities (confirmed from README + `Leviathan_system_backend.md` / frontend companion):

| Concern | Authority |
|---|---|
| General research | `ResearchService` / `ResearchStore` |
| Heavy execution | `JobRuntime` + Worker Fabric |
| Source ingestion | `SourceIngestion` subsystem |
| Dataset learning | `DatasetService` / `compute_dataset_learning_state` |
| Knowledge | `KnowledgeStore` |
| Brain | Facade / read projection only |
| Memory | Canonical Memory |
| Neuro | Advisory / model-runtime |

Docs already claim Research fail-closed externalization (`Leviathan_system_backend.md` §15). Live code still contains fail-open paths — this program closes that gap.

---

## Defect ledger (Wave 0 disposition)

### Research

| ID | Disposition | Evidence summary |
|---|---|---|
| R-001 | **CONFIRMED** | `enqueue_run`: `externalized and job_runtime` else `_spawn_run` (`service.py` ~1197–1221) |
| R-002 | **CONFIRMED** | Same pattern: `add_url_source`, `regenerate_report`; `request_web_probe` / `request_plan` fail differently |
| R-003 | **CONFIRMED** | `_runners_externalized` except → `return False` (authorizes in-process) |
| R-004 | **CONFIRMED** | `_research_worker_availability` except → `(True, None)` |
| R-005 | **CONFIRMED** | `worker.py` `_fence()` merges cancel + lease_lost → `_fail`/FAILED |
| R-006 | **CONFIRMED** | `cancel()` swallows JobRuntime exceptions; may mark CANCELLED while job lives |
| R-007 | **CONFIRMED** | `execute_fetch_url` ignores reserved `source_id`; `from_web_page` mints new UUID |
| R-008 | **CONFIRMED** | `connect_dataset` trusts caller `indexed` bool; no DatasetService check |
| R-009 | **CONFIRMED** | Caps registered in builtins/JobRuntime; worker returns unsupported for retrieve/synthesize |
| R-010 | **CONFIRMED** | `list_projects(limit=100/200)` in enqueue/reconcile; no cursor continuation |
| R-011 | **CONFIRMED** | Planner/question_model silent deterministic fallback (audit enrichment provenance) |
| R-012 | **PARTIAL** | Promotion errors stored in `model_profile` but no first-class status fields; COMPLETED still UI-primary |
| R-013 | **CONFIRMED** | `useResearchWorkspace` `.catch(() => ({ sources: [] }))` etc. |
| R-014 | **CONFIRMED** | Polling lacks stale/abort/hidden-tab discipline (to verify in detail during Wave 8) |
| R-015 | **CONFIRMED** | `probeResearchWeb` path can toast finished on queued accept |
| R-016 | **CONFIRMED** | Mixed 200 queued vs completed semantics across research ops |

### Brain

| ID | Disposition | Evidence summary |
|---|---|---|
| B-001 | **CONFIRMED** | `useBrainOverview.ts` ~757 `s.includes("ready")` etc. |
| B-002 | **CONFIRMED** | Cognition status OR with `reasoning_enabled` (Wave 6 detail) |
| B-003 | **CONFIRMED** | Availability/data presence used as health |
| B-004 | **CONFIRMED** | Frontend sets `catalog_complete: true, bounded_projection: false` on last page |
| B-005 | **CONFIRMED** | Visible vs global counts not separated cleanly |
| B-006 | **CONFIRMED** | Bounded list limits presented as totals |
| B-007 | **CONFIRMED** | Heuristic tag/label linkage (Wave 6) |
| B-008 | **CONFIRMED** | Unknown types → entity fallback in category mapper |
| B-009 | **CONFIRMED** | `BRAIN_CATEGORY_HEX` local hex map |

### Learning / Knowledge / Neuro / Dead

| ID | Disposition | Evidence summary |
|---|---|---|
| L-001 | **CONFIRMED** | `datasetLearningState.ts`: `not_learned → READY_FOR_INDEX` |
| L-002 | **INVESTIGATE** | `VALIDATING` / `STALE_JOB` exist in enum; transition reachability TBD |
| L-003 | **PARTIAL** | `brain_status_for_dataset` delegates to same compute — good; verify no drift |
| L-004 | **INVESTIGATE** | First-500 reconciliation pattern expected; confirm in DatasetService |
| L-005 | **INVESTIGATE** | JobRuntime-null enqueue path in DatasetService |
| K-001 | **PRESERVE + TEST** | Distinction exists; need cross-surface regression |
| K-002 | **INVESTIGATE** | `list_relation_atoms(limit=500)` filtering |
| K-003 | **INVESTIGATE** | Heavy provider construction sites |
| K-004 | **INVESTIGATE** | Prefix-based identity across research/SI sync |
| N-001..N-005 | **INVESTIGATE** | Neuro honesty boundary — Wave 7 |
| D-001..D-005 | **INVESTIGATE** | Cleanup deferred to Wave 10 after functional fixes |

---

## Architecture map (control → execution)

```text
Research UI (useResearchWorkspace)
  → api/client.ts
  → /api/research/* (routes/research.py)
  → ResearchService
  → ResearchStore (CONTROL SQLite research_* tables)
  → JobRuntime (research.plan|advance|fetch_url|report.generate|web.probe)
  → research worker (process_research_job)
  → ResearchRunner / Coordinator
  → Evidence/Claims/Report
  → optional assimilation → KnowledgeStore
  → BrainQueryFacade projection
  → Brain UI

Dataset connect must resolve DatasetService.learning_state_for_dataset
Neuro remains advisory (cortex/residual ≠ evidence authority)
```

Wave 0 acceptance: dispositions recorded; baseline SHA fixed; no implementation beyond ledger until Wave 1 contracts.
