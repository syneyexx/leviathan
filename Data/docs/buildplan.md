# LEVIATHAN Build Plan

This document records what has been completed so far, the current system boundary, and the intended direction for future build phases.

LEVIATHAN is a **Python-first rebuild from the ground up**. HADES is used as a functional/architectural reference, not as a codebase to copy wholesale.

---

---

## 2026-09-22 — Market simulation (causal multi-agent, EXTERNAL-FIRST) — PASS

### Objective
Replace mock Trading Center numbers with a rigorous paper market simulator: real OHLCV files, strict no-look-ahead clock, versioned strategies, multi-agent deliberation with brain hooks, honest metrics.

### Added
- `Data/modules/market_sim/` — control plane, MarketDataStore, SimulationEngine, StrategyStore, DeliberationRuntime, BrainFacade, MarketSimWorker
- Migration **v16** — market_data_sources, market_strategies/versions, market_sim_runs/fills/messages/equity/events
- API: `Data/backend/routes/market_sim.py` under `/api/market-sim/*`
- Flag: `LEVIATHAN_FEATURE_MARKET_SIM` (default false); `LEVIATHAN_MARKETS_ROOT`
- Frontend: live binding intended for `/trading/simulatie`, `/trading/strategieen`, `/trading/marktdata` (see merge note vs pixel-exact TradingCenter pages)
- Docs: `Data/docs/market_sim.md`
- Tests: `Data/backend/tests/test_market_sim.py` + fixture BTC OHLCV
- App version `0.56.0-market-sim` (after Phase 52 `0.55.0`)

### Architecture fit
- EXTERNAL-FIRST: worker executes bars; Core owns lifecycle/state
- One central SQLite; market files on filesystem with hashes
- Brain advisory only; paper fills only; trading stub still refuses real orders
- Causality violations measured and must be 0 on tests

### Explicitly NOT claimed
- Real broker / live money
- Perfect L2 microstructure without L2 data
- Guaranteed alpha / in-loop foundation training

---

## 2026-09-22 — Phase 52 — Neuro Layer Grok-level depth jump — PASS

### Objective
Elevate the Neuro Layer from Phase 51 operational completion to frontier-feeling local reasoning quality while preserving every honesty invariant (neural signal ≠ authority, residual optional/degradable, registered ≠ trained, unmeasured ≠ passed).

### Added / changed
- **Residual:** weight-backed `HFTransformersResidualAdapter` behind `LEVIATHAN_NEURO_RESIDUAL_LOAD_WEIGHTS`; ADDITIVE/GATED/DISABLED modes; provenance receipts (`implemented`/`applied`/`degraded_to_chat_completions`/`reason`); richer vLLM/llama.cpp stubs; telemetry on read/inject/forward
- **Cortex:** smarter `CortexPlanner` (budget, residual, memory coverage/quality, WM load); `CortexRuntime` mid-forward critic re-steer + residual replay; depth metadata signals (advisory only)
- **Critic:** grounding collapses without Evidence/Knowledge ID citations
- **Memory:** Tier0 priority eviction; high-trust Verification/human writes; budgeted retrieve; lock-safe snapshot/restore; contrastive head uses EmbeddingProvider when available
- **Training:** `TrainingRecipeRegistry.execute` status machine with fixture trainer; refuse fabricated COMPLETED; human preference bridge
- **Observability/status:** neuro category events; status residual posture + WM load
- Version `0.55.0-phase52`; Master `phase_span=0-52`
- Tests: `test_neuro_phase52.py` (+ existing Phase 46–51 suites)

### Verification
- Full backend `pytest Data/backend/tests` → **229 passed**

### Explicitly NOT claimed
- Default production path is weight-backed GPU residual (still opt-in / env-dependent)
- Multi-hour HBM/power SLO
- Automatic preference fabrication
- “Thought harder” as authority

### Status
**PASS**

---

## 2026-09-21 — Coding Agent control plane + /coding operator UI — PASS

### Objective
Turn `/coding` from a toast/chat-redirect stub into a production Coding Agent control plane (same honesty bar as Models / Datasets / Research), with a pixel layout matching the Coding Agent mockup.

### Added
- `Data/modules/coding/` — CodingControlPlane, CodingLoop (XML tool protocol), store, workspace confinement (HADES deny), patch applicator (fail-closed), parser, prompts (few-shots), tools ENFORCE-*, background worker
- Migration **v15** — `coding_sessions`, `coding_turns`, `coding_steps`, `coding_patches`
- Capabilities: `workspace.list`, `workspace.search`, `file.write`, `file.patch`, `file.delete`, `coding.run_tests`, `git.status`, `git.diff`; `file.read` gains line numbers / start_line / end_line
- Functions under `Data/functions/{text_file_write,text_file_patch,text_file_delete,workspace_list,workspace_search,coding_run_tests,git_status,git_diff}`
- API: `Data/backend/routes/coding.py` mounted from `main.py`; lifespan starts coding worker
- Flags: `LEVIATHAN_FEATURE_CODING` (default false; requires `LEVIATHAN_FEATURE_AGENTS`); workspace default `D:/leviathan/codingworkspace`
- Frontend: `/coding` Coding Agent page — hero + 8 panels (Task Intake, Agent Status, Workspace, Timeline, Terminal, Diff, Review, Memory); typed client; submenu **Coding Agent**
- Tests: `Data/backend/tests/test_coding_agent.py` (32)

### Architecture fit
- Side effects only via ExecutionGateway + Approvals; `requested_by=agent:coding`
- Loop runs in background worker (HTTP turn returns RUNNING immediately)
- ContextBuilder `mode=coding` replaces generic system_core
- AgentRuntime still plans VERIFY heuristics when coding flag off; delegates when on
- No private shell / FS / second DB; HADES paths rejected

### Verification
- Backend coding + migrations + agents/gateway smoke → **PASS**
- Frontend typecheck / test / build → **PASS**
- Live LM Studio E2E coding loop: **NOT TESTED** in this environment (fake LLM queue in unit tests)

### Explicitly NOT claimed
- Native OpenAI `tools[]` (XML-in-content is the real path; client has no tool_calls)
- Multi-agent coding swarm / SSE token streaming
- Automatic git commit / push without explicit operator request + approval
- Browser / media / HADES integration

### Status
**PASS** (control plane + UI; live model E2E NOT TESTED here)

---

## 2026-09-21 — Models + Datasets + Training + Research production subsystem — PASS

### Objective
Deliver end-to-end Models control (already present), plus real Datasets, Training, and Research subsystems with durable jobs, honest capability reporting, and wired frontend pages — no mock progress/sources/metrics.

