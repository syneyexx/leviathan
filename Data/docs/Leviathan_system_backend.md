# LEVIATHAN System Backend Reference

> **Canonical backend reference.** This file is the single human-readable source of truth for LEVIATHAN backend architecture, runtime ownership, persistence, execution, intelligence, research/trading systems, security boundaries, verification and exact code locations.
>
> **Snapshot:** `main` at `1c30a3d062b03f8b77eb14b9ae8dee16979fcb61` (2026-09-28), after the autonomous trading research closed-loop merge. Runtime code, schemas and executable tests remain authoritative when prose and behavior disagree.
>
> Frontend companion: [`Leviathan_system_frontend.md`](./Leviathan_system_frontend.md).

---

# 1. Documentation contract

`Data/docs/` has exactly two canonical LEVIATHAN system documents:

1. **`Leviathan_system_backend.md`** — everything behind the UI: composition, APIs, databases, cognition, models, knowledge, workers, agents, research, training, modules, security, trading, verification and file ownership.
2. **`Leviathan_system_frontend.md`** — everything rendered or operated in the React client: routes, shell, pages, state, API client, components, styles and file ownership.

Component-local README files, test manifests and generated reports may still live beside code because they are implementation evidence, not competing system architecture documents. New system-level information belongs in one of these two files.

Status vocabulary used here:

- **CURRENT** — implemented on the snapshot above.
- **FEATURE-GATED** — code exists, runtime availability depends on configuration, hardware, credentials or an external dependency.
- **UNMEASURED / UNAVAILABLE / BLOCKED** — explicit runtime truth, never an implicit PASS.
- **BOUNDARY** — intentional adapter/stub/guard; no larger capability is claimed.
- **TARGET** — only used when discussing a machine program or future gate; it is not current product truth.

The repository follows one overriding rule: **one responsibility → one canonical owner**. Do not solve a feature by adding a parallel `*V2`, second queue, second model router, fourth product database or private subsystem client.

---

# 2. What LEVIATHAN is

LEVIATHAN is a **local-first AI control plane, cognitive runtime and operator platform**. It composes models, cognition, retrieval, memory, evidence, tools, approvals, agents, background workers, research, datasets, training/evaluation, external capability modules and a causal market-research/paper-trading environment into one supervised system.

The main backend shape is:

```text
Operator / React frontend
        |
        v
FastAPI Control Plane                         Data/backend/main.py
        |
        +--> Settings + BehaviorProfile       Data/modules/settings/
        +--> Chat + CognitiveRuntime          Data/modules/cognition/
        |       +--> Brain facade             Data/modules/brain/
        |       |      + Knowledge/RAG        Data/modules/knowledge/
        |       |      + Memory               Data/modules/memory/
        |       |      + Evidence             Data/modules/evidence/
        |       |      + Neuro (advisory)     Data/modules/neuro/
        |       +--> CapabilityBroker
        |              + ExecutionGateway     Data/modules/execution/
        |              + ModuleManager/MCP
        +--> Model Control Plane              Data/modules/models/
        |       + model runtime/providers     Data/modules/model_runtime/
        +--> Agent/Coding/Research services
        +--> MarketSim research + paper
        +--> JobRuntime                       Data/modules/jobs/
                |
                v
        Worker Fabric                         Data/modules/workers/
                |
                + heavy CPU/I/O/GPU work
                + DB Commit Coordinator

Durable state:
    CONTROL   -> control/jobs/settings/runtime metadata
    KNOWLEDGE -> documents/chunks/research knowledge
    MARKET    -> market simulation/research/paper state
    Artifacts -> ArtifactStore/file-backed payloads
```

The Python API remains the only HTTP control plane. The native launcher supervises it; workers execute heavy durable work; model residency is a separate execution concern; the React app is an operator surface, not an authority.

---

# 3. Repository and process topology

## 3.1 Top-level locations

| Path | Responsibility |
|---|---|
| `leviathan.py` | primary Python application bootstrap used by launchers |
| `Data/backend/` | FastAPI composition, configuration, database upgrade and HTTP routes |
| `Data/modules/` | canonical domain implementations |
| `Data/functions/` | FunctionRuntime cold-path functions |
| `Data/external_capabilities/` | declarative external module manifests/catalog content |
| `Data/frontend/` | React operator UI; documented in the frontend reference |
| `Data/launcher/` | native/Tauri backend host and process supervisor |
| `Data/native/` | native compute/data-plane implementation/binaries when present |
| `scripts/` | worker launchers, verification harnesses and maintenance scripts |
| `.env.example` | documented environment controls/defaults |
| `installer.bat` | Windows installer/bootstrap helper |
| `run_leviathan.bat` / `run_leviathan.exe` | operator launch paths |
| `run_leviathan_workers.bat` | manual/advanced Worker Fabric recovery path |
| `upgrade_leviathan_databases.bat` | three-database upgrade entrypoint |
| `Data/HADES/` | separate submodule/boundary; not a canonical LEVIATHAN backend owner |
| `editor/` | separate editor product tree; not a canonical LEVIATHAN backend owner |

## 3.2 Runtime processes

**Control plane:** FastAPI in `Data/backend/main.py`. It validates/routs requests, resolves settings/authority, enqueues durable work and serves lightweight/read APIs.

**Worker plane:** `Data/modules/workers/` with `WorkerSupervisor`, pool registry, leases, admission and domain entrypoints. Heavy work must not silently fall back into FastAPI when externalization is enabled.

**Model plane:** `Data/modules/models/` + `Data/modules/model_runtime/`; model routing/residency is independent from worker queue ownership.

**Native host:** `Data/launcher/`; supervises Python and exposes local host lifecycle. It is not a second API or queue.

Production boot contract:

1. launcher/bootstrap starts the API process;
2. it waits for bounded loopback `GET /api/host/liveness`;
3. only after FastAPI lifespan bootstrap is proven does WorkerSupervisor start;
4. supervisor verifies CONTROL schema readiness;
5. workers are healthy only after process alive + registered + READY + heartbeat.

Relevant files: `Data/modules/workers/bootstrap.py`, `process.py`, `supervisor.py`, `loop.py`, `registry.py`, `pools.py`, `protocol.py`, `settings.py`, `admission.py`, `events.py`, `crash_diagnostics.py`, and `entrypoints/`.

---

# 4. Backend composition root and configuration

## 4.1 `Data/backend/main.py`

`main.py` is the **composition root**. It constructs shared stores/services, binds dependencies to routers, installs middleware, owns lifespan boot/shutdown, retains `POST /api/chat`, serves the SPA shell and exposes `/api/health`.

It wires, among others:

- database paths/upgrades and core stores;
- Settings Control Plane + BehaviorProfile;
- KnowledgeStore, retrieval, Brain, Memory, Evidence and Neuro;
- Model Control Plane/model runtime;
- FunctionRuntime, capability catalog, ExecutionGateway and approvals;
- JobRuntime, workers and resource admission;
- AgentRuntime/Fleet, CodingControlPlane, ResearchService;
- Dataset, training, evaluation, release and verification systems;
- ModuleManager, PluginRegistry, MCP and external capability fabric;
- MarketSimControlPlane, TradingOrchestra and Research Command;
- browser/media/voice/multimodal boundaries;
- observability, metrics, security, backup and product-truth services.

If a new backend subsystem needs a singleton dependency, its construction belongs here or in an established composition helper, not in a route handler.

## 4.2 Configuration files

| File | Role |
|---|---|
| `Data/backend/config.py` | typed environment/default configuration and canonical DB paths |
| `.env.example` | human-readable environment catalogue |
| `Data/modules/settings/catalog.py` | operator-visible setting definitions |
| `Data/modules/settings/service.py` | settings control service |
| `Data/modules/settings/store.py` | persisted settings |
| `Data/modules/settings/validation.py` | type/range/enum validation |
| `Data/modules/settings/bindings.py` | hot-apply bindings to live consumers |
| `Data/modules/settings/behavior.py` | behavior profile contract |
| `Data/modules/settings/behavior_store.py` | persisted behavior profile |
| `Data/modules/settings/resolver.py` | immutable behavior snapshot per operation |
| `Data/modules/settings/seed.py` | first-install/bootstrap behavior seed |

Environment/default configuration establishes boot values. Persisted settings are the durable operator layer where supported. HOT settings bind live; restart-required settings must not be presented as already applied.

