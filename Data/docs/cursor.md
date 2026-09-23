# Cursor Guide — LEVIATHAN Repository Map

This file tells Cursor where LEVIATHAN functionality belongs and where to look before changing anything.

## Primary rule

LEVIATHAN is a **Python-first** project.

| Concern | Location |
|---|---|
| Backend / control plane | `Data/backend/` |
| Browser UI | `Data/frontend/` (React / TypeScript / Vite) |
| Stateful domain modules | `Data/modules/` |
| On-demand cold-path functions | `Data/functions/` |
| Architecture / build docs | `Data/docs/` |

Do not recreate parallel root-level `backend`, `frontend`, `assets`, `css`, or `js` structures.

---

# Current repository structure

```text
LEVIATHAN/
├── Data/
│   ├── backend/
│   │   ├── config.py
│   │   ├── database.py
│   │   ├── llm.py
│   │   ├── main.py
│   │   ├── reasoning.py
│   │   └── tests/test_foundation.py
│   ├── frontend/
│   │   ├── package.json
│   │   ├── vite.config.ts
│   │   ├── index.html
│   │   ├── public/assets/
│   │   ├── dist/                 # production build (gitignored)
│   │   └── src/
│   │       ├── main.tsx
│   │       ├── App.tsx
│   │       ├── api/client.ts
│   │       ├── components/
│   │       ├── layouts/
│   │       ├── pages/
│   │       ├── hooks/
│   │       ├── state/
│   │       ├── styles/
│   │       └── types/
│   ├── functions/                # on-demand implementations
│   ├── modules/                  # reserved
│   └── docs/
│       ├── buildplan.md
│       ├── cursor.md
│       └── leviathan_system.md
├── .env.example
├── .gitignore
├── requirements.txt
├── README.md
├── leviathan.py
├── installer.bat
└── run_leviathan.bat
```

---

# Backend ownership

## `Data/backend/main.py`

FastAPI composition root: lifespan (migrations + DB + runs), API routes, SPA serving from `FRONTEND_DIST`.

Avoid growing domain logic here.

## `Data/backend/config.py`

Nested typed `Settings` domains + `ConfigurationError` + path constants (`FRONTEND_DIST`, etc.).

## `Data/backend/database.py`

SQLite conversations, messages, Knowledge (+ FTS5).

## `Data/backend/migrations.py`

Ordered schema migration runner (`schema_migrations` table).

## `Data/backend/llm.py` / `reasoning.py`

Compatibility shims → `Data.modules.model_runtime` / `Data.modules.reasoning`.

## Modules (preferred owners)