### Added
- Migration **v14** — datasets/versions/files/jobs/indexes; training jobs/metrics/checkpoints/artifacts; research projects/events/sources/evidence/claims/conflicts/reports
- `Data/modules/common/` — atomic IO, path safety, retry/backoff, secrets, corpus layout, process liveness
- `Data/modules/datasets/` — import (local/upload/HF resumable), materialize, detect/canonicalize, validate, dedupe, transforms, splits, tokenize stats, export, knowledge indexing, job runner
- `Data/modules/training/` — durable TrainingService, capabilities/hardware/preflight/planner, fixture + real LoRA worker subprocess, cancel/resume/reconcile, evaluation, artifact→model registry sync
- `Data/modules/research/` — projects/plans, local retrieval, optional web provider, SSRF guard, evidence/claims/conflicts/coverage/reports/export
- API routers mounted from `main.py`; startup reconcile + dataset background worker
- Frontend: Datasets / Training / Research pages rewritten against real APIs; Models Test console
- Docs: `Data/docs/models_datasets_training_research.md`

### Verification
- Backend: full `pytest Data/backend/tests` → **179+ passed** (subsystem suites included)
- Frontend: typecheck / lint / test / build → **PASS** (per frontend wiring commit)
- Real CUDA LoRA / live LM Studio / live HF / live web search: **ENVIRONMENT-DEPENDENT / NOT EXECUTED** in this agent VM

### Explicitly NOT claimed
- Token-streaming SSE on model test endpoint (non-stream real inference works; stream flag documented as not yet transported)
- Automatic “trained model is better” labeling
- Fabricated web results when provider unconfigured

### Status
**PASS** (implemented + automatically verified where environment permits)

---

## 2026-09-21 — Models Control Plane (full backend + Models page) — PASS

### Objective
Replace the mock Models page with a production Model Control Plane: registry, profiles, providers, gateway, router, lifecycle gating, import/download, capability probing, and a complete operator UI — without parallel databases or fake telemetry.

### Added
- `Data/modules/models/` — contracts, store, registry, profiles, gateway, router, runtime manager, resource preflight, capability probe, benchmarks, downloads, import, provider adapters (LM Studio, Ollama, OpenAI-compatible, llama.cpp boundary), `ModelControlPlane` facade
- Migration **v13** — `model_providers`, `model_registry`, `model_profiles`, `model_control_state`, `model_capability_results`, `model_downloads`, `model_audit_log` (central DB)
- API routes via `Data/backend/routes/models.py` (composition in `main.py`)
- Chat uses router + gateway + active profile (explicit model / role / fallback; legacy settings fallback when registry empty)
- Frontend Models page rebuilt as real control surfaces under `Data/frontend/src/pages/models/`
- Tests: `test_models_control_plane.py` + catalog unit tests; migration expectation → v13

### Architecture fit
- Single SQLite persistence; secrets never returned to browser
- Provider capabilities gate load/unload/delete (LM Studio: discover/inference/health; load/unload unsupported honestly)
- llama.cpp adapter is an explicit unmanaged boundary (not a fake runtime)
- Observability events under category `models`

### Verification
- Backend: `PYTHONPATH=/workspace python3 -m pytest Data/backend/tests` → **PASS (149)**
- Frontend: `npm run typecheck`, `npm run test`, `npm run build` → **PASS**
- Live LM Studio / Ollama / HF download against real runtimes: **NOT TESTED** in this environment (no local runtimes); adapters and offline/timeout paths covered by unit tests

### Explicitly NOT claimed
- Programmatic LM Studio load/unload (provider does not expose it on the OpenAI surface used here)
- Managed llama.cpp inference engine
- Chat SSE token streaming (preference persisted; HTTP chat remains non-SSE)
- Automatic “best model” ranking from benchmarks

### Status
**PASS** (control plane implemented; external runtime E2E NOT TESTED here)

---

## 2026-09-21 — Phase 51 — Neuro Layer operational completion — PASS

### Objective
Close remaining Neuro Layer gaps: chat/context integration, scheduled absorb, preference bridge, soak harness, frontend operator surfaces, vLLM/llama stubs.

### Added / changed
- ContextBuilder `neuro` section (advisory-only labeling)
- Chat path wires neuro signals + memory tiers + optional CortexRuntime into LLM context
- `POST /api/neuro/absorb/schedule` (Job → `knowledge.ingest_scan` with approval_id)
- `POST /api/neuro/soak` mini soak harness (explicitly not production SLO)
- `POST /api/training/preferences/from-verification` via PreferenceBridge
- Residual stubs: `VllmResidualAdapter`, `LlamaCppResidualAdapter` (honest unsupported)
- Frontend: neuro API client methods + Status page Neuro panel + mini soak
- Master phase_span `0-51`; version `0.51.0-phase51`

### Tests
- Full backend suite → **PASS (135)**
- Frontend typecheck/test after `npm install`

### Still not claimed
- HF/vLLM/llama weight-backed residual inject
- Multi-hour power/HBM SLO measurement
- Automatic preference label fabrication

### Status
**PASS**

---

## 2026-09-21 — Phases 47–50 — Neuro Layer production path — PASS

### Phase 47 — Residual adapter #1 + critic-on-residual + ablations
- `DeterministicResidualRuntime` (toy, `production_grade=false`) + `HFTransformersResidualAdapter` (config-only readiness)
- `build_residual_runtime(kind=unsupported|deterministic|hf)`
- `ProcessCritic.score_residual` + `CortexRuntime` mid-forward critic loops
- EvaluationHarness `neuro_ablation_suite` — unsupported residual ⇒ **UNMEASURED** not PASSED
- Config: `LEVIATHAN_NEURO_RESIDUAL_KIND|MODEL|DEVICE`

### Phase 48 — Memory tier hardening + ModelData absorb
- Migration **v12** `neuro_memory_snapshots` (central DB)
- `NeuroSnapshotStore` + facade `snapshot`/`restore` for Tier 0/1
- `NeuroAbsorbService` → Knowledge V2 `scan_data_root` (no parallel ingest)
- Capability `knowledge.ingest_scan` (WRITE → approvals required)
- `ContrastiveRetrievalHead` lexical proxy; vector path honest UNMEASURED
- APIs: `/api/neuro/absorb`, `/api/neuro/memory/snapshot*`, `/api/neuro/contrastive`

### Phase 49 — Cortex + training recipes
- `CortexRuntime` against ResidualStreamPort
- `TrainingRecipeRegistry` with process supervision / DPO / InfoNCE / synthetic / joint recipes
- API: `GET /api/training/recipes`, `POST /api/neuro/cortex/run`
- registered ≠ trained preserved

### Phase 50 — Production harden
- Module Manager `SUBPROCESS` isolation via `SubprocessModuleExecutor` + flag `MODULE_MANAGER_SUBPROCESS`
- Release gates: neuro residual posture WARN; subprocess INFO; catalog includes ingest_scan
- Master gate: neuro residual DEGRADED when flag ON without support
- App version `0.50.0-phase50`

### Tests / verification
- Full backend suite → **PASS (131)**
- New: `test_neuro_phases_47_50.py`

### Explicitly NOT claimed
- HF weight-backed residual inject/forward (config-only)
- Production-grade GPU residuals / frontier model hooks
- Real contrastive embedding training metrics
- Continuous soak under load as measured SLO (counters exist; long-soak NOT TESTED in CI)

### Status
**PASS** (47–50) — Neuro Layer phased MVP→harden complete for local contracts