BehaviorProfile controls model-facing identity/interaction behavior. It is **not** technical authority. Approval/permission remains in `Data/modules/approvals/` and ExecutionGateway policy.

---

# 5. Persistence: exactly three canonical SQLite databases

LEVIATHAN has **exactly three product metadata databases**:

```text
CONTROL   LEVIATHAN_CONTROL_DATABASE_PATH
          default Data/backend/data/leviathan_control.db

KNOWLEDGE LEVIATHAN_KNOWLEDGE_DATABASE_PATH
          default Data/backend/data/leviathan_knowledge.db

MARKET    LEVIATHAN_MARKET_DATABASE_PATH
          default Data/backend/data/leviathan_market.db
```

`LEVIATHAN_DATABASE_PATH` is legacy upgrade input only. `settings.database_path` is a CONTROL compatibility alias. A subsystem must not introduce a fourth product SQLite authority.

Primary files:

| File | Responsibility |
|---|---|
| `Data/backend/database.py` | core SQLite access/bootstrap compatibility |
| `Data/backend/migrations.py` | preserved legacy single-DB migration history (1..56) |
| `Data/backend/db_upgrade.py` | fresh 3-DB bootstrap + legacy cutover + domain migrations |
| `Data/backend/table_ownership.py` | canonical table→CONTROL/KNOWLEDGE/MARKET ownership |
| `Data/modules/common/sqlite_policy.py` | busy-timeout/WAL/hot-path connection policy |
| `Data/modules/db_commit/` | bulk canonical write coordinator |
| `Data/modules/sqlite_manager/` | operator DB inspection/controlled mutation surface |
| `Data/backend/routes/sqlite_manager.py` | `/api/sqlite/*` HTTP surface |

Current domain migration history includes CONTROL additions through dependency-aware external-install operations (domain v6) and MARKET autonomous-research hypotheses (domain v7). Never infer a future migration number from this document: inspect `DOMAIN_MIGRATIONS` in `db_upgrade.py` before adding the next migration.

## 5.1 Write classes

**CONTROL_WRITE** — small latency-sensitive writes may be direct when policy permits: job state, heartbeat, lease/cancel flags, bounded operator mutation.

**COMMIT_WRITE** — substantial canonical mutations use `Data/modules/db_commit/`: Knowledge chunks/embeddings, bulk research records, dataset index batches, market/evaluation/training lineage and similar heavy writes.

DB Commit Coordinator rules:

- one managed external writer pool (`db_commit`) with independent CONTROL/KNOWLEDGE/MARKET lanes;
- typed `CommitIntent`, allowlisted handlers, hashes and references — no arbitrary SQL payloads;
- durable spool under each DB parent for correctness/recovery;
- idempotent receipts before replay;
- bounded batches release SQLite locks between batches;
- unavailable writer means durable backpressure/failure, never silent direct heavy-write fallback.

## 5.2 SQLite Manager

`Data/modules/sqlite_manager/` and `Data/backend/routes/sqlite_manager.py` expose operator tooling over all three DBs: overview, schema/table/index/FK inspection, bounded row browse, parameterized PK-safe CRUD, read-only SQL, guarded INSERT/UPDATE/DELETE, integrity checks, WAL checkpoint, ownership audit, contention/runtime data and backup metadata.

It is **not** a new persistence layer and does not own schema DDL. Migrations remain the schema authority.

---

# 6. HTTP/API architecture and mutation security

Domain route modules live in `Data/backend/routes/`. `main.py` binds shared dependencies into `build_*_router(...)` functions. Important route files:

| File | Domain |
|---|---|
| `agents.py` | Agent Fleet/execution/multi-agent |
| `agent_signals.py` | Signal Fabric |
| `analytics.py` | analytics |
| `approvals.py` | approval requests/decisions |
| `artifacts.py` | ArtifactStore/run artifacts |
| `brain.py` | Brain graph/search/status |
| `browser.py`, `browser_qa.py` | browser capabilities/QA |
| `capabilities.py` | capability catalog/invoke/receipts |
| `coding.py` | Coding Agent sessions/actions |
| `cognition.py` | cognition run lifecycle/events/steering |
| `conversations.py` | conversation CRUD |
| `datasets.py` | dataset lifecycle/index/offline operations |
| `efficiency.py` | efficiency/resource projections |
| `evaluation.py` | evaluation platform/harness |
| `evidence.py` | evidence store |
| `flywheel.py` | post-training candidates/promotion/lineage |
| `functions.py` | FunctionRuntime catalogue/invoke |
| `host_console.py` | native-host read projections/liveness |
| `jobs.py` | JobRuntime |
| `knowledge.py` | knowledge/RAG/Atlas/DeepRecall/Why |
| `market_sim.py` | market data, simulation, strategies, research lab, qualification, paper |
| `mcp.py` | MCP servers/sessions/tools |
| `media.py` | media capability boundary |
| `memory.py` | durable MemoryStore |
| `models.py` | model registry/providers/routing/runtime/download |
| `modules.py` | ModuleManager lifecycle/install/execute |
| `multimodal.py` | multimodal sessions |
| `neuro.py` | Neuro/Cortex/operator surfaces |
| `observability.py`, `observations.py` | live events and durable observations |
| `platform.py` | architecture/security/release/backup/chaos/context/master projections |
| `plugins.py` | PluginRegistry |
| `research.py` | general research projects/runs/sources |
| `research_command.py` | Trading Research Command composition surface |
| `schedules.py` | schedule store/runner |
| `settings.py` | Settings/BehaviorProfile |
| `skills.py` | external skill search/load/enable |
| `sqlite_manager.py` | three-DB operator control surface |
| `system.py` | telemetry/system status |
| `tasks.py` | durable tasks |
| `team.py` | TEAM quality/collaboration APIs |
| `trading_orchestra.py` | trading-only orchestras/agents |
| `training.py` | training/jobs/preference/synthetic/active-learning |
| `verification.py` | VerificationEngine/reports |
| `voice.py` | voice boundary |
| `workers.py` | Worker Fabric dashboard/control |
| `workflows.py` | workflow store/runtime |

### Central mutation authentication

Current main has a central mutation boundary in `Data/backend/main.py` backed by `Data/modules/common/http_auth.py`. Loopback mutation is allowed by local policy; non-loopback `/api` mutations require the configured operator token. The middleware protects newly mounted mutating routers so authorization is not dependent on every handler remembering a check. Token comparison is constant-time (`hmac.compare_digest`), and unsafe non-loopback startup is rejected rather than silently exposed.

Tests: `Data/backend/tests/test_central_mutation_auth.py`.

CORS for native/Vite origins is narrowly scoped and is **not authorization**. Read projections may be allowlisted; mutating authority still goes through the central policy, approvals and domain guards.

---

# 7. Chat, Cognition and TEAM

## 7.1 Chat path

`POST /api/chat` remains in `Data/backend/main.py` because it is a composition-level path. The current high-level flow is:

```text
request
 -> effective settings + BehaviorSnapshot
 -> intent/retrieval classification
 -> Brain/Memory/Evidence/Neuro perception as needed
 -> CognitiveRuntime.submit(...)
 -> TaskModel + Perception + BeliefState + WorkingMemory
 -> MetaController + CognitivePlanner + ActionSelector
 -> model / retrieval / capability / agent / verification loop
 -> cognition-owned answer (or compatible fallback path)
 -> persist public assistant turn + telemetry
```

`Data/modules/reasoning/` is the legacy lightweight intent/retrieval-classification seam. **CognitiveRuntime** in `Data/modules/cognition/` is the deep orchestration owner.

## 7.2 Core cognition files

| File | Purpose |
|---|---|
| `cognition/runtime.py` | run/submit/cancel/resume/steer/event state machine |
| `task_model.py` | typed task model/criteria |
| `perception.py` | Brain/knowledge/memory/evidence/neuro input |
| `belief_state.py` | support/contradiction/confidence state |
| `working_memory.py` | bounded in-run memory/pinned constraints |
| `meta_controller.py` | orchestration + neural compute policy |
| `compute_axes.py` | neural inference budget axis |
| `planner.py` | structured plans/replans |
| `action_selector.py` | next-action selection |
| `capability_broker.py` | bounded capability shortlist/discovery |
| `context_v3.py` | adapter into canonical ContextBuilder |
| `completion.py` | typed acceptance/completion decisions |
| `delegation.py`, `specialists.py` | specialist/agent delegation |
| `domain_strategy.py` | domain-specific strategy hooks without another runtime |
| `experience.py` | VerifiedExperience admission |
| `ttc.py` | inference-time candidate generation/scoring/pruning/repair |
| `critics.py`, `hypotheses.py`, `neural_advisor.py` | critic/hypothesis/advice support |
| `skills.py` | measured procedural skill library |
| `store.py` + hydration/checkpoint helpers | durable resume |

