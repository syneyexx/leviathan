# LEVIATHAN System Backend Reference

> **Canonical backend documentation.** This is the single human-readable backend architecture reference for LEVIATHAN.
>
> Documentation snapshot: **2026-09-25**, based on `main` after the Frontier Reasoning F0 baseline merge. Runtime code and tests remain the final authority when this document and executable behavior disagree.
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
| Prompt/context compilation | Context subsystem | `Data/modules/context/`, cognition `context_v3.py` |
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

`main.py` is the composition root. It creates and wires the shared instances used by routes and services. Domain logic should stay in modules rather than accumulate in the composition root.

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
| `Data/backend/main.py` | FastAPI app + system composition |
| `Data/backend/config.py` | typed environment/runtime settings |
| `Data/backend/database.py` | SQLite access and initialization |
| `Data/backend/migrations.py` | ordered schema migrations; current main reaches migration 43 |
| `Data/backend/llm.py` | compatibility/boundary helpers |
| `Data/backend/reasoning.py` | compatibility import/boundary |

SQLite is the canonical metadata database. Subsystems must not silently create a second metadata authority.

---

# 5. API route map

Dedicated route modules live in `Data/backend/routes/`:

| Route module | System |
|---|---|
| `agents.py` | Agent Fleet / agent operations |
| `analytics.py` | analytics |
| `brain.py` | Brain graph/search/status |
| `coding.py` | Coding Agent sessions/turns/actions |
| `cognition.py` | cognition submit/status/events/cancel/resume |
| `datasets.py` | dataset management, ingest/index/offline workflows |
| `efficiency.py` | efficiency/resource surfaces |
| `market_sim.py` | market simulation, strategies, data, paper trading |
| `mcp.py` | MCP servers/sessions/tools |
| `models.py` | model registry/providers/downloads/routing/runtime |
| `observability.py` | runtime events/observability |
| `research.py` | research projects/runs/sources |
| `settings.py` | Settings + BehaviorProfile operations |
| `system.py` | telemetry/system status |
| `tasks.py` | durable task orchestration |
| `trading_orchestra.py` | trading-only orchestras/agents |
| `training.py` | training jobs/recipes/state |

Some legacy or compact endpoints remain composed directly in `main.py`; route modules are the preferred domain boundary.

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
- `context_v3.py` — cognition context pack;
- `completion.py` — completion decision logic;
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

`ADAPTIVE` can escalate/de-escalate from uncertainty, evidence coverage, contradiction density, failures, information gain and resource pressure.

### Frontier Reasoning target — not yet a current-main claim

The active master program extends this into **two-axis compute**:

```text
ReasoningDepth = OrchestrationCompute + NeuralInferenceCompute
```

Target additions include `NeuralComputeBudget`, provider reasoning capability profiles, native provider reasoning effort, test-time candidate search, hypothesis branching, neural task/planning advisors, critic mesh, stronger verification, CapabilityState, async cognition, verified-learning aggregation and training bridges. These are **TARGET** until their phase is merged and verified.

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

Cognition additionally uses `Data/modules/cognition/context_v3.py`.

## 7.2 Current known F1 trust gap

On the F0 baseline, `ContextBuilderV3` labels epistemic types (`KNOWLEDGE_SOURCE`, `EVIDENCE`, `TOOL_OBSERVATION`, `NEURAL_ASSOCIATION`, `HYPOTHESIS`, etc.) but still folds non-system sections into a system prompt. The active Frontier Reasoning F1 phase is intended to separate authority so Brain, Memory, web, files, MCP and tool output remain **data**, not system instructions.

Likewise, cognition must converge on the same effective persisted BehaviorProfile as normal Chat instead of a separate seed fallback. Do not document F1 as complete until tests and gates prove it.

---

# 8. Brain, Knowledge/RAG, Atlas and Deep Recall

## 8.1 Brain

`Data/modules/brain/` is the **single Brain access facade**, not a second storage engine:

- `access.py` — access contracts/helpers;
- `contracts.py` — Brain-facing data contracts;
- `facade.py` — unified querying across knowledge, memory, evidence, experience and capabilities.

`main.py` constructs `BrainAccessFacade` over the canonical stores.

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
- `types.py` — kinds, scopes, states and contracts.

Keep these concepts separate:

1. conversation history;
2. cognition `WorkingMemory`;
3. durable MemoryStore;
4. Brain/Knowledge documents;
5. VerifiedExperience.

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
- `capability_probe.py`, `vision.py`, `efficiency_capabilities.py` — capability truth;
- `downloads.py`, `import_service.py` — model acquisition/import;
- `benchmarks.py` — model benchmark support;
- `providers/` — LM Studio, Ollama, OpenAI-compatible, llama.cpp boundary, vLLM-class/base adapters.

Routing and model selection are not permission grants. Model state is reconciled with actual runtime discovery.

## 11.2 Model runtime — `Data/modules/model_runtime/`

Provider-facing execution lives here:

- `openai_compatible.py` — OpenAI-compatible chat/completion client;
- `serving.py` — serving supervisor/cancellation;
- `streaming.py` — stream normalization;
- `managed_adapter.py`, `launch_strategy.py`, `process_control.py`, `port_allocator.py`, `llama_cpp_command.py` — managed serving boundaries;
- `durable_requests.py`, `latency.py` — request/latency support.

`Data/modules/cognition/model_adapter.py` bridges CognitiveRuntime to `ModelControlPlane.inference_session`; cognition must not call an independent private model client.

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
- `admission.py`, `sqlite_support.py`;
- `entrypoints/` for domain-specific processes.

Current entrypoint families include agents, backup, coding, dataset, document AI, embeddings, evaluation, general jobs, knowledge prepare/commit, maintenance, market simulation, MCP execution, model downloads, provider I/O, reranking, research, scheduler, source ingestion, telemetry, training control and workflows.

Architecture rule: the FastAPI/chat process is the **control plane**; long I/O/CPU/GPU work should be externalized through JobRuntime/workers when practical.

---

# 14. Agents, coding and research

## 14.1 Agent system — `Data/modules/agents/`

Files include:

- `runtime.py` — AgentRuntime;
- `fleet.py`, `fleet_types.py`, `store.py` — AgentFleet;
- `planner.py` — structured agent planning;
- `multi.py` — DAG multi-agent coordination;
- `blackboard.py` — shared agent result state;
- `system_inventory.py` — truthful runtime component inventory;
- `types.py` — contracts.

CognitiveRuntime may delegate, but parent cognition remains orchestration authority.

## 14.2 Coding — `Data/modules/coding/`

Coding is a dedicated specialist control plane, not a second general assistant. Important files:

`service.py`, `loop.py`, `worker.py`, `planner.py`, `cognition.py`, `llm_adapter.py`, `parser.py`, `prompts.py`, `workspace.py`, `tools.py`, `patch.py`, `transaction.py`, `verify.py`, `review.py`, `semantic_map.py`, `store.py`, `types.py`.

Writes/executes remain capability/approval gated; tests and receipts are used for verification.

## 14.3 Research — `Data/modules/research/`

Research supports local evidence and optional outbound/web sources:

`service.py`, `runner.py`, `worker.py`, `worker_context.py`, `planner.py`, `coordinator.py`, `question_model.py`, `sources.py`, `source_quality.py`, `web.py`, `ssrf.py`, `uploads.py`, `local_retrieval.py`, `claims.py`, `evidence.py`, `conflicts.py`, `citation_audit.py`, `coverage.py`, `gaps.py`, `graph.py`, `reports.py`, `quality_scorecard.py`, `brain_sync.py`, `assignments.py`, `budgets.py`, `store.py`, `types.py`.

Important truth: outbound network permission and a configured web-search provider are separate conditions. Research must not fabricate browsing.

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

## 16.2 Evaluation — `Data/modules/evaluation/`

`harness.py`, `platform.py`, `store.py`, `types.py`, `scorecard.py`, `paired.py`, `ablations.py`, `assistant_benchmark.py` implement evaluation/reporting. `UNMEASURED` is not treated as PASS.

## 16.3 VerifiedExperience

`Data/modules/cognition/experience.py` admits only sufficiently verified/eligible experience. Current Frontier Reasoning target extends this with aggregate statistics, active-learning capture and structured training trajectories. Raw hidden chain-of-thought must not become training truth.

---

# 17. Evidence, observations, verification and artifacts

- `Data/modules/evidence/` — evidence store/service/types;
- `Data/modules/observations/` — durable observations;
- `Data/modules/verification/` — verification engine/report store/types;
- `Data/modules/artifacts/` — artifact store/types/validation.

System invariant:

```text
model output != observation
request != authority
execution request != successful effect
model says done != verified completion
```

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

---

# 20. Market Simulation / TradingCenter

`Data/modules/market_sim/` is the current trading research/simulation owner. It includes:

- market/data models: `ohlcv.py`, `data_store.py`, `dataset_pipeline.py`, `instruments.py`, providers;
- causality / epistemic time: `causality.py` (`SimulationClock`, `MarketView`), `epistemic.py` (`EpistemicFirewall`, `available_at <= as_of`);
- market state / features (T2): `features.py` (deterministic OHLCV indicator library + provenance), `market_state.py` (`MarketState`, `MultiTimeframeView`, causal higher-TF aggregation);
- strategy DSL v2 (T3): `strategy_dsl.py` (declarative sandboxed AST — no arbitrary Python), `strategy_eval.py` (legacy ma_cross/mean_reversion + DSL evaluate);
- reproducibility: `knowledge_snapshot.py` (`TradingKnowledgeSnapshot` persisted per run);
- engine: `engine.py`, `multi_engine.py`, `fill_model.py`, `execution.py` (prepare verifies `data_hash`; multi-agent rounds attach `MarketState`);
- accounting/risk: `accounting.py`, `portfolio.py`, `risk_guard.py`, `trading_live_guard.py`;
- strategies/experiments: `strategy_eval.py`, `experiments.py`, `metrics.py`;
- multi-agent hooks: `roles.py`, `deliberation.py`, `commit_reveal.py`, `brain_hooks.py` (as_of / firewall filtering);
- paper path: `paper_broker.py`;
- service/store/worker/types/capabilities;
- `orchestra/` — trading-only orchestration on the existing Agent Fleet and Model Control Plane.

**T1 (causality + data foundation):** historical agents observe markets through `MarketView`; information sources must respect `available_at <= simulation as_of`; sealed market dataset versions are content-addressed and immutable (corrections create a new version); every run stores a `TradingKnowledgeSnapshot`.

**T2 (market state + features):** `FeatureEngine` computes causal SMA/EMA/RSI/ATR/ADX/Bollinger/z-score/ROC/realized-vol/Donchian/VWAP/volume/breakout/slope/drawdown/correlation/beta/relative-strength with measured/insufficient/not-implemented status and provenance. `MarketState` packages deterministic price/trend/momentum/volatility/volume/structure/regime fields (neural interpretation excluded). Multi-timeframe views synthesize higher TFs from visible base bars only. OHLCV never claims order-book imbalance. Live broker/real-money execution remains blocked.

**T3 (Strategy Spec DSL v2):** Strategies are declarative documents (features, regime filters, entry/exit conditions, sizing, risk, cooldowns) compiled to a sandboxed AST — no `eval`/`exec`/imports. Family templates cover trend/MA/momentum/mean-reversion/breakout/vol-breakout/range/RS/MTF/event-filtered/custom. Legacy `ma_cross` / `mean_reversion` remain supported and lift into DSL v2. Validate + family-template APIs reject invalid specs before simulation. Immutable version lineage stores content hashes + nested DSL specs.

**T4 (control-plane integration):** Market-sim mutations dispatch through `ExecutionGateway` + capability catalog (MODULE provider). Default run advance path uses JobStore leases + heartbeats (`BEGIN IMMEDIATE` claim). Alpaca paper credentials resolve via `SecretsBroker` (`env:` refs). Observability emits under `trading` category. Trial ledger persists `strategy_version`; acceptance metrics align with `compute_metrics`; rolling walk-forward windows available.

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

---

# 23. Security, isolation, secrets and deployment posture

Relevant modules:

- `Data/modules/security/`: auditor, deployment, injection defenses, secrets broker;
- `Data/modules/isolation/`: guard/sandbox/types;
- `Data/modules/approvals/`: authority and approvals;
- `Data/modules/backup/`: backup/restore;
- `Data/modules/chaos/`: fault injection for controlled testing.

Default posture is local/loopback-oriented and outbound network is policy-controlled. Non-loopback privileged mutations may require the configured operator token. Do not store secrets in prompts, docs or public telemetry.

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
- Backend tests: `Data/backend/tests/`.
- Frontend tests/build: see companion frontend document.

Typical backend test entry:

```bash
python -m pytest Data/backend/tests -q
```

Run targeted suites first during phased implementation, then the impacted broader suites.

---

# 29. Documentation maintenance rule

Whenever a backend system, route, canonical owner, major file location, reasoning phase or runtime truth changes:

1. update this document in the same change;
2. update `Leviathan_system_frontend.md` if the UI contract changes;
3. update machine gate manifests/tests instead of adding a new architecture doc;
4. preserve clear `CURRENT` versus `TARGET` wording;
5. prefer code/tests over stale prose.