---

## 2026-09-21 — Phase 46 — Frontier Neuro Layer MVP + Universal Module Manager — PASS

### Objective

Specify the Top-Tier Frontier Neuro Layer and land MVP scaffolding on the Phase 45 foundation without parallel databases, gateways, or model clients.

### Added

- Architecture specification: `Data/docs/neuro_layer_architecture.md` (interfaces, Mermaid flows, training recipes, hardware guide, risks, phased plan)
- `Data/modules/module_manager/` — `ILeviathanModule`, discovery from `Data/modules/*/module.json` + `{DATA_ROOT}/plugins/`, lifecycle discover→load→initialize→execute→shutdown, hot-reload, crash containment
- Neuro contracts: `residual.py` (`ResidualStreamPort`, `UnsupportedResidualRuntime`), `cortex.py` (`CortexPlanner`), `critic.py` (`ProcessCritic`), `memory_tiers.py` (`NeuroMemoryFacade` Tier 0–2)
- First-party example module: `Data/modules/neuro/module.json` + `echo_module.py`
- Feature flags: `NEURO_CORTEX`, `NEURO_MEMORY_TIERS`, `MODULE_MANAGER`
- APIs: `GET /api/neuro/residual`, `GET /api/modules`, `POST /api/modules/discover`, `POST /api/modules/{id}/execute`
- Memory kinds: `EPISODIC`, `DECISION` (central MemoryStore; no new DB)
- App version `0.47.0-phase46`

### Changed

- `NeuroAdvisor` composes cortex / critic / memory facade / residual port; residual remains honestly unimplemented without a residual-capable runtime
- Chat `/api/neuro/assess` passes ReasoningPlan into neuro assessment
- Config validation: cortex/memory-tier child flags require parent `NEURO`
- Health exposes neuro residual support + module manager snapshot

### Architecture fit

- Module Manager is the single loader; PluginRegistry remains catalog binding (discoverable ≠ authorized)
- Memory tiers orchestrate existing MemoryStore + Knowledge V2 — no fork
- Side effects still exclusively via Execution Gateway + Approvals + Evidence + Verification
- Residual injection explicit, optional, degradable

### Database / schema

- No new migration — Tier 1 reuses `memory_entries`; Tier 2 reuses Knowledge V2

### Tests / verification

- Full backend suite → **PASS (120)**
- New: `test_module_manager.py`, expanded `test_neuro.py`

### Explicitly NOT built

- Real GPU residual hooks (vLLM/llama.cpp/TRT adapters)
- Subprocess plugin isolation
- LoRA / training execution loops
- Tier 3 distilled adapters

### Status

**PASS** (Phase 46 MVP) — architecture SPECIFIED; residual GPU path NOT TESTED (no residual runtime wired)

---

## 2026-09-21 — Phases 36–45 — Final platform polish / Master Program complete — PASS

### Phase 36 — Durable verification report store
- `VerificationReportStore` + migration v11 `verification_reports`
- Evaluate persists; `GET /api/verification/reports[+/{id}]`

### Phase 37 — Frontend API client expansion
- Typed client covers health, metrics, capabilities, approvals, jobs, release, security, master, verification, backup, telemetry

### Phase 38 — `.env.example` + config docs
- Context, backup root, chaos knobs documented; secrets stay out of public_summary

### Phase 39 — Backup / restore
- `Data/modules/backup/` local SQLite + artifacts snapshot
- Restore requires `confirm=true`; hash mismatch refused

### Phase 40 — Metrics / health surface
- `Data/modules/metrics/` + `GET /api/metrics`; health counters enriched

### Phase 41 — Chaos / resilience helpers
- `ChaosInjector` default OFF; refused when loopback_only is false
- `GET/POST /api/chaos*`

### Phase 42 — Integration harness
- `test_integration_harness.py` — approval → gateway → evidence → verification → durable report

### Phase 43 — Operator UI polish
- `/status` page with real master/release/security health
- Command agents/world panel uses honest control-plane signals (no fabricated “12 online”)

### Phase 44 — Security hardening pass
- Extra auditor findings: chaos off, no secrets in public_summary, restore confirm
- Chaos configure blocked off-loopback

### Phase 45 — Master gate summary
- `Data/modules/master/` aggregates release + security + evaluation + verification store
- `GET /api/master/gates` — READY ≠ production certified
- App version `0.46.0-phase45`

### Tests executed
- Full backend suite → **PASS (106)**

### Status
**PASS** (36–45) — Master Engineering Program phases 0–45 complete for local-first foundation

---

## 2026-09-21 — Phases 30–35 — Multi-agent, agent depth, security, native, trading — PASS

### Phase 30 — Multi-agent coordinator
- Sequential RESEARCH→GENERIC (configurable) on shared AgentRuntime

### Phase 31–32 — Coding / Research depth
- Coding plans: VERIFY + optional CSV inspect; Research adds VERIFY note
- Still gateway-only

### Phase 33 — Security audit
- `Data/modules/security/` posture checks; not a pentest
- `GET /api/security/audit`

### Phase 34 — Native runtime stub
- Python-first; native unavailable honestly

### Phase 35 — Trading stub
- Orders refused; no fabricated fills (`501`)

### Tests executed
- Full backend suite → **PASS (99)**

### Status
**PASS** (30–35)

---

## 2026-09-21 — Phases 26–29 — Browser/Media/Voice stubs + Release gates — PASS

### Phase 26 — Browser automation stub
- Honest UNSUPPORTED responses; no fabricated page content

### Phase 27 — Media automation stub
- Honest UNSUPPORTED; path required

### Phase 28 — Voice runtime stub
- ASR/TTS not implemented; no fabricated transcripts

### Phase 29 — Release gates
- `Data/modules/release/` — BLOCK/WARN/INFO local readiness
- Gates: catalog builtins, loopback, outbound deny, frontend dist
- `GET /api/release/gates` — ready ≠ production certified

### Tests executed
- Full backend suite → **PASS (94)**

### Status
**PASS** (26–29)

---

## 2026-09-21 — Phases 22–25 — Plugins, Evaluation, Isolation, Training — PASS

### Phase 22 — Plugins / MCP adapters
- `Data/modules/plugins/` — PluginRegistry binds external names → catalog capabilities
- MCP echo stub (no network); invoke only via ExecutionGateway
- discoverable ≠ authorized

### Phase 23 — Evaluation harness
- `Data/modules/evaluation/` — PASSED/FAILED/UNMEASURED/ERROR
- Foundation suite; embedding quality honestly UNMEASURED
- `POST /api/evaluation/foundation`

### Phase 24 — Isolation honesty
- `Data/modules/isolation/` — requested vs effective isolation
- Baseline: PROCESS + NETWORK_DENY + WORKSPACE (when outbound disabled)
- `GET/POST /api/isolation*`

### Phase 25 — Training registry stub
- `Data/modules/training/` — register only; start → FAILED honest 501
- registered ≠ trained; no fabricated metrics

### Tests executed
- Full backend suite → **PASS (86)**