| Package | Owns |
|---|---|
| `Data/modules/reasoning/` | ReasoningEngine (legacy classifier / compatibility) |
| `Data/modules/cognition/` | **Cognitive Runtime** — TaskModel, BeliefState, WorkingMemory, Perception, MetaController, iterative loop, experience |
| `Data/backend/routes/cognition.py` | Cognition HTTP API (`/api/cognition/*`) |
| `Data/docs/cognitive_runtime.md` | Cognitive Runtime architecture reference |
| `Data/modules/settings/` | **Settings Control Plane** — catalog, overrides, validation, hot/restart apply |
| `Data/backend/routes/settings.py` | Settings HTTP API (`/api/settings*`) |
| `Data/docs/settings_control_plane.md` | Settings ownership, precedence, secrets |
| `Data/modules/context/` | ContextBuilder |
| `Data/modules/model_runtime/` | OpenAICompatibleLLM |
| `Data/modules/models/` | **Model Control Plane** (registry, profiles, gateway, router, providers, downloads) |
| `Data/backend/routes/models.py` | Models HTTP API surface (included from `main.py`) |
| `Data/modules/run/` | RunStore / EventEnvelope / transitions + correlation |
| `Data/modules/jobs/` | JobStore / JobRuntime / leases / budgets / ResourceManager |
| `Data/modules/execution/` | CapabilityCatalog / ExecutionGateway / FrontierCapabilityManifest / receipts |
| `Data/modules/approvals/` | Policy + ApprovalService + AuthorityProfile |
| `Data/modules/settings/` | Settings Control Plane + BehaviorProfile |
| `Data/modules/common/` | CorrelationIds + ownership matrix |
| `Data/modules/browser/` | BrowserWorker + FixtureBrowserBackend (Gateway-dispatched) |
| `Data/modules/security/` | SecurityAuditor + SecretsBroker |
| `Data/backend/tests/test_architecture_wave0.py` | Wave 0 architecture conformance exit gate |
| `Data/backend/tests/test_wave1_cognition_agents.py` | Wave 1 cognition hydrate/invoke + DAG agents |
| `Data/backend/tests/test_wave2_evaluation.py` | Wave 2 evaluation platform / release authority |
| `Data/backend/tests/test_wave3_model_serving.py` | Wave 3 managed serving / measured routing |
| `Data/backend/tests/test_wave4_context_memory_knowledge.py` | Wave 4 context constraints / memory scope / retrieval thresholds |
| `Data/backend/tests/test_wave5_capability_world.py` | Wave 5 API/MCP/browser shared Run/Gateway/Evidence exit gate |
| `Data/backend/tests/test_wave6_coding_research.py` | Wave 6 coding semantic map / transactional patches + research claim graphs |
| `Data/backend/tests/test_wave7_multimodal_realtime.py` | Wave 7 multimodal session + media/voice Gateway + single context/run exit gate |
| `Data/backend/tests/test_wave8_data_training_factory.py` | Wave 8 shard resume / mixture / integrity-gated registry exit gate |
| `Data/backend/tests/test_wave9_posttraining_flywheel.py` | Wave 9 preference/DPO flywheel + no silent promote exit gate |
| `Data/backend/tests/test_wave10_production_ops.py` | Wave 10 ops recovery / no-leak / no-dup exit gate |
| `Data/backend/tests/test_wave11_product_unification.py` | Wave 11 one operating platform exit gate |
| `Data/modules/ops/` | ProductionOpsPlane + deployment profiles |
| `Data/modules/projects/` | ProjectStore / ContinuityPlane / ProductUnificationPlane |
| `Data/modules/timeline/` | Unified work timeline projection |
| `Data/modules/sdk/` | FixtureSdk over Gateway/plugins |
| `Data/modules/media/` | MediaService fixture pipelines (Gateway-dispatched) |
| `Data/modules/voice/` | RealtimeVoiceService fixture ASR/TTS + barge-in |
| `Data/modules/artifacts/` | ArtifactStore |
| `Data/modules/knowledge/` | KnowledgeStore / HybridRetriever |
| `Data/modules/function_runtime/` | FunctionRegistry / FunctionRuntime |
| `Data/modules/observations/` | ToolObservation / Effect ledger |
| `Data/modules/evidence/` | EvidenceStore / EvidenceService |
| `Data/modules/memory/` | MemoryStore |
| `Data/modules/verification/` | VerificationEngine |
| `Data/modules/agents/` | AgentRuntime (feature-flagged) |
| `Data/modules/coding/` | **CodingControlPlane** — sessions, XML loop, workspace, patches |
| `Data/backend/routes/coding.py` | Coding HTTP API (`/api/coding/*`) |
| `Data/modules/workflows/` | WorkflowStore / WorkflowRuntime |
| `Data/modules/schedules/` | ScheduleStore / ScheduleRunner |
| `Data/modules/observability/` | ObservabilityHub |
| `Data/modules/neuro/` | NeuroAdvisor + residual/cortex/critic/memory_tiers/adapters/orchestrator/snapshots |
| `Data/modules/module_manager/` | Universal Module Manager (`ILeviathanModule` + optional subprocess) |
| `Data/modules/plugins/` | PluginRegistry / declarative Tool bindings (not a second loader) |
| `Data/modules/mcp/` | **Universal MCP Bridge** — one bridge, many sessions; Tools provider |
| `Data/backend/routes/mcp.py` | MCP HTTP API (`/api/mcp/*`; call via ExecutionGateway) |
| `Data/docs/mcp_bridge.md` | MCP architecture reference |
| `Data/modules/evaluation/` | EvaluationHarness + EvaluationPlatform (scorecards, regression corpus) |
| `Data/modules/models/` | Model Control Plane + measured router + managed serving providers |
| `Data/modules/model_runtime/` | OpenAI-compatible LLM + ServingSupervisor / managed adapters |
| `Data/modules/isolation/` | IsolationGuard |
| `Data/modules/training/` | TrainingRegistry stub + TrainingRecipeRegistry |
| `Data/modules/browser/` | BrowserAutomationStub |
| `Data/modules/media/` | MediaAutomationStub |
| `Data/modules/voice/` | VoiceRuntimeStub |
| `Data/modules/release/` | ReleaseGateRunner + evaluation relevance gate |
| `Data/modules/security/` | SecurityAuditor |
| `Data/modules/backup/` | BackupService |
| `Data/modules/metrics/` | MetricsCollector |
| `Data/modules/chaos/` | ChaosInjector |
| `Data/modules/master/` | MasterGateRunner |