Reasoning modes FAST/STANDARD/DEEP/MAXIMUM change actual orchestration budgets; ADAPTIVE can change effective mode from evidence/uncertainty/failure/resource pressure. Neural compute and orchestration compute are separate axes controlled by MetaController.

Private chain-of-thought is not a persistence/API contract. Persist public plan/activity/evidence summaries, not hidden reasoning tokens.

## 7.3 TEAM collaboration

TEAM is orthogonal to reasoning depth. Canonical pieces:

- `Data/modules/cognition/team_strategy.py` — role policy + `TeamSpecialistResult`;
- `Data/modules/cognition/team_task_profile.py` — task-aware profile;
- `Data/modules/cognition/team_orchestrator.py` — DAG/follow-up/progress/no-progress;
- `Data/modules/verification/quality_contract.py` and `quality_store.py` — acceptance truth;
- `Data/backend/routes/team.py` — `/api/team/*`;
- Research TEAM mode uses the same quality-contract semantics.

Conversational TEAM uses a lightweight topology; research/coding/quantitative work keeps strict evidence/test/calculation criteria. Model-authored booleans never count as proof: artifact text and real receipt IDs are inspected.

---

# 8. Context, trust and multimodal state

Canonical context compilation is `Data/modules/context/`:

- `builder.py` — sole context compiler;
- `reference.py` — untrusted reference serialization;
- `budget.py`, `fit.py`, `tokenization.py` — token budgets;
- `compaction.py`, `hierarchical_compaction.py` — reduction;
- `bounded_cache.py`, `cache_policy.py`, `singleflight.py` — efficiency;
- `snapshots.py`, `fingerprints.py` — identity/reproducibility;
- `multimodal.py` — text/image/audio/video typed session parts;
- `types.py` — ContextPack contracts.

Instruction authority is reserved for trusted runtime/BehaviorProfile/pinned constraints. Knowledge, Memory, Evidence, web content, MCP/tool output, external module output and Neuro associations remain **data**, not system instruction authority.

Multimodal routes: `Data/backend/routes/multimodal.py`. Model vision capability truth: `Data/modules/models/vision.py`; `UNMEASURED` is never treated as `SUPPORTED`.

---

# 9. Brain, Knowledge, Memory, Evidence and Neuro

## 9.1 Brain

`Data/modules/brain/` is a facade, not another database:

- `access.py` — access contracts;
- `contracts.py` — Brain-facing types;
- `facade.py` — unified query across canonical stores;
- `compute.py` — heavy **derived** Brain computation (snapshots/analysis) for the `brain_compute` worker pool.

Bounded UI reads (`GET /api/brain/graph`, `GET /api/brain/stats`) remain inline and capped by `max_nodes`/`max_edges`. Heavy snapshot/rebuild/analyze work is enqueued as `brain.compute.snapshot` / `brain.rebuild` / `brain.analyze` onto the Worker Fabric `brain_compute` pool (`default_count=1`, `max_count=2`). Results are advisory ArtifactStore snapshots with algorithm/version provenance — never a competing Brain/graph database and never a silent Knowledge/Memory mutation.

Cognition/perception should use Brain instead of inventing private direct retrieval paths.

## 9.2 Knowledge/RAG

`Data/modules/knowledge/` owns durable documents/chunks and retrieval:

- `store.py`, `types.py` — persistence/provenance;
- `retrieval.py` — lexical+dense hybrid retrieval;
- `staged_retrieval.py` — staged/deep policy;
- `embeddings.py` — embedding interface/providers;
- `deep_recall.py` — DeepRecall;
- `atlas.py` — Atlas;
- `why_library.py` — Why Library;
- `economy.py` — retrieval budgets;
- `chunking.py`, `hashing.py`, `index_generations.py` — indexing mechanics;
- `pipeline/artifact.py`, `curator.py`, `committer.py` — preparation/commit.

Heavy ingest/index commits respect worker/DB-commit ownership. Semantic reconciliation (`knowledge.reconcile`) is owned by `knowledge_prepare`: dry-run diagnosis (missing chunks / stale embeddings) is separable from apply; bulk mutations remain `db_commit` when classified COMMIT_WRITE.

## 9.3 Memory

`Data/modules/memory/store.py`, `types.py`, `consolidation.py` and `worker.py` own durable scoped memory. Trust states distinguish agent proposal, user statement, source-derived, verified, conflicted and revoked memory. Preference corrections supersede earlier scoped preference/fact rows; retrieval stays on current ACTIVE truth.

Small Memory CRUD/search remains control-plane inline. Batch/heavy consolidation and enrichment execute on the Worker Fabric `memory` pool (`memory.consolidate` / `memory.enrich` / `memory.reconcile`). Consolidation may admit `AGENT_PROPOSED` candidates; **model confidence never becomes VERIFIED truth**.

Do not collapse conversation history, cognition WorkingMemory, durable MemoryStore, Knowledge documents, VerifiedExperience and SkillLibrary into one concept.

## 9.4 Evidence / observations / artifacts

- `Data/modules/evidence/` — durable evidence and verification-facing records;
- `Data/modules/observations/` — durable observations/tool receipts;
- `Data/modules/artifacts/` — file/large-result artifacts and hash validation.

Execution and external modules should return refs for large payloads rather than megabytes inline.

## 9.5 Neuro/Cortex

`Data/modules/neuro/` (`advisor.py`, `cortex.py`, `cortex_runtime.py`, `critic.py`, `residual.py`, `residual_orchestrator.py`, `memory_tiers.py`, `receipts.py`, `snapshots.py`, `soak.py`) is advisory. Neural associations may influence retrieval/planning/hypotheses but do not become factual or execution authority merely because a model produced them.

---

# 10. Model Control Plane and provider runtime

## 10.1 Model Control Plane — `Data/modules/models/`

This is the sole model routing/residency owner.

Key files:

- `control_plane.py` — top-level model authority;
- `inference_session.py` — canonical inference session;
- `registry.py`, `store.py`, `contracts.py` — registry state/types;
- `router.py`, `measured_routing.py` — routing policy;
- `gateway.py` — inflight/queue/error accounting;
- `residency.py`, `resource_manager.py`, `placement.py` — hardware/residency;
- `runtime_manager.py`, `runtime_binding.py`, `worker_client.py` — runtime bridge;
- `profiles.py` — persisted model profiles;
- `capability_probe.py`, `vision.py`, `efficiency_capabilities.py` — measured capabilities;
- `downloads.py`, `import_service.py`, `benchmarks.py` — acquisition/benchmarking;
- `providers/` — LM Studio, Ollama, OpenAI-compatible and other configured adapters.

A configured/listed model is not automatically resident, healthy or tool/vision/reasoning capable. Capability probes and runtime evidence determine support.

Do not abbreviate Model Control Plane as MCP: in this repository **MCP means Model Context Protocol**.

## 10.2 Model runtime — `Data/modules/model_runtime/`

- `openai_compatible.py` — provider chat/completion transport;
- `dialect.py` — provider feature adaptation without silent feature dropping;
- `inference_contract.py` — tool/schema/context contract and repair/fail-closed logic;
- `streaming.py` — separated content/reasoning/tool frames;
- `serving.py` — serving supervision/cancel;
- `managed_adapter.py`, `launch_strategy.py`, `process_control.py`, `port_allocator.py`, `llama_cpp_command.py` — managed process boundaries;
- `durable_requests.py`, `latency.py` — durable request/latency support.

Cognition uses `Data/modules/cognition/model_adapter.py`; trading agents use `Data/modules/market_sim/orchestra/model_adapter.py`. Neither should instantiate a private provider client.

---

# 11. ExecutionGateway, capabilities, functions and approvals

## 11.1 Single side-effect gateway

`Data/modules/execution/`:

- `catalog.py` — canonical capability catalogue;
- `gateway.py` — authorization/idempotency/dispatch boundary;
- `builtins.py` — built-in capability registrations;
- `manifest.py`, `metadata.py` — capability metadata;
- `receipts.py` — receipts;
- `types.py` — request/result/risk contracts;
- `workload.py` — INLINE_SAFE / EXTERNAL_PREFERRED / EXTERNAL_REQUIRED plus
  request-aware escalation via `classify_request_workload` (after path confinement);