### Status
**PASS** (22–25)

---

## 2026-09-21 — Phase 21 — Neuro Advisory Interface — PASS

### Objective

Feature-flagged NeuroAdvisor emitting advisory signals only. neural signal ≠ authority. Residual injection honestly unimplemented.

### Implementation

- `Data/modules/neuro/` — NeuroAdvisor, NeuroSignal, NeuroAssessment
- Child features: associative_memory, process_critic, residual_injection
- Chat includes neuro assessment when enabled; never gates execution
- API: `POST /api/neuro/assess`

### Tests executed

- Full backend suite → **PASS (82)**

### Known limitations

- Heuristic only — no real residual-stream / embedding neuro backend
- Does not influence approvals, gateway, or verification

### Status

**PASS**

---

## 2026-09-21 — Phase 20 — Observability Hub — PASS

### Objective

Honest in-process telemetry ring buffer + counters. Explicitly not production APM.

### Implementation

- `Data/modules/observability/` — ObservabilityHub, TelemetryEvent
- Emits from chat completion, capability execute, schedule tick
- Health includes observability snapshot
- API: `GET /api/telemetry`

### Tests executed

- Full backend suite → **PASS (79)**

### Known limitations

- In-memory only; lost on restart
- No export to Prometheus/OTLP yet

### Status

**PASS**

---

## 2026-09-21 — Phase 19 — Schedules — PASS

### Objective

Interval schedules that fire Jobs or Workflows through shared runtimes. Explicit tick (no hidden cron daemon claimed).

### Implementation

- `Data/modules/schedules/` — ScheduleStore, ScheduleRunner
- Targets: JOB (capability enqueue) or WORKFLOW
- Migration v10: `schedules` table
- API: `/api/schedules` + `POST /api/schedules/tick`

### Tests executed

- Full backend suite → **PASS (78)**

### Known limitations

- Interval-only (no cron expressions)
- Tick is explicit API/call — no background scheduler thread claimed beyond job worker

### Status

**PASS**

---

## 2026-09-21 — Phase 18 — Workflows Runtime — PASS

### Objective

Durable ordered capability sequences executed only through the Execution Gateway.

### Implementation

- `Data/modules/workflows/` — WorkflowStore, WorkflowRuntime, step defs
- States: CREATED → RUNNING → COMPLETED|FAILED|CANCELLED
- Migration v9: `workflows` table
- API: `/api/workflows` create/list/get/run/cancel

### Tests executed

- Full backend suite → **PASS (77)**

### Known limitations

- No branching/conditions; linear steps only
- No schedule triggers yet
- Cancel does not interrupt an in-flight gateway call mid-step

### Status

**PASS**

---

## 2026-09-21 — Phase 17 — Agent Runtime Skeleton — PASS

### Objective

Agent strategy layer over shared Run/Job/Gateway/Verification. No private execution paths. Feature-flagged OFF by default.

### Implementation

- `Data/modules/agents/` — AgentRuntime, AgentKind (GENERIC/CODING/RESEARCH)
- Plans capability steps; executes only via ExecutionGateway (or JobRuntime)
- Disabled when `LEVIATHAN_FEATURE_AGENTS=false`
- API: `POST /api/agents/execute`

### Tests executed

- Full backend suite → **PASS (75)**

### Known limitations

- Plans are heuristic stubs, not LLM planners
- Coding/Research are thin specializations, not full agents
- No multi-agent orchestration

### Status

**PASS**

---

## 2026-09-21 — Phase 16 — Verification Engine — PASS

### Objective

Completion authority from Evidence requirements. UNMEASURED ≠ PASSED. Model text is never verification.

### Implementation

- `Data/modules/verification/` — VerificationEngine, VerificationRequirement/Report
- Outcomes: PASSED / FAILED / UNMEASURED
- Helpers: require_artifact / require_file
- API: `POST /api/verification/evaluate`

### Tests executed

- Full backend suite → **PASS (73)**

### Known limitations

- Chat/agent completion not yet blocked by verification reports
- No durable verification report store (in-memory report per call)

### Status

**PASS**

---

## 2026-09-21 — Phase 15 — Memory Domain — PASS

### Objective

Controlled durable Memory separate from Knowledge. Refuse automatic model-output trust. Searchable; injectable into Context Engine.

### Implementation

- `Data/modules/memory/` — MemoryStore, kinds/status, FTS with LIKE fallback
- Rejects `trust=model_output`
- Chat retrieves matching memory into ContextBuilder
- Migration v8: `memory_entries` + `memory_fts`
- API: `/api/memory` CRUD-ish + search/archive/revoke

### Tests executed

- Full backend suite → **PASS (69)**

### Known limitations

- No semantic memory embeddings (feature flag exists, unused)
- No UI for memory curation

### Status

**PASS**

---

## 2026-09-21 — Phase 14 — Context Engine (token budgeting) — PASS

### Objective

Upgrade ContextBuilder into a budgeted Context Engine: heuristic token estimates, priority packing, knowledge dedupe, optional observation/evidence/memory slots, honest provenance.

### Implementation

- `Data/modules/context/types.py` — ContextSection, ContextPack metadata, `estimate_tokens` (chars/4)
- ContextBuilder packs system → history → knowledge → extras under budget; drops excess
- Settings domain `context` (`LEVIATHAN_CONTEXT_TOKEN_BUDGET`, reserve, max knowledge chars)
- OpenAICompatibleLLM constructs builder from settings

### Tests executed

- Full backend suite → **PASS (66)**

### Known limitations

- Token estimate is heuristic, not a real tokenizer
- Chat path does not yet inject observation/evidence/memory lists (slots ready)

### Status

**PASS**

---

## 2026-09-21 — Phase 13 — Evidence Domain — PASS

### Objective

Introduce Evidence as verified proof distinct from ToolObservation and model output. Artifact hash, file existence, and observation-existence claims with honest FAILED outcomes.

### Implementation

- `Data/modules/evidence/` — EvidenceStore, EvidenceService, EvidenceKind/Status
- Artifact hash verification reuses ArtifactStore.verify_hash
- Observation refs prove existence only (`existence_only` metadata)
- Migration v7: `evidence` table
- API: `GET /api/evidence`, claims for artifact/file/observation, `POST .../verify`

### Tests executed

- Full backend suite → **PASS (63)**

### Known limitations

- No composite multi-claim evidence graphs yet
- No UI for evidence review
- Completion authority for agents still not wired to evidence requirements

### Status

**PASS**

---

## 2026-09-21 — Phase 12 — Durable Effect Ledger + ToolObservation — PASS

### Objective

Persist every gateway execution as a canonical ToolObservation and EffectRecord. Observation is not evidence and not completion authority.

### Implementation

- `Data/modules/observations/` — ToolObservation, EffectRecord, ObservationStore
- ExecutionGateway writes durable observation+effect on every result (including REJECTED)
- Migration v6: `tool_observations` + `effect_ledger`
- API: `GET /api/observations`, `GET /api/observations/{id}`, effects prefer durable source