## Tests

`Data/backend/tests/` — foundation through master/integration harness.

---

# Frontend ownership

## Entry

- `src/main.tsx` — React mount + router + toast provider
- `src/App.tsx` — routes `/`, `/chat`, `/chat.html` redirect

## Pages

- `src/pages/CommandPage.tsx` — dashboard/Command shell
- `src/pages/ChatPage.tsx` — real chat against `/api/*`
- `src/pages/ModelsPage.tsx` → `src/pages/models/*` — Model Control Plane UI (no mock catalog)
- `src/pages/CodingPage.tsx` → `src/pages/coding/*` — **Coding Agent** operator surface (`/coding`, real APIs; not chat redirect)
- `src/pages/ResearchPage.tsx` — Research workspace
- `src/pages/StatusPage.tsx` — operator status
- `src/pages/BrainPage.tsx`, `TrainingPage.tsx`, `SettingsPage.tsx` — additional shells

## Models UI ownership

| File | Role |
|---|---|
| `pages/models/ModelsPage.tsx` | Page composition / data load |
| `ModelCatalog.tsx` | Search/filter/sort/keyboard selection |
| `ModelInspector.tsx` | Overview/capabilities/profile/runtime/resources/benchmarks/diagnostics |
| `ProviderManager.tsx` | Provider CRUD + connection test |
| `ModelGatewayPanel.tsx` / `ModelRouterPanel.tsx` | Live gateway + router editor |
| `ModelImportDialog.tsx` / `ModelDownloadManager.tsx` | Import/download UX |

Do not put provider-specific logic in React — call `/api/model-providers` and capability flags.

## Shared shell

- `src/layouts/AppShell.tsx`
- `src/components/AppHeader.tsx`, `AppSidebar.tsx`, `AppFooter.tsx`

## API

- `src/api/client.ts` — typed client (do not scatter raw `fetch`)
- `src/types/api.ts` — response/request types

## Styles / identity

- `src/styles/tokens.css` — canonical visual tokens
- `src/styles/leviathan.css`, `chat.css` — shell + chat

## Build / serve

```bash
cd Data/frontend
npm install
npm run build    # writes dist/
```

Backend serves `Data/frontend/dist`. Dev: `npm run dev` proxies `/api` → `:8765`.

Frontend gates: `npm run typecheck`, `npm run lint`, `npm run build`, `npm run test`.

---

# modules vs functions

| Use `Data/modules/` when | Use `Data/functions/` when |
|---|---|
| Persistent state / lifecycle | Stateless helper |
| Continuous cognition participation | Occasional cold-path capability |
| Domain API surface | Lazy load + cleanup |

Do not create empty architecture theater.

---

# Current runtime flow

```text
Browser (React SPA)
   ↓
typed api client (src/api/client.ts)
   ↓
POST /api/chat  (Data/backend/main.py)
   ↓
ReasoningEngine → optional Knowledge → OpenAICompatibleLLM
   ↓
SQLite persistence
```