- `file_io_thresholds.py` — centralized inline ceilings for reads/writes/hashes/copies/CSV/scans;
- `file_io_dispatch.py` — canonical enqueue helper for escalated filesystem jobs onto `file_io`.

### Size-aware filesystem classification

Static capability class remains the baseline (`file.read` / `file.write` /
`file.inspect_csv` / `workspace.list` stay INLINE_SAFE for small coding-agent
work). After schema validation and filesystem path confinement, the gateway
runs request-aware classification:

| Request | Class |
|---|---|
| ≤ ~1 MiB text read / write / hash / copy | INLINE_SAFE |
| ≤ ~2 MiB CSV sample inspect | INLINE_SAFE |
| non-recursive directory list ≤ 200 entries | INLINE_SAFE |
| over-threshold file / recursive list / full CSV parse-profile / parquet / filesystem.scan | EXTERNAL_REQUIRED |

Escalation never downgrades an already EXTERNAL_REQUIRED capability. Escalated
generic filesystem work is owned by the Worker Fabric `file_io` pool (not
`general`). Domain workers (`dataset`, `source_ingestion`, `knowledge_prepare`,
…) keep semantic ownership; `file_io` only owns generic capability filesystem
jobs. Large results spill to ArtifactStore; JobStore retains metadata/preview/refs.

Security ordering is mandatory: confine paths → cheap metadata → classify →
authorize → inline dispatch or durable enqueue. Approval context survives queue
serialization for WRITE side effects.

A model stating “I ran tool X” is not evidence. ExecutionGateway result/ObservationStore/receipt is the authority.

Gateway idempotency prevents replayed `idempotency_key` actions from dispatching side effects twice. Approval IDs are validated against policy; booleans such as `approved_by_user=true` are never authority.

## 11.2 FunctionRuntime

`Data/modules/function_runtime/` owns registry/runtime/built-ins/types. Physical cold functions are under `Data/functions/`, including text file read/write/patch/delete, workspace list/search, test execution, git status/diff, CSV/PDF and numeric compute functions.

## 11.3 Approvals

`Data/modules/approvals/authority.py`, `policy.py`, `service.py`, `store.py`, `types.py` own technical permission. Dependency-aware module installation binds approval to request argument digests/plan identity so approval cannot be reused for a different privileged operation.

---

# 12. JobRuntime and Worker Fabric

## 12.1 Durable jobs

`Data/modules/jobs/runtime.py`, `store.py`, `states.py`, `types.py`, `leases.py`, `retry.py`, `priority.py`, `budgets.py`, `resources.py` implement durable scheduling.

Important invariants:

- claim/lease ownership fences terminal writes;
- stale worker cannot overwrite a newer owner;
- expired RUNNING leases recover to retry, not fabricated completion;
- cancel flags propagate to cooperative executors;
- idempotency keys deduplicate durable work;
- heavy API workloads remain queued/fail honestly when required workers are unavailable.

## 12.2 Worker Fabric

`Data/modules/workers/` is the external execution plane. Domain entrypoints include agents, coding, research, memory, brain_compute, datasets/documents, embeddings/reranking, evaluation/training, market simulation, MCP, model downloads, provider I/O, source ingestion, **file_io** (generic heavy filesystem reads/writes/copies/hashes/CSV/Parquet/scans), scheduler/workflows, maintenance/backup, telemetry and DB commit.

Generic heavy filesystem jobs (`file.read` when oversized, `file.write` when oversized, `file.copy`, `file.hash`, `file.parse_csv`, `file.profile_csv`, `file.process_parquet`, `filesystem.scan`, recursive `workspace.list`) enqueue with `worker_pool=file_io`. API-local JobRuntime only claims `general`/unassigned jobs and cannot steal specialist file_io work. Small interactive file operations remain INLINE_SAFE in the control plane.

Crash forensics are durable and bounded: each process generation gets a unique log; unexpected exits publish structured metadata plus a human terminal summary; restart does not truncate predecessor evidence.

`GET /api/workers/dashboard` and `/api/workers/{id}` are operator read models; STARTING is not READY.

## 12.3 Source Ingestion authority

The former standalone source-ingestion design is consolidated into the Worker Fabric `source_ingestion` pool. Canonical entrypoint: `Data.modules.workers.entrypoints.source_ingestion`.

**Hard production boundary (Wave 1):** FastAPI / ResearchService are control-plane only for source ingestion. Heavy work — archive security validation, ZIP/TAR extraction, recursive archive inspection, document/Office/PDF parsing, and Brain retry orchestration — executes exclusively on the `source_ingestion` worker. OCR / Document AI executes exclusively on the `document_ai` worker. There is no production inline fallback when workers are absent (typed `SOURCE_INGESTION_UNAVAILABLE` / `OCR_UNAVAILABLE`).

Topology:

```text
FastAPI / Research API / operator UI
    |  auth, validate, stream upload, hash, metadata, enqueue
    v
JobRuntime (durable)
    v
source_ingestion worker  (source_ingestion.process / brain_retry)
    |-- detection, archive security, ZIP/TAR extract, recursion
    |-- document / Office / PDF / code / structured parse
    |-- when OCR genuinely required:
            durable child job (ocr.extract / document_ai.ocr)
                v
            document_ai worker  → typed receipt (OCR_UNAVAILABLE if no backend)
    v
canonical Knowledge / DB commit paths
```

Ingress rules:

| Source path | Canonical owner/behavior |
|---|---|
| Research file upload | Research `accept_upload` creates source and enqueues `source_ingestion.process` |
| Archive children | remain under parent ingestion job/lineage |
| Brain retry | enqueues `source_ingestion.brain_retry`; no synchronous heavy Knowledge write from API |
| PDF / document parse | `source_ingestion` worker only |
| OCR / Document AI | `document_ai` pool (`ocr.*` / `document_ai.*`); desired count may be 0 → UNAVAILABLE / OCR backend missing |
| Research URL fetch | Research web/fetch worker path; not mislabeled as source-ingestion queue work |
| Research coordinator local/seed/web source construction | Research source/evidence path; not a fake SI job |
| Production with SI unavailable | explicit `SOURCE_INGESTION_UNAVAILABLE`; no silent legacy parse fallback |
| Test-only inprocess | `runner=inprocess_test` + mechanical allow gate / pytest; never production default |

An idle READY source-ingestion worker with zero queue depth means **healthy idle/no work**, not failure. `document_ai` with desired=0 remains **UNAVAILABLE** (OCR backend missing) — do not start an empty worker to greenwash readiness.

Canonical implementation: `Data/modules/source_ingestion/`, worker entrypoint above, Research routes/services under `Data/modules/research/` and `Data/backend/routes/research.py`. OCR owner: `Data/modules/workers/entrypoints/document_ai.py`.

---

# 13. Agent system and Signal Fabric

## 13.1 Agent runtime/fleet

`Data/modules/agents/`:

- `runtime.py` — AgentRuntime;
- `fleet.py`, `fleet_types.py`, `store.py` — Agent Fleet;
- `governance.py` — delegation depth/cycle/authority/budget policy;
- `planner.py` — agent planning;
- `multi.py` — multi-agent DAG orchestration;
- `blackboard.py` — shared projections;
- `system_inventory.py` — truthful component inventory;
- `types.py` — contracts;
- `signals/` — Signal Fabric.

Delegated child authority is clamped to parent authority. Delegation depth and lineage are explicit; cycles are blocked; child budgets are derived from parent remaining budget.

## 13.2 Signal Fabric

Signal Fabric is a **coordination layer**, not a second AgentRuntime, JobRuntime, chat bus or database. It reuses canonical Agent Fleet, MemoryStore, JobRuntime/workers and ExecutionGateway.

Conceptual lifecycle:

```text
CREATED -> ROUTED -> PENDING -> CLAIMED -> DELIVERED -> ACKNOWLEDGED -> CONSUMED
                                \-> RETRY_WAIT -> ... -> DEAD_LETTER
```

Signal families include task/handoff, verify, block/unblock/cancel, knowledge candidate, memory candidate, heartbeat and progress. Routing supports direct, role, capability, orchestrator, mission and system routing with deterministic selection.

Sender identity never grants technical authority. Side effects still go through ExecutionGateway/Agent Fleet/Knowledge workers. Blackboard projections are convenience views, not canonical truth.