### Tests executed

- Full backend suite → **PASS (59)**

### Known limitations

- Output payloads stored in full JSON (no size capping yet)
- No Evidence domain linking observation → verified artifact proof

### Status

**PASS**

---

## 2026-09-21 — Phase 11 — Job Runtime + Resource Manager — PASS

### Objective

Durable capability jobs with validated lifecycle, bounded concurrency (ResourceManager), cancel, and execution only through the Execution Gateway.

### Implementation

- `Data/modules/jobs/` — JobState transitions, JobStore, ResourceManager, JobRuntime
- Lifecycle: CREATED → QUEUED → RUNNING → COMPLETED|FAILED|CANCELLED
- Jobs invoke capabilities via ExecutionGateway (approvals still enforced)
- ResourceManager uses `settings.resources.max_job_concurrency`
- Background worker started in app lifespan
- Migration v5: `jobs` table
- API: `GET/POST /api/jobs`, `GET .../{id}`, `POST .../{id}/cancel`

### Tests executed

- Full backend suite → **PASS (57)**

### Known limitations

- Single-process in-memory worker (no multi-worker claim fencing beyond SQLite UPDATE)
- Cancel of in-flight work is cooperative (post-gateway check)
- Effect ledger still in-memory (Phase 12+)

### Status

**PASS**

---

## 2026-09-21 — Phase 10 — Approval + Policy — PASS

### Objective

Verify gated capability execution with durable approvals and an explicit side-effect policy. Fake `approval_id` values must be denied.

### Implementation

- `Data/modules/approvals/` — PolicyEngine, ApprovalStore (SQLite), ApprovalService
- Policy: READ auto-allowed; WRITE/NETWORK/EXECUTE/DELETE/DESTRUCTIVE/EXTERNAL require approval
- Approval lifecycle: PENDING → APPROVED|DENIED|EXPIRED; APPROVED → CONSUMED (single-use)
- ExecutionGateway uses ApprovalService as `approval_checker`; consumes single-use on COMPLETED
- Migration v4: `approvals` table
- API: `GET/POST /api/approvals`, `GET .../{id}`, `POST .../{id}/approve|deny`

### Tests executed

- Full backend suite → **PASS (50)**

### Known limitations

- No UI for operator approvals yet
- Effect ledger remains in-memory
- Expiry is checked on read (lazy), not via background sweeper

### Status

**PASS**

---

## 2026-09-21 — Phase 9 — Capability Broker + Execution Gateway — PASS

### Objective

Introduce a Capability Catalog (what can be done) and a single Execution Gateway (how it is done) so privileged work is validated, policy-checked, executed via providers, and recorded as effects — without agent-local bypass paths.

### Implementation

- `Data/modules/execution/` — types, CapabilityCatalog, builtins, ExecutionGateway, effect ledger
- Builtin capabilities:
  - `file.read` / `file.inspect_csv` / `file.parse_pdf` → Function Runtime
  - `knowledge.search` → HybridRetriever
  - `artifact.create_text` → ArtifactStore (WRITE)
- Gateway flow: validate args → side-effect policy → optional approval → provider dispatch → CapabilityResult + EffectRecord
- Phase 9 policy: READ auto-allowed; WRITE+ requires `approval_id` (verified in Phase 10)
- API: `GET/POST /api/capabilities`, `GET .../{id}`, `POST .../{id}/execute`, `GET .../effects/recent`
- Health includes capability registry + gateway telemetry

### Tests executed

- Full backend suite → **PASS (44)**
- Includes approval-required rejection for WRITE without approval_id

### Known limitations

- Approval IDs are presence-checked only (Phase 10 verifies)
- Effect ledger is in-memory (not durable across restarts)
- Direct `/api/functions/*/execute` remains for Function Runtime; agent/privileged paths should use capabilities

### Status

**PASS**

---

## 2026-09-21 — Phase 8 — On-demand Function Runtime — PASS

### Objective

Build FunctionDefinition + FunctionRegistry with lazy loading, validation, lifecycle, timeout, cancellation, typed results, cleanup, telemetry, resource metadata, and bounded warm cache. Prove cold capabilities are not permanently loaded. Ship representative functions: text file read, CSV inspect, PDF parse.

### Implementation

- `Data/modules/function_runtime/` — registry, runtime, builtins catalog
- Lifecycle modes: PURE / ON_DEMAND / WARM_CACHE / PERSISTENT (defaults ON_DEMAND)
- Lazy import via entrypoint `package.module:callable`
- ON_DEMAND unloads `sys.modules` after execute (cold again)
- Bounded warm LRU cache; concurrency semaphore from settings
- Timeout via thread pool; cancel flags for in-flight calls
- Input schema validation → REJECTED
- Representative functions under `Data/functions/`:
  - `text_file_read`
  - `csv_inspector`
  - `pdf_parser` (optional pypdf; honest failure if missing)
- API: `GET /api/functions`, `GET /api/functions/{id}`, `POST .../execute`, `POST .../calls/{call_id}/cancel`
- Health includes function registry/load/telemetry

### Tests executed

- Full backend suite → **PASS (37)**
- Cold dormancy proven: registry construction does not import `Data.functions.*`; after ON_DEMAND execute module is unloaded

### Known limitations

- Execution Gateway / approvals not yet required (Phase 9–10)
- PDF parsing depends on optional `pypdf` (not added to requirements.txt)
- Cancel is cooperative via cancel_event / pre-exec flag; hard kill of arbitrary native work is not claimed

### Status

**PASS**

---

## 2026-09-20 — Phase 7 — Knowledge V2 — PASS

### Objective

Upgrade Knowledge with documents, chunks, provenance, hashes, ingest states, incremental ingest, atomic readiness, lexical retrieval, embedding interface, metadata filters, and hybrid retrieval interface. Bulk corpus root remains `LEVIATHAN_DATA_ROOT` (default `D:/ModelData`).

### Implementation

- New module `Data/modules/knowledge/`:
  - `KnowledgeStore` — documents/chunks/ingest_files, atomic READY/FAILED
  - `chunk_text` — overlapping plain-text chunking
  - `HybridRetriever` + `RetrievalQuery`/`RetrievalHit`
  - `EmbeddingProvider` protocol + `NullEmbeddingProvider` (no fabricated vectors)
- Migration v3: Knowledge V2 columns + `knowledge_chunks` + `knowledge_chunk_fts` + `knowledge_ingest_files`
- `Database` knowledge methods delegate to KnowledgeStore (Step-1 compat)
- Chat uses HybridRetriever (chunk-level context)
- API:
  - existing CRUD/search enriched (`hits` + `documents`)
  - `GET /api/knowledge/{id}` with chunks
  - `POST /api/knowledge/ingest/path`
  - `POST /api/knowledge/ingest/scan`
- Path escape outside data_root rejected
- FAILED documents excluded from READY search

### Tests executed

- `python3 -m unittest discover -s Data/backend/tests -v` → **PASS (30)**
- Embedding quality: **UNMEASURED** (null provider; no model embeddings wired)

### Known limitations