---

# Where to place future work (Master Program)

| Phase concern | Owner |
|---|---|
| Typed config expansion | `Data/backend/config.py` → later configuration module |
| Run + events | new `Data/modules/run/` (or backend package first) |
| Context Engine | new module; migrate out of `llm.py` |
| Knowledge ingest parsers (PDF/OCR) | `Data/functions/` called by Knowledge |
| Knowledge store / retrieval | `Data/modules/knowledge/` |
| Function runtime | `Data/modules/function_runtime/` |
| Function implementations | `Data/functions/<name>/` |
| Capabilities / Execution Gateway | `Data/modules/execution/` |
| Approvals / policy | `Data/modules/approvals/` |
| Jobs / resources | `Data/modules/jobs/` |
| Observations / effects | `Data/modules/observations/` |
| Evidence | `Data/modules/evidence/` |
| Memory | `Data/modules/memory/` |
| Verification | `Data/modules/verification/` |
| Agents | `Data/modules/agents/` (requires feature flag) |
| Coding Agent | `Data/modules/coding/` + `/coding` UI (requires `LEVIATHAN_FEATURE_AGENTS` + `LEVIATHAN_FEATURE_CODING`) |
| Market Sim | `Data/modules/market_sim/` + `/trading` UI (requires `LEVIATHAN_FEATURE_MARKET_SIM`; paper/causal only) |
| Workflows | `Data/modules/workflows/` |
| Schedules | `Data/modules/schedules/` |
| Observability | `Data/modules/observability/` |
| Neuro | `Data/modules/neuro/` (advisory; feature-flagged; residual optional) |
| Universal Module Manager | `Data/modules/module_manager/` (single loader; feature-flagged) |
| Neuro architecture spec | `Data/docs/neuro_layer_architecture.md` |
| Plugins / MCP bindings | `Data/modules/plugins/` (declarative) + `Data/modules/mcp/` (bridge) |
| Evaluation | `Data/modules/evaluation/` |
| Isolation | `Data/modules/isolation/` |
| Training | `Data/modules/training/` (registry stub) |
| Browser / Media / Voice | stub modules under `Data/modules/{browser,media,voice}/` |
| Release gates | `Data/modules/release/` (consumes evaluation relevance) |
| Security posture | `Data/modules/security/` |
| Backup / restore | `Data/modules/backup/` |
| Metrics | `Data/modules/metrics/` |
| Chaos helpers | `Data/modules/chaos/` (default OFF) |
| Master gates | `Data/modules/master/` |
| Frontend pages | only when backend truth exists |

---

# Rules for Cursor changes

1. Read `buildplan.md`, `leviathan_system.md`, this file, then owning code.
2. Python first for orchestration.
3. Do not make `main.py` a god file.
4. Backend owns truth; frontend reflects it.
5. No fake success / fabricated metrics.
6. Update docs after every meaningful phase (newest buildplan entry on top).
7. Preserve LEVIATHAN visual identity on frontend changes.
8. Do not depend on other repositories unless the operator explicitly instructs it.

---

# Immediate capability boundary

**Real today:** dashboard + chat UI, FastAPI, LLM client, SQLite chat/Knowledge, reasoning, Run/Artifact/Knowledge V2, Function Runtime, Execution Gateway, Approvals, Jobs, Observations, Evidence, Memory, Verification (durable reports), Agents (flagged), Coding Agent (flagged), Workflows, Schedules, Observability, Neuro Layer 46–54, Universal Module Manager (flagged; optional subprocess), **Universal MCP Bridge** (flagged), Plugins declarative bindings, Evaluation (+ neuro ablations), Isolation, Training/Browser/Media/Voice/Native/Trading stubs, Release + Security + Master gates, Backup/restore, Metrics, Chaos (OFF), operator Status + Models + MCP pages.

**Not claimed:** production certification, live trading fills, real browser/media/voice automation, native runtime, cloud backup sync, APM, penetration testing, default production GPU residual path, residual-aware stream without degrade, multi-hour soak SLOs.