Worker pool: `agent_signals`; job families include `agent_signal.deliver`, retry and housekeeping. HTTP surface: `Data/backend/routes/agent_signals.py` under `/api/agents/signals...`.

---

# 14. Coding specialist

`Data/modules/coding/` is a specialist control plane, not a second general assistant. Important files include `service.py`, `loop.py`, `worker.py`, `planner.py`, `cognition.py`, `llm_adapter.py`, `parser.py`, `prompts.py`, `workspace.py`, `tools.py`, `patch.py`, stores/types and test/verification bridges.

Coding mutations remain subject to workspace boundaries, approvals and ExecutionGateway/function receipts. Test claims require real test receipts; model prose is not evidence that a patch or test ran.

HTTP: `Data/backend/routes/coding.py`. Heavy coding work is worker-capable via the canonical jobs/workers architecture.

---

# 15. General Research system

`Data/modules/research/` owns non-trading deep research. It is separate from Trading Research Lab but shares Brain, workers, models, capabilities and evidence principles.

Core ownership:

- `service.py` — project lifecycle/enqueue/configuration;
- `runner.py` — run/recovery wrapper;
- `coordinator.py` — research phase/wave orchestration;
- `worker.py`, `worker_context.py` — external worker execution;
- `planner.py`, `question_model.py` — research planning/question modeling;
- `web.py`, `web_capabilities.py`, `web_readiness.py` — web search/fetch/readiness;
- `sources.py` — source ingestion/snapshots;
- `evidence.py`, claims/conflicts/report/quality modules — evidence chain and synthesis;
- store/types/graph/export modules — durability/provenance.

High-level chain:

```text
ResearchPage/API
 -> ResearchService (validate / authorize / enqueue)
 -> JobRuntime research.plan | research.advance | research.fetch_url | research.report.generate | research.web.probe
 -> research worker
 -> ResearchRunner/Coordinator (retrieve/synthesize/verify phases stay coordinator-internal)
 -> specialist deps: source_ingestion / embedding / rerank when required
 -> sources/snapshots
 -> evidence/claims/conflicts
 -> report/citation audit/quality
 -> optional Brain/Knowledge assimilation
```

Production ownership (fail closed — no FastAPI inline heavy fallback when externalized):

| Workload | Owner |
|---|---|
| Plan generation / regeneration | `research.plan` → research worker |
| Manual bounded plan metadata edits | Control Plane CONTROL_WRITE |
| Research runs | `research.advance` → research worker → `execute_queued_run` |
| Live web probe (network) | `research.web.probe` → research worker |
| Web readiness (config) | Control Plane INLINE_SAFE |
| URL fetch | `research.fetch_url` → research worker |
| Report regenerate | `research.report.generate` → research worker |
| Physical source parse | `source_ingestion` (unchanged) |
| Embedding / rerank batches | `embedding` / `rerank` specialist pools |

Web permission and web search readiness are different. Outbound enabled does not mean a search provider is configured. Best-effort public search must remain labeled best-effort; fetch-only/search-unavailable states are explicit.

Search hit ≠ fetched source ≠ evidence span ≠ supported claim ≠ knowledge document.

HTTP: `Data/backend/routes/research.py`.

---

# 15A. Brain / Memory / Embedding / Rerank external execution

```text
CONTROL PLANE
  -> DURABLE JOB
  -> CORRECT DOMAIN WORKER
  -> SPECIALIST MODEL/IO WORKERS WHEN REQUIRED
  -> CANONICAL DOMAIN OUTPUT
  -> CANONICAL COMMIT PATH
```

- **Brain facade** — bounded query stays inline; heavy derived compute → `brain_compute`.
- **Memory** — bounded CRUD inline; heavy consolidation/enrichment → `memory`.
- **Embedding / Rerank** — specialist inference pools; worker READY ≠ backend/model READY; rerank default_count remains 0 until configured; unavailable rerank must not be labeled neural.
- **Knowledge reconcile** — `knowledge_prepare` diagnosis → typed repair → `db_commit` when COMMIT_WRITE.
- **db_commit** — sole bulk SQLite COMMIT_WRITE lane (`default 1 / max 1`).
- Product DBs remain CONTROL / KNOWLEDGE / MARKET only — never brain.db / memory.db / research_v2.db.

# 16. Datasets, documents and ingestion

`Data/modules/datasets/` owns dataset lifecycle, quality, indexing, semantic state, offline workflows and exports. `Data/modules/documents/` owns document extraction/intelligence. `Data/modules/source_ingestion/` owns source/file ingestion execution under Worker Fabric.

Important dataset concepts:

- canonical dataset identity + versions;
- processing/index state separate from “learned”/Brain state;
- semantic re-analysis explicitly requested;
- large transforms externalized;
- native/Python compute backend reported honestly;
- missing memory/throughput metrics remain UNMEASURED.

HTTP: `Data/backend/routes/datasets.py`. Knowledge ingestion: `Data/backend/routes/knowledge.py`. Source ingestion enters through domain APIs but heavy parse/index work is worker-owned.

---

# 17. Training, flywheel, evaluation, release and verification

## Training

`Data/modules/training/` owns durable recipes/jobs/training control/post-training data. `Data/backend/routes/training.py` exposes operations. A recipe definition is not proof a GPU training run completed.

## Flywheel

`Data/backend/routes/flywheel.py` and training/flywheel modules manage challengers, lineage and promotion evidence. Promotions require the configured verification/evaluation authority; model preference alone is insufficient.

## Evaluation

`Data/modules/evaluation/` owns benchmark/evaluation harnesses, ablations, scorecards/platform state. Missing model/provider measurements remain unavailable/unmeasured.

## Verification/quality

`Data/modules/verification/` owns verification reports and TEAM quality contracts. Important files include the verification engine/store plus `quality_contract.py`, `quality_store.py`.

## Release/master/product truth

- `Data/modules/release/` — release/CI relevance and gates;
- `Data/modules/master/` — master readiness aggregation;
- `Data/modules/product_truth/` — honest operator/product state helpers.

---

# 18. ModuleManager, Plugins, Skills and external capability fabric

## 18.1 ModuleManager

`Data/modules/module_manager/` is the dynamic module lifecycle authority. It handles discovery, installation, readiness, start/stop/restart, health, logs/jobs, capability registration, version lifecycle, idle sweep and external adapters.

The external fabric under `Data/modules/module_manager/external/` is generic. Supported declarative families include CLI, MCP, owned process/service, HTTP/OpenAPI, skill pack, catalog and composite. External sources are described in manifests under `Data/external_capabilities/`; per-repository bespoke wrapper classes are intentionally avoided.

External state is CONTROL-owned. PluginRegistry is rehydrated after external capabilities register so durable plugin bindings do not become a competing runtime.

## 18.2 Dependency-aware InstallationService

Installation is one flow, not ad-hoc shell calls from pages/adapters:

```text
plan install
 -> inspect declared dependencies/runtime/package manager
 -> persist operation
 -> approval for privileged system changes if required
 -> fetch/stage
 -> runtime/app dependencies
 -> post-install
 -> verify/re-probe
 -> promote version
 -> READY or typed failure
```

Primary install authority is `Data/modules/module_manager/external/install.py`; dependency/package-manager helpers and adapters live beside it under `Data/modules/module_manager/external/`. Lifecycle composition remains in `Data/modules/module_manager/manager.py`; routes are `Data/backend/routes/modules.py`.

Privileged system dependency approval is bound to request arguments/plan hash. Normal production execution uses JobRuntime/Worker Fabric; synchronous install fallback is default-off and must be explicitly enabled. Installation state/receipts are persisted in CONTROL domain migration v6.

## 18.3 Skills

`Data/backend/routes/skills.py` + external skill store/loader support bounded catalog search, on-demand instruction loading, enable/disable and execution through registered capability paths. Thousands of skill bodies are never dumped into model context just because they exist in the catalog.

## 18.4 External result handling

Large CLI/HTTP outputs spill to ArtifactStore; cognition/Chat receives bounded excerpts and artifact/source refs. Operational SSE may expose module/job/tool/artifact/source lifecycle, never hidden chain-of-thought.

External finance/trading packages are analytics/research capabilities only. If a manifest marks MarketSim bypass forbidden, mutation bypass is rejected; real-money execution remains blocked.

## 18.5 Plugins and MCP