- Plain-text parsers only (`.txt/.md/.csv/.json/.log`); heavy parsers remain future Functions
- No real embedding backend yet — hybrid interface is lexical-only until a provider is available
- Scan skips files > 5 MiB

### Status

**PASS**

---

## 2026-09-20 — Phase 6 — Artifact System — PASS

### Objective

Canonical Artifacts with DB metadata + filesystem content + hash provenance.

### Implementation

- `Data/modules/artifacts/` (`ArtifactStore`, `ArtifactRecord`)
- Content under `LEVIATHAN_ARTIFACTS_ROOT` (default `Data/backend/data/artifacts`)
- Migration v2 creates `artifacts` table
- API: `POST/GET /api/artifacts`, `POST /api/artifacts/{id}/verify`
- Path-traversal filename rejected

### Tests executed

- Full backend suite → PASS (21)

### Status

**PASS**

---

## 2026-09-20 — Phase 5 — Database Migration Foundation — PASS

### Objective

Introduce ordered, restart-safe schema versioning without destroying existing SQLite data.

### Implementation

- `Data/backend/migrations.py` with `schema_migrations` table and contiguous version validation.
- Baseline migration v1 is a no-op marker so existing DBs adopt versioning safely.
- Applied during application lifespan before DB/run initialize.

### Tests executed

- `test_migrations` + full backend suite → PASS (19)

### Status

**PASS**

---

## 2026-09-20 — Phase 4 — Canonical Run + Event Model — PASS

### Objective

Introduce canonical Run lifecycle, validated transitions, structured events, and honest completion/failure semantics wired into `/api/chat`.

### Implementation

- New module `Data/modules/run/` with `RunState`, `validate_transition`, `RunRecord`, `EventType`, `EventRecord`, `RunStore`.
- SQLite tables `runs` + `run_events` in the existing DB file.
- Chat orchestration creates a Run and transitions: CREATED → PLANNING → RETRIEVING?/EXECUTING → COMPLETED or FAILED.
- `FAILED → COMPLETED` is illegal (tested).
- COMPLETED only after assistant message persistence.
- `GET /api/runs/{run_id}` returns run + events.

### Tests executed

- `python3 -m unittest discover -s Data/backend/tests -v` → PASS (17)
- Includes transition + store tests

### Status

**PASS**

---

## 2026-09-20 — Phase 3 — Core Module Ownership — PASS

### Objective

Separate reasoning, context, and model-runtime ownership into `Data/modules/` without breaking Step 1 callers.

### Implementation

- `Data/modules/reasoning/` owns `ReasoningEngine` / `ReasoningPlan`
- `Data/modules/context/` owns `ContextBuilder` / `ContextPack` (extracted from LLM prompt assembly)
- `Data/modules/model_runtime/` owns `OpenAICompatibleLLM`
- Backend shims `Data/backend/reasoning.py` and `llm.py` re-export for compatibility
- `main.py` imports from modules

### Tests executed

- Context builder tests + full backend suite → PASS

### Status

**PASS**

---

## 2026-09-20 — Phase 2 — Typed Configuration Foundation — PASS

### Objective

Centralize configuration into typed nested domains with validation, data-root, feature flags, and resource ceilings while preserving Step 1 compatibility accessors.

### Implementation

- Expanded `Data/backend/config.py` with domains: `runtime`, `model`, `knowledge`, `reasoning`, `features`, `resources`, `network`.
- Added `ConfigurationError` for invalid booleans/ints/paths/conflicting feature flags.
- Added `LEVIATHAN_DATA_ROOT` (default `D:/ModelData`, preserved on POSIX).
- Added resource concurrency limits and experimental feature flags (all default OFF).
- Loopback-only host guard.
- `Settings.public_summary()` exposed on `/api/health` (no secrets).
- Compatibility properties: `llm_*`, `knowledge_top_k`, `max_history_messages`, `reasoning_enabled`.

### Files changed

- `Data/backend/config.py`
- `Data/backend/main.py` (health config summary; version `0.3.0-phase2`)
- `Data/backend/tests/test_config.py`
- `.env.example`
- docs

### Tests executed

- `python3 -m unittest Data.backend.tests.test_config -v` → PASS (6)
- `python3 -m unittest Data.backend.tests.test_foundation -v` → PASS (4)
- Manual `/api/health` includes `config` object → PASS

### Known limitations

- No config file layer yet (env-only precedence).
- Resource limits are declared but not yet enforced by a Resource Manager (Phase 12).

### Status

**PASS**

---

## 2026-09-20 — Phase 1 — Frontend Application Foundation — PASS

### Objective

Migrate the static HTML/CSS/JS frontend to React + TypeScript + Vite while preserving LEVIATHAN visual identity and chat/backend connectivity.

### Implementation

- Replaced static `index.html` / `chat.html` / `js/*` shell with a Vite React/TS SPA under `Data/frontend/`.
- Preserved `tokens.css`, `leviathan.css`, `chat.css` and image assets.
- Added typed API client (`src/api/client.ts`) for health/conversations/chat.
- Routes: `/` Command dashboard, `/chat` real chat, `/chat.html` → `/chat`.
- Backend serves `Data/frontend/dist` (SPA + `/assets`); health reports `frontend.dist_ready`.
- Vite dev proxy: `/api` → `http://127.0.0.1:8765`.

### Files changed (primary)

- `Data/frontend/**` (new Vite app)
- `Data/backend/main.py` (SPA serving)
- `Data/backend/config.py` (`FRONTEND_DIST`)
- `.gitignore` (node_modules/dist)
- docs: `buildplan.md`, `leviathan_system.md`, `cursor.md`, `README.md`

### Tests executed

- Backend: `python3 -m unittest Data.backend.tests.test_foundation -v` → PASS (4 tests)
- Frontend: `npm run typecheck` → PASS
- Frontend: `npm run lint` → PASS (0 errors)
- Frontend: `npm run test` → PASS (1 test)
- Frontend: `npm run build` → PASS
- Manual HTTP: `/api/health`, `/`, `/chat`, `/assets/hero.jpg`, `POST /api/conversations` → PASS
- Live LLM chat completion: NOT TESTED (no local model server at `127.0.0.1:1234`; health correctly reports `llm.available=false`)

### Verification

- UI loads from Vite dist through FastAPI.
- Chat page bootstraps conversations against real backend APIs.
- Honest LLM offline semantics preserved.

### Known limitations

- Dashboard agent/project panels remain visual shell (not backend-backed).
- Context assembly still lives in `llm.py` (Phase 14 target).
- No streaming SSE yet.

### Status

**PASS**

---

## 2026-09-20 — Phase 0 — Current-State Audit — PASS

### Objective

Map the repository, identify documentation drift, and produce a safe migration plan before structural work.

### Findings

