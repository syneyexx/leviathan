# LEVIATHAN System Backend Reference

> **Canonical backend documentation.** This is the single human-readable backend architecture reference for LEVIATHAN.
>
> Documentation snapshot: **2026-09-26**, based on `main` after External Execution Fabric (#163), General Assistant Fabric (#165), and Frontier Master Program W0A/W0B baseline. Runtime code and tests remain the final authority when this document and executable behavior disagree.
>
> Companion frontend reference: [`Leviathan_system_frontend.md`](./Leviathan_system_frontend.md).

---

## 1. Documentation policy

`Data/docs/` intentionally contains exactly two canonical documents:

1. `Leviathan_system_backend.md` — backend architecture, ownership, runtime flows, module/file map, machine program state locations and active target architecture.
2. `Leviathan_system_frontend.md` — frontend architecture, routes, pages, API/client structure and frontend file map.

Program gate manifests, generated verifier reports and machine state belong outside `Data/docs`, normally under `Data/backend/tests/` or `scripts/`. New implementation work should update these two canonical documents instead of creating another architecture Markdown file.

### Status vocabulary

- **CURRENT** — implemented in the current repository/runtime.
- **FEATURE-GATED** — implementation exists, but runtime availability depends on configuration/provider/hardware.
- **BOUNDARY/STUB** — an honest boundary exists but production implementation is not claimed.
- **TARGET** — part of an active implementation program, not yet a claim about current runtime behavior.

---

# 2. What LEVIATHAN is

LEVIATHAN is a **local-first AI control plane and cognitive runtime**. The backend is not a single LLM wrapper: it composes model routing, cognition, retrieval, durable memory, neural advisory layers, capabilities, approvals, agents, jobs/workers, evidence, verification, datasets, training, evaluation, market simulation and operator controls into one system.

The architectural rule is **one responsibility → one canonical owner**. Existing subsystems are extended in-place. Parallel `*V2` runtimes are forbidden unless an explicit tested migration replaces the old owner.

High-level runtime:

```text
User / UI
   |
   v
FastAPI control plane
   |
   +--> Settings / BehaviorProfile
   +--> CognitiveRuntime
   |      +--> TaskModel / Perception / BeliefState / WorkingMemory
   |      +--> MetaController / CognitivePlanner / ActionSelector
   |      +--> Brain/RAG + Memory + Evidence + Neuro/Cortex
   |      +--> CapabilityBroker -> ExecutionGateway
   |      +--> Agent delegation -> Coding / Research / specialists
   |      +--> Verification + Completion
   |
   +--> Model Control Plane -> inference_session -> provider/runtime
   |
   +--> JobRuntime -> external worker pools for long/heavy work
   |
   +--> SQLite durable state / observations / receipts / artifacts
```

---

# 3. Canonical ownership map

The encoded ownership contract lives in `Data/modules/common/ownership.py`.

| Responsibility | Canonical owner | Primary location |
|---|---|---|
| Application composition | FastAPI composition root | `Data/backend/main.py` |
| Configuration | Settings Control Plane | `Data/modules/settings/` |
| Assistant behavior/identity | BehaviorProfile | `Data/modules/settings/behavior*.py`, `resolver.py`, `seed.py` |
| Legacy intent/complexity classification | ReasoningEngine | `Data/modules/reasoning/` |
| Cognitive orchestration | CognitiveRuntime | `Data/modules/cognition/` |
| Cognitive compute policy | MetaController + ReasoningPolicy | `Data/modules/cognition/meta_controller.py`, `Data/modules/intelligence/policy.py` |
| Cognitive planning | CognitivePlanner | `Data/modules/cognition/planner.py` |
| Orchestration action selection | ActionSelector | `Data/modules/cognition/action_selector.py` |
| Model selection/routing/residency | Model Control Plane | `Data/modules/models/` |
| Provider transport/inference | Model runtime | `Data/modules/model_runtime/` |
| Prompt/context compilation | Context subsystem | `Data/modules/context/` (canonical); cognition `context_v3.py` is adapter only |
| Unified knowledge access | Brain facade | `Data/modules/brain/` |
| Documents/RAG/retrieval | Knowledge | `Data/modules/knowledge/` |
| Durable scoped memory | Memory | `Data/modules/memory/` |
| Neural advisory/cortex | Neuro | `Data/modules/neuro/` |
| Evidence | Evidence | `Data/modules/evidence/` |
| Capabilities/side effects | ExecutionGateway | `Data/modules/execution/` |
| Cold-path functions | FunctionRuntime | `Data/modules/function_runtime/`, `Data/functions/` |
| Permission/approval policy | Approvals | `Data/modules/approvals/` |
| Durable jobs | JobRuntime | `Data/modules/jobs/` |
| External execution pools | Worker system | `Data/modules/workers/` |
| Specialist agents | AgentRuntime/AgentFleet | `Data/modules/agents/` |
| Coding | CodingControlPlane | `Data/modules/coding/` |
| Research | ResearchService | `Data/modules/research/` |
| Datasets | DatasetService | `Data/modules/datasets/` |
| Training | TrainingService | `Data/modules/training/` |
| Evaluation/release evidence | Evaluation platform | `Data/modules/evaluation/`, `Data/modules/release/` |
| Verification | VerificationEngine | `Data/modules/verification/` |
| Artifacts | ArtifactStore | `Data/modules/artifacts/` |
| MCP integration | McpBridge/McpProvider | `Data/modules/mcp/` |
| Plugins | PluginRegistry | `Data/modules/plugins/` |
| Dynamic modules | ModuleManager | `Data/modules/module_manager/` |
| Market simulation | MarketSimControlPlane | `Data/modules/market_sim/` |
| Workflows/schedules | WorkflowRuntime / ScheduleRunner | `Data/modules/workflows/`, `Data/modules/schedules/` |
| Tasks | TaskService | `Data/modules/tasks/` |
| Observability | ObservabilityHub | `Data/modules/observability/` |
| Metrics/time series | Metrics | `Data/modules/metrics/` |
| Persistent metadata | central SQLite | `Data/backend/database.py`, `migrations.py` |

---

# 4. Backend composition root

## 4.1 `Data/backend/main.py`

`main.py` is the composition root (**CURRENT**). It creates and wires the shared instances used by route modules and services. Domain HTTP handlers live in `Data/backend/routes/*` via `build_*_router(deps)`; `main.py` keeps composition, lifespan, middleware, **`POST /api/chat`**, SPA shell routes (`/`, `/chat`, `/{spa_path}`), and `/api/health`.

Current wiring includes:

- `Database`, `MigrationRunner`, run/artifact stores;
- embedding provider, `KnowledgeStore`, `HybridRetriever`, `StagedRetriever`, `DeepRecallService`, `AtlasStore`, `WhyLibrary`, `KnowledgeAssimilationService`;
- `FunctionRuntime`, `CapabilityCatalog`, `ExecutionGateway`, approvals, observations and capability receipts;
- `JobRuntime`, resource manager and external-worker admission;
- evidence, memory and verification stores/services;
- `AgentRuntime`, `MultiAgentCoordinator`, `AgentFleetService`;
- workflows and schedules;
- observability, telemetry and metrics;
- Neuro/Cortex/residual components;
- module manager, plugins and MCP bridge/provider;
- evaluation, release gates, training/flywheel services;
- datasets, research, coding and market simulation;
- browser/media/voice capability services and honest stubs;
- `ReasoningEngine`, `OpenAICompatibleLLM`, `ModelControlPlane`;
- Settings Control Plane and BehaviorProfile resolution;
- `CognitiveRuntime`, specialist delegation handlers and cognition persistence;
- tasks, Brain facade and domain strategy registry;
- security, backup, chaos and master/release checks.

## 4.2 Backend core files

| File | Purpose |
|---|---|
| `Data/backend/main.py` | Composition root + chat + SPA + health (**CURRENT**) |
| `Data/backend/config.py` | typed environment/runtime settings |
| `Data/backend/database.py` | SQLite access and initialization |
| `Data/backend/migrations.py` | ordered schema migrations; current main reaches migration **52** (`paper_portefeuille`) |
| `Data/backend/llm.py` | compatibility/boundary helpers |
| `Data/backend/reasoning.py` | compatibility import/boundary |

SQLite is the canonical metadata database. Subsystems must not silently create a second metadata authority.

### SQLite write architecture (CONTROL_WRITE vs COMMIT_WRITE)

LEVIATHAN uses one canonical SQLite database with two explicit write classes:

| Class | Rule | Examples |
| --- | --- | --- |
| `CONTROL_WRITE` | Tiny, latency-sensitive, **direct** SQLite allowed | supervisor/worker heartbeats, job status transitions, cancel flags, lease renewals |
| `COMMIT_WRITE` | Substantial canonical mutations **must** go through the DB Commit Coordinator | Knowledge chunks/embeddings, research evidence/claims/reports, dataset index batches, MarketSim event batches, evaluation/training lineage batches, source-ingestion bulk metadata |

**DB Commit Coordinator** (`Data/modules/db_commit/`, worker pool `db_commit`, `desired_count=1`):

- External worker managed by `WorkerSupervisor` (not an AI agent).
- Producers submit typed `CommitIntent` messages (payload **refs** + hashes — never giant inline blobs, never arbitrary SQL).
- Fast path: Windows-compatible localhost IPC; correctness path: durable filesystem spool under `<db-parent>/commit_spool/{pending,inflight,applied,failed,quarantine}`.
- Allowlisted `CommitHandlerRegistry` adapters call domain stores (`KnowledgeStore`, `ResearchStore`, …) — domain ownership stays with those stores.
- Idempotent `commit_receipts` / `commit_batches` tables live in the **same** main DB; crash recovery checks receipts before re-applying.
- Bulk handlers use bounded batches and release the SQLite writer lock between batches so control-plane heartbeats are not starved.
- Writer unavailable ⇒ durable spool / `DB_COMMIT_BACKPRESSURE` / `DB_COMMIT_SPOOL_UNAVAILABLE` — **never** fall back to direct heavy SQLite writes from producers.
- Legacy `knowledge_commit` pool defaults to `0`; `knowledge.commit` jobs are owned by `db_commit`.

Canonical connection policy: `Data/modules/common/sqlite_policy.py` (busy_timeout on hot paths; `PRAGMA journal_mode=WAL` only during initialize/migration).

---


# 5. API route map

Dedicated route modules live in `Data/backend/routes/` (Wave 0D — domain routers extracted from `main.py`):

| Route module | System |
|---|---|
| `agents.py` | Agent Fleet / execute / multi-agent |
| `agent_signals.py` | agent signal fabric |
| `analytics.py` | analytics |
| `approvals.py` | approval requests/decisions |
| `artifacts.py` | artifacts + run lookup |
| `brain.py` | Brain graph/search/status |
| `browser.py` | legacy browser request + QA journey surfaces |
| `browser_qa.py` | Browser QA crawls control plane |
| `capabilities.py` | capability catalog / invoke / receipts |
| `coding.py` | Coding Agent sessions/turns/actions |
| `cognition.py` | cognition submit/status/events/cancel/resume |
| `conversations.py` | conversation CRUD |
| `datasets.py` | dataset management, ingest/index/offline workflows |
| `efficiency.py` | efficiency/resource surfaces |
| `evaluation.py` | evaluation harness / platform / residual |
| `evidence.py` | evidence store |
| `flywheel.py` | post-training challengers / promotions / lineage |
| `functions.py` | function registry / invoke |
| `jobs.py` | job runtime |
| `knowledge.py` | knowledge / atlas / deep-recall / why / ingest |
| `market_sim.py` | market simulation, strategies, data, paper trading |
| `mcp.py` | MCP servers/sessions/tools |
| `media.py` | media capability request |
| `memory.py` | memory store |
| `models.py` | model registry/providers/downloads/routing/runtime |
| `modules.py` | module manager discover/execute |
| `multimodal.py` | multimodal sessions |
| `neuro.py` | Neuro / Cortex / residual operator surfaces |
| `observability.py` | runtime events/observability |
| `observations.py` | observation store |
| `platform.py` | thin misc: architecture, metrics, telemetry, isolation, release, security, native, trading stub, backup, chaos, secrets, context preview, master gates |
| `plugins.py` | plugin registry / invoke |
| `research.py` | research projects/runs/sources |
| `schedules.py` | schedule store / runner |
| `settings.py` | Settings + BehaviorProfile operations |
| `system.py` | telemetry/system status |
| `tasks.py` | durable task orchestration |
| `trading_orchestra.py` | trading-only orchestras/agents |
| `training.py` | durable training jobs + preference/synthetic/active-learning surface |
| `verification.py` | verification evaluate / reports |
| `voice.py` | voice capability request |
| `workers.py` | worker supervisor / admission |
| `workflows.py` | workflow store / runtime |

`main.py` (**CURRENT**) retains composition + `POST /api/chat` + SPA shell + `/api/health`. Route modules are the preferred domain boundary.

---

# 6. Chat, Reasoning and CognitiveRuntime

## 6.1 Current chat intelligence path

The current architecture combines a lightweight legacy classifier with a real cognitive runtime:

```text
POST /api/chat
  -> effective Settings / BehaviorProfile snapshot
  -> legacy ReasoningEngine + retrieval policy
  -> Brain/RAG / Memory / Neuro enrichment when justified
  -> CognitiveRuntime.submit(...)
       -> TaskModel
       -> Perception
       -> BeliefState
       -> WorkingMemory
       -> MetaController
       -> CognitivePlanner
       -> ActionSelector
       -> model / retrieval / capability / agent / verify loop
  -> cognition-owned answer when available
  -> otherwise compatible chat/model path
  -> persist final assistant turn
```

`ReasoningEngine` is **not** the deep reasoning system. It remains a compatibility classifier and retrieval-plan seam under `Data/modules/reasoning/`. `CognitiveRuntime` is the canonical orchestration authority.

## 6.2 CognitiveRuntime files

`Data/modules/cognition/` contains the cognitive state machine and supporting types. Important files include:

- `runtime.py` — submit/run/cancel/steer/status/events/resume;
- `task_model.py` — task model construction;
- `perception.py` — evidence/knowledge/memory/neuro perception;
- `belief_state.py` — confidence/support/contradiction state;
- `working_memory.py` — bounded current-run memory and pinned constraints;
- `meta_controller.py` — adaptive mode/strategy/budget selection;
- `planner.py` — structured plans with acceptance conditions;
- `action_selector.py` — value-based next action selection;
- `capability_broker.py` — capability shortlist/discovery;
- `context_v3.py` — cognition **profile adapter** over canonical `ContextBuilder` (not a second compiler);
- `completion.py` — typed acceptance criteria + evidence-based completion decisions (legacy string criteria remain compatibility-only / unverified when unsupported);
- `delegation.py` / `specialists.py` — agent/specialist delegation;
- `domain_strategy.py` — domain-specialized cognition without a second runtime;
- `experience.py` — VerifiedExperience/admission;
- `store.py` / hydration helpers — persistence/resume;
- `loop_detection.py`, `failure.py`, `steering.py`, `types.py`, `errors.py` — control-state machinery;
- `model_adapter.py` — bridge into the Model Control Plane.

## 6.3 Current reasoning modes

Current `ReasoningPolicy`/`MetaController` modes control **real orchestration budgets**:

| Mode | Wall | Model calls | Model tokens | Tools | Agents | Replans | Retries | Retrieval | Workers | Context | Critics | Iterations |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| FAST | 30s | 1 | 2,000 | 0 | 0 | 0 | 1 | 1 | 1 | 3,000 | 0 | 2 |
| STANDARD | 90s | 3 | 6,000 | 4 | 1 | 2 | 2 | 2 | 2 | 6,000 | 1 | 5 |
| DEEP | 180s | 6 | 12,000 | 8 | 2 | 3 | 3 | 3 | 3 | 8,000 | 2 | 8 |
| MAXIMUM | 300s | 10 | 20,000 | 12 | 3 | 4 | 4 | 4 | 4 | 12,000 | 3 | 12 |

`ADAPTIVE` can escalate/de-escalate from uncertainty, evidence coverage, contradiction density, failures, information gain and **measured** resource pressure (CPU/RAM/VRAM telemetry, queue depth, inflight model workloads — never a fake constant `0.0`).

### Two-axis compute (W3 CURRENT)

```text
ReasoningDepth = OrchestrationCompute + NeuralInferenceCompute
```

- **Orchestration** — `CognitiveBudgets` (retrieval rounds, critics, tools, agents, model calls, iterations).
- **Neural** — `NeuralComputeBudget` in `Data/modules/cognition/compute_axes.py` (reasoning effort, reasoning token allowance, candidate count, sampling, output allowance).

`MetaController` is the single policy owner for both axes. `MetaDecision` exposes `requested_mode`, `effective_mode`, `orchestration`, `neural`, and `resource_pressure`. FAST / STANDARD / DEEP / MAXIMUM differ measurably on both axes.

### Test-time compute (W4 CURRENT)

`Data/modules/cognition/ttc.py` owns candidate search when `neural.candidate_count > 1`:

- `Candidate` / `CandidateSet` — id, output, structured result, usage, hash, scores
- Scorers: Schema, Grounding, Consistency, Constraint, ToolGrounding, Integrity
- `IntegrityScorer` is **technical** only (injection boundary, unsupported capability claims, fabricated tool observations, secret leakage, authority confusion, schema) — not moral/political/ideological moderation
- Prune weak candidates; bounded repair with explicit verifier feedback
- Persist hashes/scores/public summaries/selected answer — not raw rejected private CoT

`CognitiveRuntime` applies TTC on RESPOND/MODEL_CALL when the neural axis budgets multiple candidates.

### Neural task advice + critic mesh (W5 CURRENT)

- `neural_advisor.py` — `NeuralTaskModelAdvisor` emits structured TaskAdvice; heuristic fallback is always labeled `heuristic_fallback`
- `hypotheses.py` — `HypothesisBoard` integrated into cognitive runs (support/contradiction/open questions)
- `critics.py` — Critic mesh (Process, Factual, Plan, Integrity, Code, Consistency); critic output is **not** verification proof and cannot authorize side effects
- Integrity critics remain technical-only (no ideological content layer)

### Async cognition resume / steering (W7 CURRENT)

- Durable checkpoints include plan, beliefs, working memory, budgets, neural axis, hypotheses, evidence refs, public events, pinned constraints
- `steer` supports goal_change / constraint_add / correction / status_request (program aliases)
- Pinned constraints re-applied on hydrate so compaction cannot drop them
- API: `/api/cognition/runs/{id}/steer`, `/resume`, `/cancel`, `/events` — no raw CoT exposure
- FAST may stay inline; DEEP/MAXIMUM remain budgeted for external-worker paths via JobRuntime when bound

### Frontier Reasoning target — not yet a current-main claim

The active master program continues beyond W7 into Brain/memory unification, agent recursion governance, coding/research expert systems, training/evaluation, trading lab, frontend, browser, multimodal, voice, and operations waves. Remaining items are **TARGET** until merged and verified.

---

# 7. Context, authority and prompt trust

## 7.1 Canonical context system

`Data/modules/context/` contains:

- `builder.py` — canonical context compilation for normal model paths;
- `reference.py` — untrusted reference serialization/escaping;
- `budget.py`, `fit.py`, `tokenization.py` — token budgeting;
- `compaction.py`, `hierarchical_compaction.py` — context reduction;
- `bounded_cache.py`, `cache_policy.py`, `singleflight.py` — efficiency/cache controls;
- `snapshots.py`, `fingerprints.py` — deterministic context identity;
- `multimodal.py` — multimodal session/parts;
- `types.py` — ContextPack/section types.

Cognition uses `Data/modules/cognition/context_v3.py` as a **thin adapter**: TaskModel / perception / beliefs / plan map into `ContextBuilder.build()` inputs. There is one compilation implementation.

## 7.2 Context authority (W1 CURRENT)

`ContextBuilder` is the sole compiler. Instruction authority contains BehaviorProfile identity, pinned constraints, and trusted runtime contract only.

Retrieved Knowledge, Memory, Evidence, web/tool/MCP/browser content, and Neuro associations remain **DATA** (reference_context / typed sections on the conversation path). They must not elevate into system authority.

Invariants covered by tests:

- prompt-injection payloads in knowledge stay out of `system_prompt` but remain available as data;
- latest user turn is pinned and cannot disappear because the same string appeared earlier;
- large retrieval degrades per-item under token budget (not one atomic all-or-nothing block);
- BehaviorProfile / response language apply per operation via overlays (hot-apply / cross-process freshness owned by settings);
- packs carry context fingerprints / snapshot identity.

Epistemic trust labels (`KNOWLEDGE_SOURCE`, `EVIDENCE`, `TOOL_OBSERVATION`, `NEURAL_ASSOCIATION`, …) remain for model-facing DATA classification — not system instruction elevation.

---

# 8. Brain, Knowledge/RAG, Atlas and Deep Recall

## 8.1 Brain

`Data/modules/brain/` is the **single Brain access facade**, not a second storage engine:

- `access.py` — access contracts/helpers;
- `contracts.py` — Brain-facing data contracts;
- `facade.py` — unified querying across knowledge, memory, evidence, experience and capabilities.

`main.py` constructs `BrainAccessFacade` over the canonical stores and binds it onto `PerceptionService` (W8). When Brain is bound, Perception gathers Knowledge/Memory/Evidence through Brain first and does **not** bypass Brain with private store calls.

## 8.2 Knowledge/RAG

`Data/modules/knowledge/` owns documents and retrieval. Important files:

- `store.py`, `types.py` — persistent documents/chunks/provenance;
- `retrieval.py` — hybrid lexical+dense retrieval;
- `staged_retrieval.py` — staged retrieval and deeper recall policy;
- `embeddings.py` — embedding provider interface/implementations;
- `deep_recall.py` — deep recall service;
- `atlas.py` — Atlas interpretation store;
- `why_library.py` — Why Library;
- `economy.py` — cognitive retrieval economy/budgets;
- `chunking.py`, `hashing.py`, `index_generations.py` — ingest/index mechanics;
- `pipeline/artifact.py`, `pipeline/curator.py`, `pipeline/committer.py` — knowledge preparation/commit path.

Current behavior is RAG/Brain-based evidence acquisition with provenance and retrieval gating. Retrieved text must never itself become execution or system authority.

---

# 9. Memory

`Data/modules/memory/` owns **durable scoped memory**:

- `store.py` — persistence/search;
- `types.py` — kinds, scopes, states and contracts;
- `consolidation.py` — episodic → semantic candidates with provenance (W8).

Explicit trust states (`MemoryTrustState`):

`AGENT_PROPOSED` · `USER_STATED` · `SOURCE_DERIVED` · `VERIFIED` · `CONFLICTED` · `REVOKED`

LLM confidence never becomes memory truth. Consolidation may admit semantic candidates as `AGENT_PROPOSED` until verification. Procedural skills derived from repeated VERIFIED cognition runs live in `cognition/skills.py` (`SkillLibrary`) — no hidden CoT.

**A08 / W08 preference correction:** `MemoryStore.correct_preference` is the canonical write path when a user corrects an earlier stored preference. It persists a new `PREFERENCE` row, marks prior matching `PREFERENCE`/`FACT` rows (`preference_key` / tags) as `SUPERSEDED`, and leaves retrieval on ACTIVE-only so the current preference wins. No parallel preference store — BehaviorProfile remains conversational identity/settings; durable user preferences live here.

Keep these concepts separate:

1. conversation history;
2. cognition `WorkingMemory`;
3. durable MemoryStore;
4. Brain/Knowledge documents;
5. VerifiedExperience;
6. SkillLibrary (procedural, measured success rate).

They may be combined in perception/context, but they are not the same storage or trust class.

---

# 10. Neuro / Cortex

`Data/modules/neuro/` remains part of the architecture and is **advisory**, not factual authority.

Current files/components include:

- `advisor.py` — NeuroAdvisor integration;
- `cortex.py`, `cortex_runtime.py` — bounded cortex planning/runtime;
- `critic.py` — process critic;
- `memory_tiers.py` — neuro-facing memory tiers;
- `residual.py`, `residual_orchestrator.py` — residual adapter/runtime boundary;
- `receipts.py` — residual receipts;
- `snapshots.py` — neuro snapshots;
- `adapters.py`, `types.py` — contracts;
- `soak.py` — soak harness;
- `echo_module.py`, `module.json` — module integration.

`main.py` wires residual runtime, NeuroMemoryFacade, ContrastiveRetrievalHead, ProcessCritic, CortexRuntime, CortexPlanner and NeuroAdvisor. Neural associations can influence retrieval, hypotheses and planning but do not automatically become exact facts or permission.

---

# 11. Model Control Plane and model runtime

## 11.1 Model Control Plane — `Data/modules/models/`

The Model Control Plane is the only model routing/residency owner. Key files:

- `control_plane.py` — top-level model control API;
- `inference_session.py` — canonical inference session;
- `registry.py`, `store.py`, `contracts.py` — model/provider registry state;
- `router.py`, `measured_routing.py` — routing decisions;
- `gateway.py` — inflight/queue/error accounting;
- `residency.py`, `resource_manager.py`, `placement.py` — physical placement/resource truth;
- `runtime_manager.py`, `runtime_binding.py`, `worker_client.py` — runtime lifecycle/worker bridge;
- `profiles.py` — persisted model profiles;
- `capability_probe.py`, `vision.py`, `efficiency_capabilities.py` — capability truth (probes measure behavior; config alone never upgrades to SUPPORTED);
- `downloads.py`, `import_service.py` — model acquisition/import;
- `benchmarks.py` — model benchmark support;
- `providers/` — LM Studio, Ollama, OpenAI-compatible, llama.cpp boundary, vLLM-class/base adapters.

`ModelCapabilities` includes frontier transport fields (`toolCalling`, `parallelToolCalls`, `jsonSchemaResponse`, `reasoningEffort`, `logprobs`, `streamingToolDeltas`, `multiCandidate`, …) with honest `supported` / `unsupported` / `unmeasured` / `unknown` / `unverified` states.

Routing and model selection are not permission grants. Model state is reconciled with actual runtime discovery.

Do **not** abbreviate Model Control Plane as MCP — in this repository MCP means Model Context Protocol.

## 11.2 Model runtime — `Data/modules/model_runtime/`

Provider-facing execution lives here:

- `openai_compatible.py` — OpenAI-compatible chat/completion client (frontier transport options: tools, response_format, logprobs, n/candidates, …);
- `dialect.py` — provider dialect adaptation; requested capabilities are never silently dropped (`SUPPORTED` / `UNSUPPORTED` / `UNMEASURED`);
- `inference_contract.py` — W04 inference contract: tool-calling probe/record, structured/json_schema repair-or-`UNAVAILABLE`, context refuse/truncate with explicit signal;
- `serving.py` — serving supervisor/cancellation;
- `streaming.py` — stream normalization with separated `content` / `reasoning` / `tool` channels (partial separation is labeled honestly);
- `managed_adapter.py`, `launch_strategy.py`, `process_control.py`, `port_allocator.py`, `llama_cpp_command.py` — managed serving boundaries;
- `durable_requests.py`, `latency.py` — request/latency support.

`Data/modules/cognition/model_adapter.py` bridges CognitiveRuntime to `ModelControlPlane.inference_session`; cognition must not call an independent private model client.

**W04 inference contract (CURRENT):** Requested tools must appear in the provider payload or be recorded as rejected — never silently omitted (`TOOL_CALLING_DROPPED` if marked SUPPORTED but absent). `response_format` / `json_schema` responses are deterministically repaired (fence strip, span extract, trailing commas) then schema-validated; failure is `STRUCTURED_RESPONSE_UNAVAILABLE` — never a pretended structured success. Streaming keeps reasoning on `reasoning_delta` frames and tool calls on `tool_delta` frames; content reduction ignores reasoning. Context overflow either refuses (`CONTEXT_WINDOW_EXCEEDED`) or truncates with `CONTEXT_TRUNCATED` and an explicit `context_bound` signal.

---

# 12. Execution, functions, approvals and capability truth

## 12.1 Execution world

`Data/modules/execution/`:

- `catalog.py` — capability catalog;
- `gateway.py` — single side-effect boundary;
- `builtins.py` — built-in capability definitions;
- `manifest.py`, `metadata.py` — capability metadata/manifests;
- `receipts.py` — durable execution receipts;
- `types.py` — request/result/risk contracts.

`ExecutionGateway` mediates tools, files, knowledge, artifacts, browser, MCP, media and voice where configured. A model saying an action happened is not proof; receipts/observations are the truth boundary.

## 12.2 Function runtime

`Data/modules/function_runtime/` owns cold-path function registration/execution (`registry.py`, `runtime.py`, `builtins.py`, `types.py`). Physical functions live under `Data/functions/`:

- `text_file_read/`
- `text_file_write/`
- `text_file_patch/`
- `text_file_delete/`
- `workspace_list/`
- `workspace_search/`
- `coding_run_tests/`
- `git_status/`
- `git_diff/`
- `csv_inspector/`
- `pdf_parser/`
- `numeric_compute/`

## 12.3 Approvals / authority

`Data/modules/approvals/`:

- `authority.py` — technical authority profile;
- `policy.py` — policy engine;
- `service.py` — approval orchestration;
- `store.py`, `types.py` — durable approval state.

BehaviorProfile is **not** AuthorityProfile. Side effects that require approval cannot be granted merely by model text.

---

# 13. Jobs and external workers

## 13.1 Jobs

`Data/modules/jobs/` contains durable schedulable work:

- `runtime.py`, `store.py`, `states.py`, `types.py`;
- `leases.py`, `retry.py`, `priority.py`;
- `budgets.py`, `resources.py`.

## 13.2 External worker system

`Data/modules/workers/` provides external process execution and admission:

- `bootstrap.py`, `process.py`, `supervisor.py`, `loop.py`;
- `registry.py`, `pools.py`, `protocol.py`, `settings.py`;
- `admission.py`, `sqlite_support.py` (re-exports canonical `sqlite_policy`);
- `events.py` — centralized worker terminal observability (`WorkerEventEmitter`);
- `entrypoints/` for domain-specific processes;
- `Data/modules/db_commit/` — DB Commit Coordinator (serialized `COMMIT_WRITE`).

Current entrypoint families include agents, backup, coding, dataset, document AI, embeddings, evaluation, general jobs, knowledge prepare, **db_commit** (canonical bulk writer; knowledge_commit is a deprecated compatibility shim with desired=0), maintenance, market simulation, MCP execution, model downloads, provider I/O, reranking, research, scheduler, source ingestion, telemetry, training control and workflows.

Architecture rule: the FastAPI/chat process is the **control plane**; long I/O/CPU/GPU work must be externalized through JobRuntime/workers.

**Production defaults (CURRENT):**
- `workers.enabled` / `supervisor_enabled` / `externalize_api_runners` = ON
- Dataset / source-ingestion runners = `external` (inprocess is TEST/LEGACY only)
- Agents / Coding / Signal Fabric / Reasoning = ON
- `network.allow_outbound` = ON (SSRF, private-network, and ExecutionGateway restrictions still apply)
- Canonical launcher: `run_leviathan_workers.bat` → one consolidated supervisor terminal for **all** pools
- Operator read-model: `GET /api/workers/dashboard` (+ `/api/workers/{id}`) — pools + workers + job join + progress + resources
- Agents page → **Worker Fabric** monitor consumes that dashboard (never agentCount as “Active Workers”)
- Process topology: API = control plane; WorkerSupervisor = spawn/lease/restart/drain; specialist workers = one OS process per slot; model serving remains a separate residency plane

Pool catalog (CURRENT shape): ~25 pools; optional/FEATURE_GATED include `rerank`, `document_ai`, `telemetry`; legacy `knowledge_commit` desired=0 (db_commit owns bulk writes).

When externalization is enabled, worker unavailable → durable queued/failed/`WORKER_UNAVAILABLE` — **never** silent synchronous heavy fallback inside FastAPI.

### Control Plane vs Execution Plane

| Plane | Owns | Must not own |
| --- | --- | --- |
| Control Plane (API/main) | routing, validation, auth/policy, job enqueue/cancel/status, SSE, lightweight metadata | PDF/archive parse, bulk embedding, research runs, dataset transforms, training, evaluation suites, unbounded network fetch |
| Execution Plane (WorkerSupervisor pools) | durable job claim/execute for heavy work | control-plane routing / approvals |

### Workload classification (`Data/modules/execution/workload.py`)

Capabilities declare an `execution_class` in metadata:

- `INLINE_SAFE` — small/bounded; may run in API
- `EXTERNAL_PREFERRED` — prefer workers when available
- `EXTERNAL_REQUIRED` — must not run heavy implementation in API when `LEVIATHAN_WORKERS_EXTERNALIZE_API=true`

`ExecutionGateway` rejects inline API execution of `EXTERNAL_REQUIRED` with `worker_required` (honest `WORKER_UNAVAILABLE` / enqueue path). Worker processes (`LEVIATHAN_WORKER_ID`) and explicit developer mode (`LEVIATHAN_WORKERS_EXTERNALIZE_API=false`) remain exempt. Classification never bypasses authorization.

### Terminal observability

Worker lifecycle uses one emitter → human terminal lines + structured logs:

- `[LEVIATHAN] Control Plane gestart`
- `[JOB] Research '…' ingepland — job ab12cd34` (enqueue; not yet started)
- `[WORKER] research pool gestart — 2 workers` (after processes are owned)
- `[WORKER:research-1] Research '…' gestart` (after claim/begin)
- completion/failure with duration and safe error codes

Labels come from allowlisted metadata (topic/filename/dataset name); secrets and document bodies are never printed.

DB Commit Coordinator terminal channel:

- `[WORKER] DB Commit pool gestart — 1 worker`
- `[DB-WRITER] Research '…' commit ingepland — N records` (queued ≠ started)
- `[DB-WRITER] … commit gestart` / `voltooid — N records — …ms`
- retries (`SQLITE_BUSY`), quarantine (`PAYLOAD_HASH_MISMATCH`), shutdown (`writer stopt — pending=N`)

---

### Fallback policy

When externalization is enabled, worker unavailable → durable queued/failed/`WORKER_UNAVAILABLE` — **never** silent synchronous heavy fallback inside FastAPI.

### Knowledge / Research control-plane rules (W3–W4)

- Public `POST /api/knowledge` stages content (`INDEXING`) and enqueues `knowledge.prepare`; chunking/embedding run on `knowledge_prepare` workers.
- `KnowledgeStore.initialize()` is **schema-only**. Legacy content backfill is a resumable `knowledge.prepare` (`action=backfill`) job (`KNOWLEDGE_BACKFILL_PENDING`).
- ModelData / neuro absorb scans enqueue `knowledge.ingest_scan` on the prepare pool.
- Research URL add validates SSRF shape in API, creates `PENDING` source, enqueues `research.fetch_url`.
- Report regeneration enqueues `research.report.generate`.
- Brain retry enqueues `source_ingestion.brain_retry` (no sync `upsert_document` on the API thread).
- When externalized, missing Source Ingestion returns `SOURCE_INGESTION_UNAVAILABLE` — never legacy `UploadIngestor` PDF parse in FastAPI.
- Cognition research delegation uses `background=True` / durable enqueue (WAITING), not sync deep research on the chat thread.
- Training cancel returns promptly (`wait_seconds=0`); log reads use bounded tail I/O.
- Artifact hash verification streams from disk.

---

# 14. Agents, coding and research

## 14.1 Agent system — `Data/modules/agents/`

Files include:

- `runtime.py` — AgentRuntime;
- `fleet.py`, `fleet_types.py`, `store.py` — AgentFleet;
- `governance.py` — DelegationGovernor (W9): depth, cycle detection, authority inheritance, child budget from parent;
- `planner.py` — structured agent planning;
- `multi.py` — DAG multi-agent coordination;
- `blackboard.py` — shared agent result state;
- `system_inventory.py` — truthful runtime component inventory;
- `types.py` — contracts;
- `signals/` — Signal Fabric for durable async coordination (not all sync subresults).

CognitiveRuntime may delegate via `DelegationService`, but parent cognition remains orchestration authority.

W9 governance invariants:

- `parent_run_id`, `delegation_depth`, `max_delegation_depth` on every hop;
- child authority ≤ parent authority (`clamp_authority`);
- child compute budget derived from remaining parent budget;
- lineage cycle detection blocks Cognition→Agent→Cognition→same-Agent recursion;
- agent memory: `AGENT_PRIVATE` plus optional `ORCHESTRATOR_SHARED` scope.

## 14.2 Coding — `Data/modules/coding/`

Coding is a dedicated specialist control plane, not a second general assistant. Important files:

`service.py`, `loop.py`, `worker.py`, `planner.py`, `cognition.py`, `llm_adapter.py`, `parser.py`, `prompts.py`, `workspace.py`, `tools.py`, `patch.py`, `transaction.py`, `verify.py`, `review.py`, `semantic_map.py`, `store.py`, `types.py`.

Writes/executes remain capability/approval gated; tests and receipts are used for verification.

W10 hardening:

- Native provider tool_calls preferred when offered (`CodingLLMAdapter` + `capabilities_from_native_tool_calls`); text XML/JSON is fallback only.
- Repo semantic map injected into loop context as advisory DATA.
- Workspace snapshots before mutating writes; restore on verify/test failure.
- Any completed write requires `coding.run_tests` evidence before COMPLETED (no "fixed" without tests).
- Post-write `StepKind.CRITIC` with structured `HunkReview` findings.

## 14.3 Research — `Data/modules/research/`

Research supports local evidence and optional outbound/web sources:

`service.py`, `runner.py`, `worker.py`, `worker_context.py`, `planner.py`, `coordinator.py`, `question_model.py`, `sources.py`, `source_quality.py`, `web.py`, `ssrf.py`, `uploads.py`, `local_retrieval.py`, `claims.py`, `evidence.py`, `conflicts.py`, `citation_audit.py`, `coverage.py`, `gaps.py`, `graph.py`, `reports.py`, `quality_scorecard.py`, `brain_sync.py`, `assignments.py`, `budgets.py`, `store.py`, `types.py`.

Important truth: outbound network permission and a configured web-search provider are separate conditions. Research must not fabricate browsing.

W10 web policy:

- Real `robots.txt` enforcement when `respect_robots_txt=True` (refuse Disallow).
- Per-host rate limiting + Retry-After honor.
- Readability extraction prefers `article`/`main`/paragraph clusters.
- `published_at` extracted from HTML meta when present; citation resolution includes `location`.
- Long Research remains external-first via cognition specialists (`background=True`).

---

# 15. Datasets, source ingestion and document extraction

## 15.1 Dataset system — `Data/modules/datasets/`

Dataset lifecycle covers ingest, validation, canonicalization, dedupe, PII/contamination checks, split/mixture manifests, indexing and training export.

Key files include:

`service.py`, `store.py`, `types.py`, `formats.py`, `importers.py`, `huggingface.py`, `offline.py`, `materialize.py`, `shards.py`, `validation.py`, `quality.py`, `canonicalize.py`, `dedupe.py`, `pii.py`, `contamination.py`, `splits.py`, `mixtures.py`, `packing_sim.py`, `tokenize_stats.py`, `indexing.py`, `relations.py`, `transforms.py`, `annotation.py`, `export.py`, `jobs.py`, `worker.py`, `sidecar.py`.

## 15.2 Source ingestion — `Data/modules/source_ingestion/`

Files include `service.py`, `pipeline.py`, `worker.py`, `store.py`, `types.py`, `settings.py`, `detection.py`, `handlers.py`, `skip_policy.py`, `secrets_policy.py` and archive/safety helpers. Uploaded/registered sources can feed knowledge/dataset workflows according to policy.

## 15.3 Documents — `Data/modules/documents/`

Document extraction/parsing support lives here and is used by ingestion/capability flows.

---

# 16. Training, post-training, evaluation and verified learning

## 16.1 Training — `Data/modules/training/`

Current infrastructure includes:

- service/store/registry/planner/preflight/recovery;
- recipes and launch/hardware/capability checks;
- SFT data preparation;
- preference schema/store/bridge and DPO infrastructure;
- active-learning and synthetic-data components;
- integrity/lineage/model registration;
- candidate promotion/flywheel boundary;
- worker entry/trainer loop and neuro worker.

Files include `service.py`, `store.py`, `registry.py`, `recipes.py`, `planner.py`, `preflight.py`, `launcher.py`, `hardware.py`, `capabilities.py`, `config.py`, `events.py`, `recovery.py`, `artifacts.py`, `integrity.py`, `lineage.py`, `model_registration.py`, `sft_data.py`, `preference_schema.py`, `preference_store.py`, `preferences.py`, `dpo.py`, `active_learning.py`, `synthetic.py`, `promotion.py`, `evaluation.py`, `neuro_worker.py`, `types.py`, and `worker/`.

Do not infer that every recipe is production GPU-ready on every machine. Availability is provider/hardware/config dependent. Candidate promotion is explicit; silent active-model replacement is not the architecture.

W11 learning flywheel (CURRENT):

- `ExperienceStore.aggregate_stats` / `search` — admitted-only training truth rollups.
- Active-learning kinds cover verification failure, low TTC agreement, user correction, critic high severity, tool failure patterns, retrieval miss (`training/active_learning.py`).
- Lifecycle: `CANDIDATE → EVALUATED → ELIGIBLE → PROMOTED` via govern (never auto-promote).
- `trajectory_export.export_training_trajectory` — public states/messages/answer/verified only; no private CoT.
- GRPO / RL / reward-model / HF-DPO reported as `FEATURE_GATED` until operational trainers exist.

## 16.2 Evaluation — `Data/modules/evaluation/`

`harness.py`, `platform.py`, `store.py`, `types.py`, `scorecard.py`, `paired.py`, `compute_paired.py`, `judge_calibration.py`, `ablations.py`, `assistant_benchmark.py` implement evaluation/reporting. `UNMEASURED` is not treated as PASS.

W12 CURRENT:

- Paired compute FAST vs DEEP uses bootstrap of paired quality deltas (`compute_paired.py`); DEEP need not beat FAST on every easy task; hard suites require mean delta ≥ min useful effect with CI lower bound > 0.
- LLM judge calibration (`judge_calibration.py`): below reliability threshold → `UNMEASURED`.
- Assistant benchmark families include reasoning, prompt-injection resistance, language following, browser, multimodal honesty, trading live-block, research grounding.

## 16.3 VerifiedExperience

`Data/modules/cognition/experience.py` admits only sufficiently verified/eligible experience. Current Frontier Reasoning target extends this with aggregate statistics, active-learning capture and structured training trajectories. Raw hidden chain-of-thought must not become training truth.

---

# 17. Evidence, observations, verification and artifacts

- `Data/modules/evidence/` — evidence store/service/types;
- `Data/modules/observations/` — durable observations;
- `Data/modules/verification/` — verification engine/report store/types;
  - tiers (W6): `DETERMINISTIC_VERIFICATION`, `CROSS_MODEL_VERIFICATION`, `SELF_CRITIQUE` — same-model critique is never labelled independent verification;
  - `capability_state.py` — `SystemCapabilityState` self-knowledge (available capabilities, workers, web/browser/network, GPU when measured; brain percentage stays UNMEASURED);
- `Data/modules/artifacts/` — artifact store/types/validation.

System invariant:

```text
model output != observation
request != authority
execution request != successful effect
model says done != verified completion
SELF_CRITIQUE != CROSS_MODEL_VERIFICATION
UNMEASURED != PASS
exit_code=0 alone != tests passed
source ref alone != claim supported
```

**Typed completion (W03 CURRENT):** `TaskModel.acceptance_criteria` carry criterion IDs, verifier kind, scope, expected artifact/effect, and required evidence. `CompletionEngine` publishes per-criterion `verification_status` (`supported` / `contradicted` / `insufficient_evidence` / `unavailable_verifier` / `failed_execution` / `unverified`). Only `supported` counts as met.

---

# 18. MCP, plugins and module manager

## MCP — `Data/modules/mcp/`

One bridge handles supported MCP sessions and synchronizes tools into the canonical capability catalog. Files include `bridge.py`, `provider.py`, `session.py`, `execution.py`, `catalog_sync.py`, `module_integration.py`, `policy.py`, `limits.py`, `secrets.py`, `store.py`, `protocol.py`, `transports/`, `types.py`, `errors.py`.

MCP invocation still passes through `ExecutionGateway`; MCP is not a private side-effect channel.

## Plugins — `Data/modules/plugins/`

`registry.py`, `types.py` manage plugin registration/capability exposure.

## Module manager — `Data/modules/module_manager/`

`manager.py`, `discovery.py`, `subprocess_exec.py`, `types.py` own dynamic module discovery/lifecycle and optional subprocess isolation.

---

# 19. Browser, media, voice and multimodal

- `Data/modules/browser/` — local DOM/Playwright boundary, worker and honest stub;
- `Data/modules/media/` — media service/stub and artifact integration;
- `Data/modules/voice/` — realtime voice service/stub;
- `Data/modules/context/multimodal.py` — multimodal session/part contracts.

These paths are FEATURE-GATED and backend/provider availability must be reported honestly. Existence of a boundary does not imply universal production browser, speech or media-generation support.

### General Assistant Fabric (GI)

LEVIATHAN integrates existing owners into one assistant path — **not** a second ChatRuntime:

- **CognitiveRuntime** (`Data/modules/cognition/`) remains the sole cognitive orchestration authority. Adaptive `TaskModel.execution_class` selects DIRECT / CONTEXTUAL / TOOL_REQUIRED / CURRENT_INFO / COMPLEX_REASONING / MULTI_DOMAIN / VERIFICATION_REQUIRED / WORK.
- **BehaviorProfile** owns conversational behavior (`SYSTEM_PROMPT`). **AuthorityProfile** / **ExecutionGateway** own technical side effects. They must never merge.
- **system.inspect** aggregates real provider telemetry; brain percentage is explicitly UNMEASURED (not a metric).
- **FactualityGate** / claim assessment live under `Data/modules/verification/claims.py`. Fake critic `evidence_refs` cannot PASS.
- **web.search** / **web.fetch** route through `Data/modules/research/web.py` providers. Unconfigured search returns `WEB_SEARCH_UNAVAILABLE` — never fabricates results.
- **General Intelligence Orchestra** seeds live in AgentFleet (`Data/modules/agents/general_orchestra.py`). Parent Cognition owns the final voice.
- **PlaywrightBrowserBackend** is READY only after Chromium launch + navigate + observation proof.
- **BrowserJourneyCrawler** / `LocalUserJourneyCrawler` (`Data/modules/browser/qa_crawler.py`) is localhost-scoped QA; APIs under `/api/browser/qa/*` (gateway) and thin `/api/browser/qa/crawls*` router. No CrawlerRuntime2 / stealth.
- **QaRepairBridge** (`Data/modules/browser/qa_repair.py`) is an optional operator-triggered finding → `CodingCognitiveStrategy` → tests/replay path; never marks fixed without evidence.
- Chat returns `assistant_telemetry` assembled from cognition public status (tool_calls with receipts/duration, agent_delegations, web_sources, context budget/used, behavior hash/version, latency). No hidden CoT.

### Capability contract (CURRENT)

`CapabilityCatalog` (`Data/modules/execution/`) is the sole executable capability registry. Declared/planned capability ids in coding prompts, coding tool gates, cognition planner `likely_capabilities`, AgentFleet seeds, and `EXTERNAL_WORKER_CAPABILITIES` must be ⊆ catalog (`Data/backend/tests/test_capability_contract_drift.py`).

- Fictional prompt ids (`git.commit`, `coding.run_command`) are rejected — not registered.
- Real worker aliases registered: `knowledge.ingest_document`, `knowledge.ingest_path`, `rerank.batch` (FEATURE_GATED pool), `market_sim.mandate.loosen` (approval identity).
- Trading role labels (`market_sim.observe`, …) and agent inventory abstracts remain descriptors, not gateway capabilities.

### Behavior / Chat integrity (CURRENT)

- Behavior identity is BehaviorProfile → immutable BehaviorSnapshot per turn (`Data/modules/settings/`); ContextBuilder must not invent a second identity.
- Language follows the latest user turn when configured (`auto_follow_user`).
- Retrieved Knowledge/Memory/Evidence/Web/tool output remain **DATA**, never system instruction authority.
- Stream frames are snapshot-safe (no cumulative `message.content` appended as deltas).
- Heavy domain work stays on JobRuntime/workers; Chat/model stream stays on the Model Control Plane by design.

---

# 20. Market Simulation / TradingCenter

`Data/modules/market_sim/` is the current trading research/simulation owner. It includes:

- market/data models: `ohlcv.py`, `data_store.py`, `dataset_pipeline.py`, `instruments.py`, providers;
- causality / epistemic time: `causality.py` (`SimulationClock`, `MarketView`), `epistemic.py` (`EpistemicFirewall`, `available_at <= as_of`);
- market state / features (T2): `features.py` (deterministic OHLCV indicator library + provenance), `market_state.py` (`MarketState`, `MultiTimeframeView`, causal higher-TF aggregation);
- reproducibility: `knowledge_snapshot.py` (`TradingKnowledgeSnapshot` persisted per run);
- engine: `engine.py` (WalletLedger + RiskGuard + NextBarFillModel), `multi_engine.py`, `fill_model.py` (legacy shim), `execution.py` (TIF / Limit / Stop / IntrabarPathPolicy; prepare verifies `data_hash`; multi-agent rounds attach `MarketState`);
- accounting/risk: `accounting.py` (W13 multi-symbol WalletBook), `portfolio.py`, `risk_guard.py`, `trading_live_guard.py`;
- data realism (W13): `universe.py` (PIT membership), `costs.py` (CostModelPack provenance), `stats_inferential.py` (DSR/PBO/FDR/bootstrap/CPCV geometry);
- strategy governance (W14): `strategy_asset.py`, `strategy_dsl.py` (v3), `regimes.py`, `hpo.py`, `curriculum.py`;
- agent lab (W15): `agent_lab.py` (scientific search / tournaments / lesson trust);
- paper ops (W16): `paper_deployment.py`;
- strategies/experiments: `strategy_eval.py`, `experiments.py`, `metrics.py` (`resolve_periods_per_year`), `position_episodes.py` (`ClosedTrade` / `PositionEpisodeTracker`);
- multi-agent hooks: `roles.py`, `deliberation.py`, `commit_reveal.py`, `brain_hooks.py` (as_of / firewall filtering);
- paper path: `paper_broker.py`;
- service/store/worker/types/capabilities;
- `orchestra/` — trading-only orchestration on the existing Agent Fleet and Model Control Plane.

**T1 (causality + data foundation):** historical agents observe markets through `MarketView`; information sources must respect `available_at <= simulation as_of`; sealed market dataset versions are content-addressed and immutable (corrections create a new version); every run stores a `TradingKnowledgeSnapshot`.

**T2 (market state + features):** `FeatureEngine` computes causal SMA/EMA/RSI/ATR/ADX/Bollinger/z-score/ROC/realized-vol/Donchian/VWAP/volume/breakout/slope/drawdown/correlation/beta/relative-strength with measured/insufficient/not-implemented status and provenance. `MarketState` packages deterministic price/trend/momentum/volatility/volume/structure/regime fields (neural interpretation excluded). Multi-timeframe views synthesize higher TFs from visible base bars only. OHLCV never claims order-book imbalance. Live broker/real-money execution remains blocked.

**P0A (kernel honesty):** `SimFill` carries measured honesty fields (`realized_delta`, `remaining_qty`, `order_type`, `fill_price_source`, `observed_execution`, `decision_bar_index`, `intent_id`, `trade_id`) — unmeasured fields are omitted from `public_dict`. `ClosedTrade` / `PositionEpisode` (`position_episodes.py`) is the foundation for closed-trade win rate; fill-level win rate is separately labeled and must not be conflated. `resolve_periods_per_year` annualizes Sharpe/Sortino via instrument calendar → observed frequency → asset-family default → timeframe fallback (crypto 1h ≠ equity 1h); unresolved annualization yields UNMEASURED. `evaluate_acceptance` reads `compute_metrics` keys (`trade_count`, `total_return`/`total_return_pct`, `max_drawdown`/`max_drawdown_pct`). Migration 45 persists honesty fill columns and `market_sim_closed_trades`.

**P0D (resume/determinism/leases):** Three hashes — `RunInputFingerprint` (immutable), `CheckpointStateHash` (per checkpoint), `TrajectoryHash` (trajectory). `SimulationEngine` records fingerprints/checkpoints; multi-engine `prepare` restores `wallet_snapshot` when `bar_index > 0` (no cash rewind). Soft leases: `heartbeat_run_lease` / `expire_stale_leases` (migration 46). WalletLedger rejects duplicate `tx_id` and exposes `assert_invariants`. G08–G11 PASS. P0 complete.

**P0C (risk/sizing/instruments):** `RiskGuard.on_bar_timestamp` resets `orders_today` on UTC day change. Explicit `SizingModel` on `SimRun.sizingModel`. Instrument lot/tick/min_notional. Shorts require `ShortMarginPolicy`. G10 PASS.

**P1A (streaming + splits + SEALED attempts):** Canonical `iter_ohlcv` / `stream_ohlcv` stream CSV/Parquet without materializing the series (G01). `DatasetSplitManifest` (`split_manifest.py`) builds chronological TRAIN/VAL/SEALED windows with optional `embargo_bars`; sealing a dataset freezes the manifest (G06). `SealedAttemptBinder` binds `sealed_attempt_id` + `run_id` on first SEALED exposure; crash/resume keeps the same attempt and checkpoint (never rewind); COMPLETED is single-use (`SEALED_ALREADY_CONSUMED`). Migration 47. G13/G21 IN_PROGRESS (absolute 5y soak + acceptance-from-run-IDs remain later).

**P1B (TradingGym + API + worker):** `TradingGym` (`gym.py`) provides causal `reset`/`step` with observations via `MarketView` (G26 PASS). Interactive episodes may step in the control plane; **complete** episodes are `EXTERNAL_REQUIRED` (`market_sim.gym_episode`) on the market_sim worker — FastAPI refuses sync fallback with `TRADING_WORKER_UNAVAILABLE`. Routes under `/api/market-sim/gym/episodes`.

**P1C (trajectory + RewardSpec + dataset bridge):** Canonical `RewardSpec` (`reward.py`) computes kernel-derived step rewards (`equity_delta`, `log_return`, `realized_pnl_delta`, sparse `episode_total_return`); unknown defs stay UNMEASURED. `TrajectoryBuilder` / `TrajectoryArtifact` (`trajectory.py`) seal content-addressed gym step streams; `dataset_bridge.export_trajectory_to_dataset` writes JSONL under markets `.artifacts` and registers via DatasetService when bound (honest `FILE_ONLY` otherwise). G29 PASS.

**P2A (Strategy DSL v2):** `strategy_dsl.py` defines `StrategySpecV2` over `FeatureEngine` — kinds `breakout`, `rsi`, `feature_compare`, plus legacy `ma_cross` / `mean_reversion`, with `regime_filter` gating entries fail-closed. `evaluate_strategy` dispatches v2 kinds; no arbitrary code execution. G15 PASS.

**P2B (Trial Ledger + WFA + sealed acceptance):** Append-only `append_trial` / `count_trials`; `save_experiment` persists `strategy_version` (D14). `wfa.py` rolling WFA windows with purge gap; `walk_forward_splits` rolling overload (D13). `evaluate_acceptance_from_run` reads kernel `run.metrics` only (G21 PASS). G19 PASS; G20 IN_PROGRESS (CPCV later).

**P2C (sandbox + lineage + StrategyMemory):** Python code strategies are `FEATURE_GATED` / `NOT_AVAILABLE` (`code_strategy.py`) until an IsolationSandbox escape suite PASSes — AST filtering alone is insufficient; create/version reject `kind=python`. Immutable lineage via `strategy_lineage.py` (`parent_version`, `parent_content_hash`, `immutable`) on create/version (G17 PASS). `MultiAgentEngine.prepare` hydrates durable StrategyMemory from `list_strategy_memories(as_of_ts=run.start)` (G22 PASS, D15). G16 remains FEATURE_GATED (honest).

**P3A (orchestra cadence + async DecisionRecord):** `decision_cadence.py` owns explicit cadence gates (`every_n_bars` / `daily_close` / `hourly` / `event_driven` / `off`) and `AsyncDecisionQueue` (causal as_of eligibility, no rewind). `create_run` no longer injects a silent multi-agent roster (D31); cadence is recorded on run metadata. Engines consult `should_decide_on_bar`. Trading Orchestra registers `AgentDefinitionKind.TRADING` executors on Agent Fleet; append-only `DecisionRecord` chain (proposal→critique→risk→intent). `AgentKind.TRADING` labeled. G24 PASS.

**P3B (ResearchCampaign + causal Brain/Memory + A0–A4):** Durable `ResearchCampaign` (migration 48) with `checkpoint_iteration` resume; worker job `market_sim.research_campaign` is EXTERNAL_REQUIRED (`TRADING_WORKER_UNAVAILABLE` without JobRuntime). `BrainFacade.retrieve(as_of)` + StrategyMemory as_of (G23 PASS). Scorecards with violation penalties (G27 PASS). Readiness ladder A0–A4; A5/LIVE → `A5_IMPOSSIBLE`; promotion via kernel acceptance never enables live (G25/G28/G31 PASS).

**P4A (PaperForwardRunner + isolated paper + RiskGuard):** `LocalPaperBroker.wallet_for_session` isolates cash per paper session (D18). `PaperForwardRunner` + `paper_forward_step` / `paper_place_order` run every paper order through canonical `RiskGuard` (G32/G34 PASS). Live money remains BLOCKED.

**P4B (sim-to-paper gap + Gateway + leases):** `sim_to_paper_gap.measure_sim_to_paper_gap` reports honest MEASURED/UNMEASURED gaps (G33). `LiveBrokerAdapter` is UNSUPPORTED (G35). Market-sim mutation routes bind `ExecutionGateway` + `capability_catalog` (G37, D16). `claim_next_runnable` uses `BEGIN IMMEDIATE`; JobStore leases are canonical (G38, D25/D26). Contiguous migrations through 48 (G39).

**P4C (TradingCenter frontend real backend):** `SimulatiePage` exposes `initialCash` / `engine` / `decisionCadence`; default single-strategy with empty agents (D27). Paper/strategy pages call real APIs. G41/G42 PASS.

**W24 Final integration (CURRENT):** Backend lab/computer-use/multimodal/voice/security helpers covered by wave tests; frontend typecheck green on W18 surfaces; live trading BLOCKED; A5 IMPOSSIBLE; parallel runtimes created: NONE. Playwright E2E/MSW and full OS sandbox remain honest FEATURE_GATED / UNMEASURED where not measured.

**W23 Security / multi-user / ops (CURRENT):** `common/security_ops.py` auth posture + RBAC role vocabulary; unmeasured OS enforcement is not called secure; secrets-broker honesty; rate-limit/OTel FEATURE_GATED.

**W22 Automations / plugins / MCP / data analysis (CURRENT):** `execution/data_analysis.py` safe AST calculator + CSV summarize; MCP content untrusted; no AutomationRuntime2 (JobRuntime/schedules).

**W21 Voice (CURRENT):** `voice/transport.py` — voice is transport into Chat/CognitiveRuntime; ASR/TTS MEASURED/UNAVAILABLE/NOT_CONFIGURED honesty; no duplicate conversation memory.

**W20 Multimodal / documents (CURRENT):** `documents/intelligence.py` vision capability declaration + document structure refs; eval families FEATURE_GATED until measured; not an independent multimodal runtime.

**W19 Web / Browser / Computer-use (CURRENT):** Computer-use loop (`execution/computer_use.py`) enforces proposal→authority→execute→observe→verify; free-form OS text refused; click success ≠ task completion. Existing Playwright readiness, localhost QA crawler (no stealth), and QaRepairBridge retained. Web search unconfigured → WEB_SEARCH_UNAVAILABLE, never fabricated.

**W18 Frontend Platform (CURRENT):** ErrorBoundary + lazy trading routes; `api/http.ts` + `api/domains/marketSimLab.ts`; chat Stop abort; DEMO banners for decorative mocks; Playwright/MSW FEATURE_GATED until CI dependency.

**W17 Trading Center UI (CURRENT):** `/trading/lab` + `/api/market-sim/lab/overview|cost-pack|feed-health|trials` expose real lab truth (curriculum, roles, Trial Ledger, cost provenance, feed probe). Broker/live remains BLOCKED. No mock KPIs.

**W16 Trading Lab IV (CURRENT):** `paper_deployment.py` PaperDeployment with compatibility validation, environment fingerprint, feed health (staleness/gaps), kill switch, and modelled/shadow/paper gap comparison. Paper does not prove live profitability; LIVE BLOCKED; A5 impossible.

**W15 Trading Lab III (CURRENT):** `agent_lab.py` scientific search loop with pre-registered `AcceptanceCriteria` (threshold relaxation forbidden). Terminal outcomes `QUALIFIED_STRATEGY_FOUND` | `NO_STRATEGY_QUALIFIED` (valid PASS). Lessons default `AGENT_PROPOSED`; sealed lineage contamination refused; tournaments VAL-first with Elo that does not prove profitability; public trajectory→dataset bridge (no hidden CoT). Live BLOCKED; A5 impossible.

**T08 / W17 sealed rename inheritance:** `register_lineage_rename` / root lineage aliases keep sealed holdout exposure on the contamination root. Renamed or parent-lineage descendants still raise `HOLDOUT_LINEAGE_CONTAMINATED` for the same sealed dataset; a new holdout/version/epoch is required.

**W14 Trading Lab II (CURRENT):** `strategy_asset.py` StrategyAsset + ExecutionCompatibilityManifest (live_compatible always false; promotion requires evidence). DSL v3 extends `strategy_dsl.py` (stop/take-profit/trailing/time-stop/sizing/universe/session/portfolio; no eval/exec). `regimes.py` volatility/trend/correlation/changepoint + synthetic fixtures; HMM FEATURE_GATED. `hpo.py` grid/random/evolutionary with mandatory Trial Ledger; sealed tuning forbidden; Bayesian/TPE FEATURE_GATED. `curriculum.py` logged reproducible stage progression through sealed/paper.

**W13 Trading Lab I (CURRENT):** Point-in-time universe membership (`universe.py`: IPO/delist/rename/exchange events, corporate actions, session calendars, `DatasetRevisionIdentity`) — default `point_in_time`; today's universe must be labelled. Canonical `WalletLedger`/`WalletBook` multi-symbol `positions` with gross/net exposure and equity-at-marks; single-currency restriction refuses silent FX mix. `CostModelPack` (`costs.py`) labels Spread/Impact/Latency/Fee/Funding/Borrow as MEASURED/ASSUMED/UNMEASURED with provenance. Inferential honesty (`stats_inferential.py`): block bootstrap CIs, Monte Carlo resample, Deflated Sharpe (trial ledger N), PBO, Benjamini–Hochberg FDR, purge/embargo, CPCV path geometry, minimum useful sample. Live remains BLOCKED.

**Slice 16 (final gates + verifier):** A0–A4 Trading Center Master Program complete on this branch. `LiveTradingGuard` = BLOCKED; A5 = impossible; long work is `market_sim` worker EXTERNAL_REQUIRED; no second trading runtime. Verifier: `scripts/verify_trading_100.py --run-tests`. Remaining honest non-PASS gates (e.g. CPCV/FDR/Windows/corporate-actions) stay NOT_STARTED / IN_PROGRESS / NOT_TESTED_IN_CI — never false PASS.

`Data/modules/trading/stub.py` remains a boundary/stub, not a second trading platform.

Machine gate state lives in `Data/backend/tests/trading_gates.json`; `scripts/verify_trading_100.py` is the verifier.

---

# 21. Tasks, workflows and schedules

- `Data/modules/tasks/`: `service.py`, `store.py`, `planner.py`, `projection.py`, `types.py` — durable task control;
- `Data/modules/workflows/`: runtime/store/types — multi-step workflow execution;
- `Data/modules/schedules/`: runner/store/types — scheduled targets.

They reuse JobRuntime/ExecutionGateway instead of introducing independent queues or side-effect paths.

---

# 22. Settings and BehaviorProfile

`Data/modules/settings/` is the operator configuration authority:

- `catalog.py` — setting definitions;
- `service.py`, `store.py` — control plane and persistence;
- `validation.py`, `types.py` — contracts;
- `bindings.py` — live consumer bindings;
- `behavior.py`, `behavior_store.py`, `resolver.py`, `seed.py` — assistant BehaviorProfile.

`Data/backend/config.py` supplies typed environment/default configuration. SQLite overrides are the durable operator layer where supported. Settings indicate HOT vs restart-required semantics.

Behavior defines model-facing identity/interaction policy; it does not grant technical authority.

### Behavior hot-apply (CURRENT)

- `BehaviorProfileStore` is the persisted global behavioral truth.
- `BehaviorSettingsResolver` creates a **new immutable `BehaviorSnapshot` per independent operation** (chat turn, cognition submit, coding model call).
- Conversations are **not** pinned to the BehaviorProfile version that existed at conversation creation.
- Editing the system prompt (or other BehaviorProfile fields) hot-applies from the **next** turn — no new chat, page refresh, backend restart, or model reload.
- An operation already in flight keeps the immutable snapshot with which it started.
- Long-lived workers observe the latest persisted profile on the next job by reading the store at operation start (not via in-process callbacks alone).
- `SEED_SYSTEM_PROMPT` is first-install / bootstrap only; it is not runtime identity when a persisted profile exists.

---

# 23. Security, isolation, secrets and deployment posture

Relevant modules:

- `Data/modules/security/`: auditor, deployment, injection defenses, secrets broker;
- `Data/modules/isolation/`: guard/sandbox/types;
- `Data/modules/approvals/`: authority and approvals;
- `Data/modules/backup/`: backup/restore;
- `Data/modules/chaos/`: fault injection for controlled testing.

Default posture is local/loopback-oriented. Outbound network is **enabled by default** for provider connectivity, but remains policy-controlled (SSRF protection, private-network restrictions, credential isolation, ExecutionGateway). Non-loopback privileged mutations may require the configured operator token. Do not store secrets in prompts, docs or public telemetry.

---

# 24. Observability, metrics, release and health

- `Data/modules/observability/` — event hub/operator registry/system telemetry;
- `Data/modules/metrics/` — metrics collector/time series;
- `Data/modules/release/` — release gates/CI relevance;
- `Data/modules/master/` — master gate aggregation;
- `Data/modules/product_truth/` — product-truth/posture helpers;
- `Data/modules/analytics/` — analytics service.

Release/evaluation philosophy: missing measurements remain missing; they are not converted to synthetic PASS.

---

# 25. Provider I/O and remote boundaries

`Data/modules/provider_io/` owns controlled remote/provider operations such as generic HTTP, Hugging Face metadata, market-data providers and remote chat/provider calls. It includes policy, credentials, readiness, stream state and executor/facade layers. Network permission remains separate from provider configuration.

`Data/modules/model_download/` owns model-download readiness/facade/executor/errors. `Data/modules/compute/` owns small compute/numeric tier helpers. `Data/modules/native/` is an explicit stub/boundary rather than another model stack.

---

# 26. Repository backend map — where to find things

## `Data/backend/`

- `main.py` — composition + app
- `config.py` — environment/runtime settings
- `database.py` — central SQLite
- `migrations.py` — schema migrations
- `routes/` — domain APIs
- `tests/` — backend/unit/integration/gate manifests

## `Data/modules/`

| Directory | What lives there |
|---|---|
| `agents/` | agent runtime/fleet/multi-agent/blackboard |
| `analytics/` | analytics service |
| `approvals/` | authority/policy/approval persistence |
| `artifacts/` | artifact storage/validation |
| `backup/` | backup/restore |
| `brain/` | unified Brain facade/contracts |
| `browser/` | browser capability implementations/boundaries |
| `chaos/` | controlled fault injection |
| `coding/` | Coding Agent control plane |
| `cognition/` | CognitiveRuntime and structured cognition |
| `common/` | shared atomic/path/hash/correlation/ownership utilities |
| `compute/` | compute/numeric tier utilities |
| `context/` | context building, trust, compaction, multimodal, budgets |
| `datasets/` | dataset lifecycle/quality/index/export |
| `documents/` | document extraction |
| `evaluation/` | evaluation harness/platform/ablations/scorecards |
| `evidence/` | evidence storage/service |
| `execution/` | capability catalog/gateway/receipts |
| `function_runtime/` | cold function registry/runtime |
| `intelligence/` | cross-cutting intelligence policy/health/assimilation |
| `isolation/` | sandbox/isolation guard |
| `jobs/` | durable jobs/leases/retry/resources |
| `knowledge/` | RAG/retrieval/Atlas/DeepRecall/Why |
| `market_sim/` | market simulation/paper/trading orchestras |
| `master/` | master readiness gates |
| `mcp/` | MCP bridge/provider/sessions/transports |
| `media/` | media capabilities |
| `memory/` | durable scoped memory |
| `metrics/` | metrics/time series |
| `model_download/` | model download boundary |
| `model_runtime/` | inference transport/serving |
| `models/` | Model Control Plane |
| `module_manager/` | module discovery/lifecycle |
| `native/` | native runtime stub/boundary |
| `neuro/` | Neuro/Cortex/residual advisory layer |
| `observability/` | system/operator telemetry |
| `observations/` | durable observations |
| `plugins/` | plugin registry |
| `product_truth/` | truth/posture reporting |
| `provider_io/` | controlled remote/provider I/O |
| `reasoning/` | legacy reasoning/retrieval policy |
| `release/` | release/CI gates |
| `research/` | research runtime/evidence/source graph |
| `run/` | parent run lifecycle/event envelope |
| `schedules/` | schedule persistence/runner |
| `security/` | audit/injection/secrets/deployment controls |
| `settings/` | Settings Control Plane/BehaviorProfile |
| `source_ingestion/` | source/file ingestion workers/pipeline |
| `tasks/` | durable task service |
| `trading/` | explicit trading boundary/stub |
| `training/` | training/post-training/flywheel |
| `verification/` | verification engine/report store |
| `voice/` | realtime voice boundary |
| `workers/` | external worker architecture |
| `workflows/` | workflow runtime/store |

## Other backend-relevant locations

- `Data/functions/` — FunctionRuntime executables/cold-path helpers.
- `scripts/` — launchers, worker helpers and verification harnesses.
- `.env.example` — documented environment controls.
- `leviathan.py`, `run_leviathan.bat`, `installer.bat` — startup/install entrypoints.

---

# 27. Frontier Reasoning + Inference-Time Compute program

The active program is an **in-place** evolution. It does not replace Brain/RAG, Memory, Neuro/Cortex, CognitiveRuntime, agents, workers, Model Control Plane, Training or Evaluation.

Current `main` at the documentation snapshot contains the **F0 baseline/audit machinery**. Later phases are targets until merged and verified:

| Phase | Target |
|---|---|
| F0 | baseline/audit + gate skeleton — CURRENT baseline |
| F1 | context/trust + canonical BehaviorProfile |
| F2 | two-axis compute + reasoning capability profile |
| F3 | provider-native reasoning |
| F4 | test-time compute candidates/pruning/repair |
| F5 | structured reasoning state |
| F6 | neural TaskModel + planner |
| F7 | advisory neural action ranking |
| F8 | HypothesisBoard + critic mesh |
| F9 | verification/completion v2 |
| F10 | CapabilityState/self-awareness |
| F11 | async cognition via JobRuntime/workers |
| F12 | long-horizon steering/compaction/resume |
| F13 | experience aggregation/active learning |
| F14 | verified training trajectory bridge |
| F15 | post-training candidate lifecycle |
| F16 | reasoning/tool/coding/research eval + ablations |
| F17 | frontend reasoning controls/observability/settings |
| F18 | final integration/hardening |

Machine-readable reasoning gates are kept at:

- `Data/backend/tests/frontier_reasoning_gates.json`
- verifier: `scripts/verify_frontier_reasoning.py`
- generated verifier report: `Data/backend/tests/frontier_reasoning_completion_report.json` when requested.

R01–R30 must not be described as PASS without executed evidence.

### Invariants for every future phase

```text
one CognitiveRuntime
one Model Control Plane
one ExecutionGateway
one central metadata SQLite authority
Brain/RAG remains knowledge
Memory remains memory
Neuro/Cortex remains advisory
workers remain heavy-work execution plane
model output != observation
action request != authority
unverified result != verified experience
no private chain-of-thought persistence/exposure
```

---

# 28. Machine verification and tests

Key verification manifests/harnesses live outside `Data/docs` so canonical documentation stays limited to two files:

- Frontier reasoning: `Data/backend/tests/frontier_reasoning_gates.json`, `scripts/verify_frontier_reasoning.py`.
- Trading program: `Data/backend/tests/trading_gates.json`, `scripts/verify_trading_100.py`.
- Aggregate runner: `scripts/verify_leviathan.py` (frontier + trading).
- Capability contract: `Data/backend/tests/test_capability_contract_drift.py`.
- Backend tests: `Data/backend/tests/`.
- Frontend tests/build: see companion frontend document.

```bash
python -m pytest Data/backend/tests -q
python scripts/verify_leviathan.py --allow-incomplete --write-report
python scripts/verify_frontier_reasoning.py --allow-f0-skeleton-only
python scripts/verify_trading_100.py --allow-incomplete
```

Incomplete / NOT_STARTED / UNMEASURED / FEATURE_GATED are **not** PASS. Baseline-green CI must not coerce frontier or trading program gates to PASS. `--allow-incomplete` only permits an honest incomplete report without FAIL/crash.

Production-quality program ledger (machine state): `Data/backend/tests/production_quality_program.json` maps waves W00–W23 onto existing R/G/F identifiers. Status is never PASS without executed evidence.

### Production-quality integrity repairs (W00–W04 CURRENT)

- **W00:** Default frontend Vite config no longer statically imports `editor/vite-plugin.mjs`. Editor mode loads only when `LEVIATHAN_EDITOR=1` and the plugin file exists; otherwise it raises a precise configuration error. Excluded trees (`Data/HADES/`, `editor/`) remain unmodified.
- **W01:** `AssistantBenchmarkRunner` never fabricates `ACK` for a missing model or retry (`force_ack` removed). Absent model → `measured=False` / UNAVAILABLE. Retries re-invoke the real caller and preserve attempt evidence. `TaskRunResult.truth` is derived (component vs model-quality), not a fixed end-to-end claim. Token usage is provider-reported or an explicit estimate — never word-count mislabeled as tokens. Trading verifier frontend globs enumerate `.ts`/`.tsx` explicitly (no brace-expansion assumption).
- **W02:** `run_research_campaign_on_worker` executes canonical gym episodes per iteration; trials complete only with simulation receipts; wins come from acceptance, not trial count; zero-risk promotion inputs are not fabricated. `AcceptanceCriteria.evaluate` and `experiments.evaluate_acceptance` fail closed on missing/NaN/infinite metrics and refuse unit inference from magnitude. `evaluate_candidate_pipeline` enforces `max_candidates` atomically (`CANDIDATE_BUDGET_EXHAUSTED`). `may_promote_to` / `promote_asset` reject caller booleans and enforce stage prerequisites. `MarketView.feature` cache keys include clock index/as_of. Citation validity without a report audit is `UNMEASURED`. `SchemaScorer` validates nested types (not keys only).
- **W03:** `TaskModel.acceptance_criteria` are typed predicates (criterion ID, expected artifact/effect, verifier kind, scope, required evidence, status). `CompletionEngine` scores only `supported` as met; outcomes distinguish supported / contradicted / insufficient_evidence / unavailable_verifier / failed_execution. Legacy string `success_criteria` remain compatibility readers — unsupported semantics stay unverified. Trusted test receipts require suite/command, execution, workspace/artifact revision, and attempt id; unrelated shell `exit_code=0`, directory listings, stale receipts, fake artifact IDs, and model-authored evidence fields do not pass. Source refs alone do not satisfy claim support. Low-risk `simple_chat` may finish `COMPLETED_UNVERIFIED` without pretending verification.
- **W04:** `model_runtime/inference_contract.py` + streaming channel honesty. Tool-calling is probed/recorded on every request; SUPPORTED-without-payload raises `TOOL_CALLING_DROPPED`. Structured/`json_schema` responses repair deterministically or fail closed with `STRUCTURED_RESPONSE_UNAVAILABLE` (never schemaSatisfied without validation). Reasoning stream frames stay on a separate channel; partial separation is labeled. Context overflow refuses or truncates with an explicit `context_bound` signal (`CONTEXT_WINDOW_EXCEEDED` / `CONTEXT_TRUNCATED`) — no silent overflow.

### Typed completion and autonomous lab lifecycle (W03 / W16 CURRENT)

- **W03:** See production-quality W03 bullet above (typed `AcceptanceCriterion`, trusted test receipts, A04).
- **W16:** Durable `market_sim_agent_labs` (migration 53). Control-plane methods create/start/pause/resume/cancel labs bound to research campaigns; worker path runs real simulations. HTTP: `/api/market-sim/lab/runs` (+ start/pause/resume/cancel). Valid outcomes remain `QUALIFIED_STRATEGY_FOUND` | `NO_STRATEGY_QUALIFIED`.

Adversarial coverage: `Data/backend/tests/test_adversarial_w01_w02.py` (A01–A03, A06, T01–T05, T14–T15); `test_adversarial_w03_completion.py` (A04 + stale/fake/model-authored); `test_adversarial_w04_inference_contract.py` (tool drop, structured UNAVAILABLE, reasoning channels, context bounds); `test_adversarial_w08_w17.py` (A08 preference supersession + T08 sealed rename inheritance); `test_adversarial_w09_w19.py` (T16 + NL citation/hedging); `test_adversarial_w10_w11.py` (gateway unauthorized/idempotency + lease fence/crash recovery); `test_trading_lab_w16_lifecycle.py`.

Citation audit includes Dutch factual/hedging cues; hedging does not clear evidence duty when factual markers remain. `instruments.support_matrix()` / `family_capability()` keep options/futures/forex as explicit `NOT_IMPLEMENTED` (no silent equity fallback).

### Production-quality cognition / memory / sealed / web (W06 / W08 / W17 CURRENT)

- **W06:** `CognitiveRuntime.cancel` propagates to registered `child_run_ids` (delegation metadata `child_run_id` / `run_id` auto-registers). Parent stop does not leave children running in-process. `CognitivePlanner.replan` records `observation_linked` / `observation_refs`; adaptive reasons without observation ids are marked `observation_trace:MISSING` (strict mode raises `COGNITION_REPLAN_MISSING_OBSERVATION_TRACE`).
- **W08 / A08:** `MemoryStore.correct_preference` writes a new `PREFERENCE`, supersedes every ACTIVE matching `preference_key` (`PREFERENCE` or legacy `FACT`), stays in-scope (no silent GLOBAL wipe from a conversation edit), and ACTIVE search/list return only the current preference.
- **W17 / T08:** Sealed holdout contamination keys use a rename-stable root via `lineage_aliases` / `register_lineage_rename` / optional `root_lineage_id`. Renamed descendants cannot claim a fresh sealed holdout after revelation.
- **Web (GI7):** `HttpWebProvider` search/fetch tolerate thin response doubles (`status_code` / `.text` via getattr + `content` fallback) so rate-limit and robots paths do not turn real provider results into `UNAVAILABLE`/`FAILED` under mocks. Fabrication remains forbidden.
- **W18 / T09:** `LocalPaperBroker.restore_session` + `WalletLedger.from_public_dict` hydrate durable paper wallet/orders after process restart; `paper_session_state` calls hydrate before trading. Feed `EventOrderer` drops duplicate `event_id`s on reconnect; `client_order_id` remains fill-idempotent so replay cannot double-apply.
- **W10 (tool gateway):** Canonical `ExecutionGateway` (`Data/modules/execution/gateway.py`) rejects unauthorized tool calls (`approved_by_user` is never authority; forged/consumed approvals denied). COMPLETED invocations with an `idempotency_key` replay prior output via process cache + durable `ObservationStore` and do not re-dispatch providers (no double side-effects).
- **W11 (durable execution):** `JobStore.transition` / `schedule_retry` accept `expected_lease_owner` fencing; `JobRuntime` completes under its worker id. A stale worker that lost its lease cannot mark COMPLETED after takeover. `recover_expired_leases` moves crashed RUNNING jobs to `RETRY_WAIT` (never fabricates COMPLETED); a later claim re-executes honestly.

Run targeted suites first during phased implementation, then the impacted broader suites.

---

# 29. Documentation maintenance rule

Whenever a backend system, route, canonical owner, major file location, reasoning phase or runtime truth changes:

1. update this document in the same change;
2. update `Leviathan_system_frontend.md` if the UI contract changes;
3. update machine gate manifests/tests instead of adding a new architecture doc;
4. preserve clear `CURRENT` versus `TARGET` wording;
5. prefer code/tests over stale prose.