- `Data/modules/plugins/` + `Data/backend/routes/plugins.py` — PluginRegistry lifecycle/invoke.
- `Data/modules/mcp/` + `Data/backend/routes/mcp.py` — MCP server/session/tool bridge.

MCP tools still enter the same capability/approval/observation architecture. MCP is not model routing and does not bypass ExecutionGateway authority.

---

# 19. Browser, media, voice and provider I/O

- `Data/modules/browser/` + `Data/backend/routes/browser.py`, `browser_qa.py` — browser capability/QA boundaries;
- `Data/modules/media/` + `Data/backend/routes/media.py` — media capability boundary; disconnected platforms stay NOT CONNECTED/UNAVAILABLE;
- `Data/modules/voice/` + `Data/backend/routes/voice.py` — realtime voice boundary;
- `Data/modules/provider_io/` — controlled remote HTTP/provider/market-data/chat I/O, credentials, readiness and streams;
- `Data/modules/model_download/` — model-download worker boundary;
- `Data/modules/isolation/` — sandbox/isolation guard;
- `Data/modules/security/` — audit, deployment, injection and secrets controls.

Network permission, provider configuration and provider health are three different states. SSRF/private-network policy must be evaluated from trusted settings, not payload-supplied booleans.

---

# 20. MarketSim and Trading Center backend — end to end

`Data/modules/market_sim/` is the **single trading simulation, strategy research, qualification and paper authority**. `Data/modules/trading/` remains an explicit boundary/stub; no parallel live trading engine exists.

**Real-money execution is BLOCKED.** Historical simulation, shadow and autonomous paper use simulated capital. A5/live-money autonomy is impossible by product contract.

HTTP owner: `Data/backend/routes/market_sim.py`; trading-agent/orchestra HTTP: `Data/backend/routes/trading_orchestra.py`; Research Command: `Data/backend/routes/research_command.py`.

## 20.1 Market data and causality

Important files:

- `data_store.py` — `MarketDataStore`, canonical indexed historical market-file registry; large market files stay on disk;
- `dataset_pipeline.py` — market-data import/quality/version preparation around `MarketDataStore`;
- `ohlcv.py` — OHLCV loading/validation/normalization;
- `causality.py` — `SimulationClock`, `MarketView`, as-of firewall;
- `features.py` — canonical FeatureEngine;
- `regimes.py` — deterministic trend/volatility/correlation/changepoint regimes; HMM stays feature-gated until real support exists;
- `market_state.py` — causal market-state snapshots;
- `costs.py` — cost model packs;
- `universe.py`, `exchange_calendars.py`, `instruments.py` — point-in-time universe, session calendars and instrument/session rules;
- `Data/modules/provider_io/adapters/market_stream.py` — external/current market-feed stream ordering, stable feed identity and gap recovery;
- `paper_deployment.py` — paper-forward feed-health representation used by deployments.

Historical perception may only use `timestamp <= as_of`. Unknown calendars/data/features fail closed or stay UNMEASURED; OHLCV is never promoted to fake L2/L3 order-book truth.

## 20.2 Strategies and simulation

Key files:

- `strategy_dsl.py` — bounded declarative DSL, no arbitrary eval/exec;
- `strategy_families.py` — canonical learner/generation family descriptors;
- `strategy_asset.py`, `strategy_lineage.py` — versioned assets/lineage/compatibility;
- `gym.py` — causal simulation episode engine;
- `execution.py`, `fill_model.py`, `accounting.py`, `risk_guard.py` — fills/wallet/risk/economic accounting;
- `experiments.py`, `strategy_eval.py` — trial/evaluation provenance;
- `behavior_fingerprint.py` — strategy behavior identity/dedup support.

The DSL supports the bounded implemented strategy kinds (including moving-average, mean-reversion, breakout, RSI, momentum, volatility, relative-strength, pairs-spread, feature-compare and composite families) plus operational HOLD. Unknown/arbitrary code fails closed.

## 20.3 Autonomous Trading Research Lab

Current main supports two lab creation modes:

- `SEED_EXISTING_STRATEGY` — existing strategy/version is the parent;
- `AUTONOMOUS_DISCOVERY` — no manually pre-created strategy is required; the lab creates a durable research lineage and generates its own candidates.

Core files:

| File | Role |
|---|---|
| `agent_lab.py` | lab contract/outcomes/acceptance/sealed lineage rules |
| `learning.py` | adaptive evolutionary learner and run creation |
| `learning_runtime.py` | durable generation execution/resume |
| `learning_candidates.py` | mutation/crossover/exploration/proposals |
| `learning_fitness.py` | fitness, failure classes, expectancy economics |
| `learning_types.py` | run/objective/candidate types |
| `research_hypothesis.py` | explicit falsifiable hypothesis contract |
| `research_perception.py` | causal numeric research perception |
| `chart_perception.py` | deterministic as-of chart snapshots + typed VLM observations |
| `research_cycle.py` | actual agent/evolution generation cycle + dedup |
| `research_roles.py` | canonical research-role reconciliation |
| `research_scope.py` | `ResearchDatasetBundle` / `EdgeScope`, multi-source/timeframe/asset refs |
| `candidate_explainability.py` | evidence-only “why was this candidate accepted/rejected?” projection |
| `lesson_trust.py` | lesson trust evolution from proposal to measured validation |
| `strategy_memory.py` / brain hooks | strategy lessons/negative evidence/retrieval |

MARKET domain v7 adds `market_research_hypotheses` and additive run-mode support.

A research hypothesis is public structured reasoning: mechanism, scope, falsification criteria, evidence/counterevidence, provenance and status. It is not hidden chain-of-thought. Falsification conditions may not be relaxed after outcome observation.

### Perception and chart vision

Numeric market truth remains primary. Research perception uses causal bars/features/regimes with source/version/as-of provenance. Chart perception is advisory:

```text
as-of bounded OHLCV
 -> deterministic chart snapshot
 -> artifact/reference
 -> model selected through Model Control Plane
 -> only if VisionCapabilityProfile.charts == SUPPORTED
 -> schema-validated ChartObservation
 -> optional numeric-vs-visual conflict evidence
```

No chart-capable model means honest UNAVAILABLE while numeric research continues. A VLM cannot place an order or override RiskGuard/qualification.

### Hybrid search

Research generations combine bounded evolutionary search (elite/mutation/crossover/exploration) with agent-proposed candidates. Agent model calls route through `market_sim/orchestra/model_adapter.py` → Model Control Plane; no private Ollama/OpenAI client lives in the research modules.

Duplicate/equivalent specs are canonicalized/deduplicated before expensive trials where supported. Losing trials remain evidence and update future priors/failure statistics.

## 20.4 Trading agents and orchestra

`Data/modules/market_sim/orchestra/` contains service, store, types, model adapter and executors. Roles include market/regime analysis, signal/news analysis, strategy research/authoring, critic, deterministic risk officer, execution agent, evaluator, postmortem and orchestrator. Role registration integrates with the existing Agent Fleet instead of creating a second fleet.

Important invariant from `orchestra/executors.py`: models propose/critique/explain; **RiskGuard is deterministic authority**; execution agent records/routes paper intent only.

`Data/modules/market_sim/roles.py`, `research_roles.py` and `institutional_team.py` reconcile role vocabularies/required risk veto.

## 20.5 Scientific split integrity

Research is not considered qualified from a green TRAIN curve.

Canonical integrity components include:

- dataset certification/version/hash;
- immutable split manifests and research episode binding;
- TRAIN/VAL/ROBUSTNESS/SEALED roles;
- embargo/point-in-time constraints;
- walk-forward folds;
- multiple-testing/PBO/CSCV diagnostics where configured;
- regime matrix;
- cost/slippage/spread/parameter/time perturbations;
- sample adequacy;
- capacity/execution compatibility;
- sealed single-use/lineage contamination firewall.

Relevant files include `split_manifest.py` (`DatasetSplitManifest` / `ResearchEpisodeBinding`), `epistemic.py` (adaptive-vs-sealed evidence classes), `walk_forward.py`, `robustness.py`, `regimes.py`, `sample_adequacy.py`, `capacity_qualification.py`, `qualification.py`, `commit_reveal.py` and related tests.

SEALED evidence is not adaptive training material for the same contaminated lineage. Renaming a strategy does not reset the root lineage.

## 20.6 Profitability/fitness truth