- Step 1 foundation is real: FastAPI, SQLite chat/Knowledge, ReasoningEngine, OpenAI-compatible LLM client, static UI (pre-Phase 1).
- Major doc drift: `leviathan_system.md` described HADES, not current LEVIATHAN.
- `Data/modules/` and `Data/functions/` were empty placeholders only.
- No Run/Event model, migrations framework, Execution Gateway, Memory, Evidence, Neuro.
- Context injection was embedded in `llm.py`.
- Configuration was a small typed `Settings` dataclass (acceptable Phase 0 baseline; Phase 2 expands).

### Migration plan (ordered)

Follow Master Engineering Program Phases 1→… without jumping to Neuro. Preserve working chat. Prefer module ownership over `main.py` growth. Rewrite `leviathan_system.md` as current-system truth; keep HADES as appendix lessons only.

### Tests executed

- Foundation unit tests → PASS
- No code behavior changes in Phase 0 itself beyond audit documentation (Phase 1 implements frontend).

### Status

**PASS**

---

# 1. Project goal

Build LEVIATHAN as a cleaner, smaller and more coherent successor architecture to HADES.

The project should preserve proven behavior and invariants from HADES while avoiding accumulated legacy code, duplicated execution paths, large wrappers and mixed responsibility boundaries.

Primary language:

```text
Python
```

Frontend remains browser-based HTML/CSS/JavaScript for now, served by the Python backend.

---

# 2. Work completed before Step 1

## 2.1 LEVIATHAN visual shell created in HADES

A standalone LEVIATHAN visual concept was first created inside the HADES repository.

The shell included:

- dashboard/Command page;
- chat page;
- shared visual design tokens;
- dashboard/chat CSS;
- JavaScript shell interactions;
- image assets.

This was intentionally a visual shell, not yet a real AI runtime.

## 2.2 Standalone LEVIATHAN repository prepared

The contents of the HADES `LEVIATHAN/` folder were copied into:

`syneyexx/leviathan`

The initial transfer was merged through PR #1.

This established the visual repository baseline.

---

# 3. Step 1 — LLM Chat Foundation

Step 1 converted the visual chat shell into the first real LEVIATHAN runtime.

The implementation was developed on PR #2 and then merged into `main`.

## 3.1 Python backend

A FastAPI backend was added.

Initial backend responsibilities:

- application startup;
- API routes;
- serving the existing frontend;
- chat orchestration;
- LLM communication;
- conversation persistence;
- Knowledge persistence/retrieval;
- lightweight reasoning.

## 3.2 LLM connection

An OpenAI-compatible LLM client was added.

Current behavior:

- default local endpoint is LM Studio-friendly;
- endpoint is configurable through environment variables;
- model can be pinned explicitly;
- if no model is configured, LEVIATHAN can query `/v1/models` and use the first available model;
- model/provider unavailability is reported as failure rather than replaced with fabricated assistant output.

Current default endpoint:

```text
http://127.0.0.1:1234/v1
```

## 3.3 Persistent chat

SQLite persistence was added for:

- conversations;
- conversation titles;
- user messages;
- assistant messages.

The chat page can now:

- create a conversation;
- send a real message to the Python backend;
- call the configured LLM;
- persist responses;
- reload conversation history;
- switch conversations;
- create new chats.

## 3.4 Simple reasoning layer

A first lightweight `ReasoningEngine` was added.

Current responsibilities:

- classify basic intent;
- estimate basic complexity;
- decide whether Knowledge retrieval should be used;
- create a small structured/public plan summary.

This is deliberately small.

It exists as a clean expansion seam for later planning/routing rather than attempting to rebuild HADES reasoning in Step 1.

It is not private chain-of-thought storage.

## 3.5 Knowledge system

A first local Knowledge system was added using SQLite.

Current features:

- Knowledge document storage;
- title/content/source metadata;
- update/upsert;
- list;
- delete;
- search;
- FTS5 full-text retrieval when available;
- LIKE fallback when FTS5 is unavailable;
- relevant Knowledge injected into model context when the reasoner selects retrieval.

This provides the first HADES-like persistent knowledge capability without importing the old HADES implementation.

## 3.6 Health and API behavior

A health endpoint was added exposing runtime/model status.

The backend returns explicit HTTP errors when the LLM is unavailable rather than storing fake assistant success.

## 3.7 Tests

Foundation unit tests were added for:

- conversation persistence;
- message persistence;
- Knowledge retrieval;
- reasoning behavior.

No fake live-model test is claimed when a real model provider is unavailable.

---

# 4. Repository restructuring completed

After Step 1, the repository structure was normalized under `Data/`.

Current primary structure:

```text
Data/
├── backend/
├── frontend/
├── modules/
├── functions/
└── docs/
```

## 4.1 Backend moved to `Data/backend/`

All Python runtime/backend code now belongs under:

```text
Data/backend/
```

Current files include:

```text
Data/backend/
├── __init__.py
├── config.py
├── database.py
├── llm.py
├── main.py
├── reasoning.py
└── tests/
    ├── __init__.py
    └── test_foundation.py
```

## 4.2 Frontend moved to `Data/frontend/`

The dashboard/chat browser shell now belongs under:

```text
Data/frontend/
```

Current structure includes:

```text
Data/frontend/
├── index.html
├── chat.html
├── assets/
├── css/
└── js/
```

The Python backend serves this directory.

## 4.3 `Data/modules/` created

Created as the future home for larger optional/domain-specific subsystems.

Potential later examples:

- coding;
- research;
- neural;
- agents;
- plugins;
- MCP;
- trading;
- media;
- automation.

## 4.4 `Data/functions/` created

Created as the future home for smaller reusable Python helpers.

This prevents both the backend and feature modules from accumulating duplicated low-level utility code.

## 4.5 Runtime launcher updated

`RUN_LEVIATHAN.bat` now starts the application using the Python package path:

```text
Data.backend.main:app
```

## 4.6 Runtime database location normalized

Default local SQLite runtime database location is now intended under:

```text
Data/backend/data/leviathan.db
```

Runtime database files remain ignored by Git.

---

# 5. Documentation phase completed

`Data/docs/` was created as the project architecture/build documentation location.

Current documentation files:

## `Data/docs/leviathan_system.md`

Describes the current HADES architecture as a reference for LEVIATHAN, including:

- reasoning/routing;
- model layer;
- Tool Kernel;
- Capability Broker;
- plugins/MCP;
- execution path;
- approvals;
- isolation;
- Work Runtime;
- completion/verification truth;
- Coding Agent;
- Research;
- Knowledge;
- Memory;
- Evidence/Artifacts;
- Neural V2;
- native runtime;
- storage;
- frontend;
- observability;
- security boundaries;
- architectural debt LEVIATHAN should avoid.

## `Data/docs/cursor.md`

Repository map for Cursor explaining:

- which file owns which current function;
- where new backend logic belongs;
- where frontend logic belongs;
- when to use `modules` versus `functions`;
- current runtime flow;
- project implementation rules.

## `Data/docs/buildplan.md`

This file.

---

# 6. Current architecture after Step 1