The learner does **not** treat win rate as profitability. `learning_fitness.py` derives expectancy economics so a 70% win rate with destructive losses can rank below a lower-win-rate strategy with positive post-cost expectancy. Evaluation considers net return/expectancy, payoff, drawdown, risk-adjusted/stability signals, costs, turnover, sample adequacy, regime/parameter/cost sensitivity and complexity where measurable.

Missing economic inputs remain UNMEASURED; they are not silently treated as zero.

## 20.7 QualificationAuthority

`Data/modules/market_sim/qualification.py` is the canonical scientific promotion authority with fixed gate order:

1. Q01 Data Certification
2. Q02 Reproducibility
3. Q03 Baseline Acceptance
4. Q04 Walk Forward
5. Q05 Statistical Multiplicity
6. Q06 Regime Matrix
7. Q07 Adversarial Robustness
8. Q08 Execution Validity
9. Q09 Capacity
10. Q10 Sealed Holdout
11. Q11 Portfolio Compatibility

Agent/VLM confidence is never a competing gate. Caller `passed=true` booleans are not qualification evidence.

## 20.8 Paper, shadow and autonomy

Key files:

- `portefeuille/service.py` — canonical paper portfolio lifecycle/accounting/order service used by Research Command/Orchestra paper routing;
- `paper_broker.py` — paper-broker abstraction and local paper sessions;
- `paper_forward.py` — paper-forward runner;
- `paper_deployment.py` — durable deployment/feed health;
- `autonomous_paper_loop.py` — A0–A4 loop state/promotion receipts;
- `paper_forward_drift.py` — forward evidence policy/drift/tickets;
- `trading_live_guard.py` — real-money boundary.

Progression is qualification-governed. Shadow is observe-only; autonomous paper uses simulated capital and RiskGuard. Kill-switch state is durable. Paper sessions restore wallet/orders on restart and client-order/event replay is idempotent.

Forward evidence requires meaningful history; a few lucky observations do not become PASS. Drift can create a continual-research ticket but does not automatically promote a replacement or enable live execution.

## 20.9 Closed continual-research loop

Current main closes:

```text
historical data
 -> autonomous/seed Research Lab
 -> hypotheses/perception
 -> hybrid candidate generation
 -> TRAIN/VAL/robustness/SEALED
 -> QualificationAuthority
 -> shadow/autonomous paper
 -> forward evidence/drift
 -> ContinualResearchTicket
 -> linked new Research Lab run
```

Old evidence remains immutable. PAPER-observed StrategyMemory has its own epistemic state; companion lessons start AGENT_PROPOSED and become VALIDATED only through measured evidence policy.

## 20.10 Research Command and Control Room

**Research Command**: `Data/modules/market_sim/research_command/service.py`, store support, `Data/backend/routes/research_command.py`. It composes existing TradingOrchestra, paper portfolio, news and Research Lab. It can start/pause a bound paper/research session, manage watch state, flatten paper positions, arm paper kill switch and invoke the existing lab lifecycle. It **does not own a second learning engine**.

**Institutional Control Room**: MarketSim institutional runtime/service projections exposed through `Data/backend/routes/market_sim.py`. It surfaces qualification/reconciliation/exceptions/audit/data-plane/fabric truth without inventing green states.

## 20.11 Chat read capabilities for trading research

`Data/modules/market_sim/chat_capabilities.py` binds current MarketSim state into registered read capabilities for lab status, lessons/drift/explanation. Chat reads through canonical capability/Brain paths; it does not query MARKET SQLite directly and cannot unlock live trading.

---

# 21. Workflows, schedules and tasks

- `Data/modules/workflows/` — workflow store/runtime/multi-step execution;
- `Data/modules/schedules/` — schedule persistence/runner;
- `Data/modules/tasks/` — durable operator task service;
- `Data/modules/run/` — parent run/event envelope utilities.

They reuse JobRuntime/ExecutionGateway rather than maintaining independent execution queues or side-effect channels.

---

# 22. Security, isolation, secrets and authority

Relevant code:

- `Data/modules/common/http_auth.py` — central HTTP mutation policy;
- `Data/modules/security/` — auditor/deployment/injection/secrets controls;
- `Data/modules/isolation/` — sandbox/isolation guard;
- `Data/modules/approvals/` — approval authority;
- `Data/modules/context/reference.py` — untrusted model-facing reference boundary;
- `Data/modules/execution/gateway.py` — side-effect authorization/idempotency;
- `Data/modules/provider_io/` + Research SSRF helpers — remote/private-host controls.

Rules:

- external/web/news/tool/module text is untrusted data;
- payload fields never grant private-network or execution authority;
- secrets are leased/brokered, not copied into public telemetry/prompts;
- side effects use code-enforced authority, not prompt instructions;
- hidden chain-of-thought is not logged or exposed;
- non-loopback API mutations require operator auth;
- trading real-money mutations remain blocked independently of generic approval.

---

# 23. Observability, analytics, health, backup and chaos

- `Data/modules/observability/` — event hub, operator registry, telemetry/event stream;
- `Data/modules/observations/` — durable observations;
- `Data/modules/metrics/` — metric/time-series collection;
- `Data/modules/analytics/` — analytics service;
- `Data/modules/host_console/` + `Data/backend/routes/host_console.py` — read-only host projections;
- `Data/modules/backup/` — database backup/restore with maintenance/recovery fencing;
- `Data/modules/chaos/` — controlled fault injection;
- `Data/modules/product_truth/` — truthful product/readiness projections.

`GET /api/host/liveness` is intentionally cheap. `/api/health` is the richer application diagnostic and must not be substituted into tight launcher polling loops.

Restore is maintenance-coordinated and startup checks recovery journals; mixed/unfinished restore state fails closed rather than booting across inconsistent databases.

---

# 24. Native compute and resource boundaries

`Data/native/` contains the native data-plane implementation where available; `Data/modules/native/` is the Python-facing boundary. `Data/modules/compute/` owns bounded numeric/compute helpers.

Native acceleration is a capability, not a truth claim. If the binary/toolchain/operation is missing, backend and UI report unavailable/unmeasured/fallback. Heavy Python remains worker-externalized rather than being rewritten into ad-hoc native code merely for labeling.

System telemetry measures CPU/RAM, optional GPU, disk capacity and network rates; first/reset network sample stays null rather than fabricated zero.

---

# 25. Native launcher / backend host

`Data/launcher/` is a Tauri/native host around `leviathan.py`. It owns process lifecycle, not API business logic.

Host lifecycle states include STOPPED, PREFLIGHT, STARTING, RUNNING, DEGRADED, STOPPING, FAILED and ATTACHED_EXTERNAL. System readiness is separate (STARTING/READY/DEGRADED/SAFE_MODE/NOT_CONFIGURED/UNMEASURED).

Key backend contracts:

- `GET /api/host/liveness` — cheap boot proof;
- `/api/host/overview`, `/api/host/source-ingestion`, `/api/host/native-operations` — read projections;
- `/api/workers/dashboard` — Worker Fabric state;
- `/api/performance/snapshot` — resource/DB contention;
- `/api/models/status` — model plane;
- `/api/events/stream` — live operational stream.

Safe Mode intentionally disables workers and is not equivalent to a random worker crash.

---

# 26. Verification, gate manifests and machine truth

Architecture prose is not release evidence. Machine manifests/reports live outside `Data/docs`:

| Program | Manifest / verifier |
|---|---|
| Frontier reasoning | `Data/backend/tests/frontier_reasoning_gates.json`, `scripts/verify_frontier_reasoning.py` |
| Trading | `Data/backend/tests/trading_gates.json`, `scripts/verify_trading_100.py` |
| Aggregate | `scripts/verify_leviathan.py` |
| Capability drift | `Data/backend/tests/test_capability_contract_drift.py` |
| Backend tests | `Data/backend/tests/` |
| Production-quality ledger | `Data/backend/tests/production_quality_program.json` |

The frontier manifest currently remains a conservative F0/R01–R30 machine ledger and may mark gates NOT_STARTED even while individual production features with similar historical wave names exist. **Do not infer product capability from a wave label.** Inspect the actual subsystem tests and gate entry.

Trading verifier supports strict provenance/evidence semantics. Documentary/file-exists checks alone cannot produce strict PASS; FEATURE_GATED/UNMEASURED/NOT_TESTED do not become PASS because CI is otherwise green.

Common commands:

```bash
python -m pytest Data/backend/tests -q
python scripts/verify_leviathan.py --allow-incomplete --write-report
python scripts/verify_frontier_reasoning.py --allow-f0-skeleton-only
python scripts/verify_trading_100.py --allow-incomplete
python scripts/verify_trading_100.py --strict --run-tests
```

Generated reports must be regenerated by their verifier, not hand-edited green.

---

# 27. Complete `Data/modules/` locator

This table is the fastest entry point for Cursor when locating ownership.

| Directory | Canonical responsibility |
|---|---|
| `agents/` | AgentRuntime/Fleet, governance, multi-agent, Signal Fabric |
| `analytics/` | analytics service |
| `approvals/` | authority/policy/approval persistence |
| `artifacts/` | artifact storage/hash/validation |
| `backup/` | backup/restore/maintenance recovery |
| `brain/` | unified Brain access facade |
| `browser/` | browser capability/QA boundary |
| `chaos/` | controlled fault injection |
| `coding/` | CodingControlPlane |
| `cognition/` | CognitiveRuntime/TEAM/planning/TTC/critics |
| `common/` | shared hashing/path/ownership/HTTP auth/SQLite utilities |
| `compute/` | bounded numeric/compute helpers |
| `context/` | context/trust/budget/compaction/multimodal |
| `datasets/` | dataset lifecycle/quality/index/offline/export |
| `db_commit/` | canonical bulk SQLite commit coordinator |
| `documents/` | document extraction/intelligence |
| `evaluation/` | evaluation platform/harness/ablations |
| `evidence/` | Evidence service/store |
| `execution/` | capability catalog + ExecutionGateway + receipts |
| `function_runtime/` | cold function registry/runtime |
| `host_console/` | host/operator read models |
| `intelligence/` | cross-cutting intelligence policy/health |
| `isolation/` | sandbox/isolation guard |
| `jobs/` | durable jobs/leases/retries/resources |
| `knowledge/` | RAG/Brain documents/Atlas/DeepRecall/Why |
| `market_sim/` | causal market sim, autonomous strategy research, qualification, paper |
| `master/` | master readiness aggregation |
| `mcp/` | Model Context Protocol bridge/session/tool provider |
| `media/` | media capability boundary |
| `memory/` | durable scoped MemoryStore |
| `metrics/` | metrics/time series |
| `model_download/` | model acquisition worker boundary |
| `model_runtime/` | provider inference/serving/streaming |
| `models/` | Model Control Plane |
| `module_manager/` | ModuleManager + generic external capability fabric/install authority |
| `native/` | Python-facing native runtime boundary |
| `neuro/` | Neuro/Cortex/residual advisory system |
| `observability/` | event/system/operator telemetry |
| `observations/` | durable observations/receipts |
| `plugins/` | PluginRegistry |
| `product_truth/` | truthful readiness/posture projections |
| `provider_io/` | controlled remote/provider I/O |
| `reasoning/` | legacy intent/retrieval classification seam |
| `release/` | release/CI gates |
| `research/` | general research runtime/evidence/source graph |
| `run/` | common run lifecycle/envelopes |
| `schedules/` | schedule persistence/runner |
| `security/` | audit/injection/secrets/deployment controls |
| `settings/` | Settings Control Plane + BehaviorProfile |
| `source_ingestion/` | source/file ingestion pipeline executed by Worker Fabric |
| `sqlite_manager/` | operator control plane for the three SQLite DBs |
| `tasks/` | durable task service |
| `trading/` | explicit live-trading boundary/stub |
| `training/` | training/post-training/flywheel support |
| `verification/` | verification/quality contracts/reports |
| `voice/` | realtime voice boundary |
| `workers/` | Worker Fabric/supervisor/pools/entrypoints |
| `workflows/` | workflow runtime/store |

Other backend-relevant code:

- `Data/functions/` — physical FunctionRuntime implementations;
- `Data/external_capabilities/` — external source manifests only, not bespoke runtime owners;
- `Data/native/` — Rust/native data-plane source/build output boundary;
- `scripts/` — verifiers/worker helper scripts;
- `Data/backend/tests/` — executable architecture and product-truth evidence.

---

# 28. Cursor change guide — where to start

| You need to change... | Start at... | Also inspect... |
|---|---|---|
| app dependency wiring | `Data/backend/main.py` | target route/service constructor |
| environment/default setting | `Data/backend/config.py` | `settings/catalog.py`, `bindings.py`, `.env.example` |
| persisted setting/UI catalog | `Data/modules/settings/` | frontend Settings page |
| DB ownership/schema | `Data/backend/table_ownership.py`, `Data/backend/db_upgrade.py` | owning store + migration tests |
| bulk DB write | `Data/modules/db_commit/` | owning domain store |
| Chat behavior | `Data/backend/main.py` chat endpoint | `Data/modules/cognition/`, Brain, context |
| cognition planning/reasoning | `Data/modules/cognition/` | `verification/`, `context/` |
| model routing | `Data/modules/models/control_plane.py` | router/residency/model_runtime |
| provider transport | `Data/modules/model_runtime/` | capability probe/contracts |
| retrieval/RAG | `Data/modules/knowledge/` | `brain/`, `context/` |
| durable memory | `Data/modules/memory/` | Brain/perception |
| tool/side effect | `Data/modules/execution/` | approval, observation, function/module/MCP owner |
| durable heavy job | `Data/modules/jobs/` | `Data/modules/workers/entrypoints/` |
| worker lifecycle | `Data/modules/workers/` | `Data/backend/routes/workers.py`, launcher boot |
| agent/fleet | `Data/modules/agents/` | cognition delegation |
| coding agent | `Data/modules/coding/` | execution functions/verification |
| research/web | `Data/modules/research/` | `Data/backend/routes/research.py`, workers |
| dataset ingestion | `Data/modules/datasets/`, `Data/modules/source_ingestion/` | db_commit/knowledge workers |
| training/evaluation | `Data/modules/training/`, `Data/modules/evaluation/` | release/verification/flywheel |
| module installation/lifecycle | `Data/modules/module_manager/` | `Data/backend/routes/modules.py`, approvals, JobRuntime |
| skill integration | `Data/backend/routes/skills.py` | module_manager external skill store |
| MCP | `Data/modules/mcp/` | ExecutionGateway |
| market simulation | `Data/modules/market_sim/gym.py` | causality/features/execution/accounting |
| strategy generation | `Data/modules/market_sim/strategy_families.py`, `Data/modules/market_sim/learning_candidates.py` | DSL/learning/research_cycle |
| autonomous trading research | `Data/modules/market_sim/research_cycle.py` | hypothesis/perception/learning/qualification |
| qualification | `Data/modules/market_sim/qualification.py` | WFA/regimes/robustness/capacity/sealed |
| paper autonomy/drift | `Data/modules/market_sim/autonomous_paper_loop.py`, `Data/modules/market_sim/paper_forward_drift.py` | service/store/live guard |
| Research Command | `Data/modules/market_sim/research_command/` | route + orchestra + paper + lab |
| security/auth | `Data/modules/common/http_auth.py`, `Data/modules/security/`, `Data/modules/approvals/` | main middleware/ExecutionGateway |
| observability | `Data/modules/observability/`, `Data/modules/metrics/` | event producers + frontend event client |

---

# 29. Architectural invariants to preserve

```text
one FastAPI control plane
one CognitiveRuntime
one Model Control Plane
one canonical ContextBuilder
one Brain facade over canonical stores
one ExecutionGateway for capability side effects
one JobRuntime / Worker Fabric for durable heavy work
one Agent Fleet
one ModuleManager external fabric
one MarketSim trading/research authority
exactly three product SQLite databases: CONTROL / KNOWLEDGE / MARKET
ArtifactStore for large/file payloads
model output != observation
retrieved text != instruction authority
request/approval flag != technical authority
UNMEASURED != PASS
TRAIN profit != qualification
chart/VLM opinion != trading authority
real-money trading remains BLOCKED
no private chain-of-thought persistence/exposure
```

---

# 30. Documentation maintenance rule

For every backend PR that changes a canonical owner, route, database/table ownership, model/cognition contract, worker flow, external module lifecycle, trading/research flow or major file location:

1. update this document in the same PR;
2. update `Leviathan_system_frontend.md` when the operator/API contract changes;
3. update executable manifests/tests rather than creating a new system-level architecture Markdown file;
4. state CURRENT vs FEATURE-GATED/UNMEASURED honestly;
5. include exact file paths so Cursor can start at the right owner;
6. never use documentation prose to upgrade a runtime state to PASS.