```text
Browser
  │
  ▼
Data/frontend/chat.html
  │
  ▼
Data/frontend/js/chat.js
  │
  ▼
FastAPI — Data/backend/main.py
  │
  ├────────► ReasoningEngine
  │           Data/backend/reasoning.py
  │
  ├────────► SQLite Knowledge retrieval
  │           Data/backend/database.py
  │
  ├────────► OpenAI-compatible LLM
  │           Data/backend/llm.py
  │
  └────────► SQLite conversation persistence
              Data/backend/database.py
```

The current system is intentionally simple and real.

There is no simulated tool layer or fake autonomous runtime hidden behind the UI.

---

# 7. Current Step 1 capabilities

Implemented now:

- Python runtime;
- FastAPI;
- dashboard served by backend;
- functional chat page;
- OpenAI-compatible LLM connection;
- LM Studio-friendly local model support;
- model discovery;
- persistent conversations;
- persistent messages;
- local SQLite database;
- Knowledge document storage;
- FTS5 Knowledge retrieval;
- fallback Knowledge search;
- lightweight deterministic reasoning;
- basic model/health reporting;
- configuration through `.env`;
- foundation regression tests;
- normalized `Data/` directory layout;
- documentation structure.

---

# 8. Explicitly not implemented yet

The following HADES-scale systems are not yet LEVIATHAN functionality:

- full Context Engine;
- capability registry;
- Tool Kernel;
- tool execution;
- Execution Gateway;
- policy engine;
- approval service;
- effect ledger;
- canonical ToolObservation;
- Work/Run runtime;
- artifacts;
- evidence;
- verification engine;
- long-running cancellation/runtime control;
- Coding Agent;
- Research Agent;
- Memory system;
- Neural system;
- plugin runtime;
- MCP runtime;
- browser automation;
- native/C++ runtime;
- workflows;
- schedules;
- multi-agent orchestration;
- trading;
- media automation;
- voice;
- production observability/release gates.

These must be built deliberately in future phases.

---

# 9. Build principles going forward

## 9.1 Python remains the primary implementation language

Use Python for:

- orchestration;
- APIs;
- reasoning/planning;
- lifecycle;
- persistence services;
- model integration;
- capability management;
- agents;
- verification;
- Knowledge/Memory.

Native/C++ should only be introduced later for clearly justified low-level/performance responsibilities.

## 9.2 HADES is reference, not source tree

Before rebuilding a large subsystem:

1. inspect current HADES behavior;
2. inspect recent HADES regression tests;
3. identify the core invariant;
4. identify duplicated/obsolete code;
5. design a smaller LEVIATHAN contract;
6. implement from scratch;
7. verify with tests.

## 9.3 No fake completion

Carry forward the strongest HADES truth invariants:

```text
model output != evidence
request boolean != authority
dispatch != completion
requested isolation != effective isolation
unmeasured != passed
```

## 9.4 Keep the core small

Large domain systems should live in `Data/modules/` rather than being folded directly into `Data/backend/main.py`.

## 9.5 One infrastructure path

Future agents should share the same:

- capabilities;
- execution gateway;
- policy;
- approvals;
- observations;
- lifecycle;
- persistence;
- verification.

Avoid separate generic execution systems for Coding, Research, plugins and MCP.

---

# 10. Recommended next build phases

The exact sequence can change after design review, but the current recommended order is below.

## Phase 2 — Core runtime contracts

Build the contracts that future systems can share before adding many agents.

Recommended components:

- `Run` model/lifecycle;
- structured Context Pack;
- canonical result/observation models;
- basic event model;
- explicit service/repository boundaries.

Goal: establish the skeleton that prevents later duplicate state machines.

## Phase 3 — Capability system

Build:

- CapabilityDescriptor;
- Capability Registry;
- built-in core capabilities;
- schema validation;
- capability discovery;
- capability inspection.

Do not start with dozens of wrappers.

## Phase 4 — Execution Gateway

Build one controlled execution path:

```text
request
→ validation
→ policy
→ authorization
→ approval
→ executor
→ observation
→ evidence/effect record
```

Initial capabilities could include:

- filesystem read;
- filesystem list;
- filesystem write;
- terminal/process execution.

Start with strict boundaries and tests.

## Phase 5 — Context Engine

Replace ad-hoc context assembly with one structured Context Pack that can combine:

- system instructions;
- conversation;
- constraints;
- Knowledge;
- Memory later;
- Evidence;
- Artifacts;
- tool observations;
- Neural signals later.

Add token budgeting, deduplication and provenance.

## Phase 6 — Work/Run persistence

Build persistent long-running runs/tasks using the shared lifecycle.

Add:

- steps;
- events;
- cancellation;
- checkpoints;
- verification state;
- completion authority.

## Phase 7 — Artifacts and Evidence

Add first-class concrete outputs and evidence references.

Completion should be able to prove requested files/results exist.

## Phase 8 — Coding Agent

Build Coding as a strategy layer on top of the shared runtime.

It should use the same filesystem, terminal, approval, lifecycle and verification infrastructure.

## Phase 9 — Research

Build Research using:

- shared capabilities;
- network policy;
- Knowledge;
- Evidence;
- provenance;
- source verification.

## Phase 10 — Memory

Build persistent controlled Memory separately from Knowledge.

Do not automatically persist arbitrary model output as memory truth.

## Phase 11 — Plugins and MCP

Normalize external functionality into the same Capability system.

Prefer:

- declarative adapters;
- protocol adapters;
- minimal custom providers.

Avoid reproducing the large wrapper count of HADES.

## Phase 12 — Neural

Only after the Context/Knowledge/Memory/Evidence contracts are stable.

Neural should initially be advisory/associative only.

It must never own permissions, approval, execution authority or completion.

## Later phases

- multi-agent orchestration;
- automation/workflows;
- schedules;
- browser;
- native acceleration;
- trading simulation;
- media automation;
- voice;
- stronger observability/evals/release gates.

---

# 11. Definition of progress

A phase is not complete merely because files exist.

For a build phase to be considered complete it should normally have:

- a documented contract;
- implementation;
- integration into the real runtime where intended;
- focused tests;
- truthful failure states;
- no fake/placeholder completion claims;
- updated docs.

---

# 12. Current project state

As of this document:

```text
Visual shell                  DONE
Standalone repository         DONE
Python/FastAPI foundation     DONE
Real chat connection          DONE
LLM provider connection       DONE
SQLite conversations          DONE
Simple reasoning              DONE
Knowledge database            DONE
Knowledge retrieval           DONE
Data/backend structure        DONE
Data/frontend structure       DONE
Data/modules structure        DONE
Data/functions structure      DONE
Data/docs structure           DONE
Advanced runtime/core         NOT YET
Tools/capabilities            NOT YET
Agents                        NOT YET
Neural                        NOT YET
Plugins/MCP                   NOT YET
```

This is intentional.

The objective of Step 1 was to establish a small working base rather than prematurely recreate the full HADES surface area.

---

# 13. Documentation maintenance rule

After every major phase:

- update this `buildplan.md` with what actually shipped;
- update `cursor.md` if ownership/file locations change;
- update `leviathan_system.md` if the target architecture or HADES reference lessons materially change;
- do not document unimplemented functionality as finished.
