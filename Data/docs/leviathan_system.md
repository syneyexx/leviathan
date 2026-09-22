# LEVIATHAN System Reference — Current Architecture

> Purpose: describe **how LEVIATHAN currently works**.
>
> This is the implementation truth for the repository as of the **Universal MCP Bridge** (migration v17) on Market Simulation (v16) + Coding Agent + Models + Datasets/Training/Research foundation.
>
> HADES remains a behavioral reference for future subsystems. It is **not** implemented here.

When this document disagrees with executable code and tests, **code and tests win**.

---

# 1. What LEVIATHAN is today

LEVIATHAN is a Python-first, local-first AI control plane with Master Engineering Program foundation (phases 0–45), Neuro Layer phases 46–52, a full **Model Control Plane**, Datasets/Training/Research (v14), Coding Agent, **Market Simulation** for `/trading`, and a **Universal MCP Bridge** for Tools.

**Implemented and real:**

- FastAPI backend composition root (`0.57.0-mcp`);
- **Universal MCP Bridge** (`Data/modules/mcp/`) — one bridge, many stdio/HTTP sessions; tools → CapabilityCatalog (`provider_kind=MCP`); invoke only via ExecutionGateway;
- **Coding Agent** (`Data/modules/coding/`) — sessions, XML capability loop, workspace confinement (HADES excluded), approval-gated writes, background worker;
- **Market Simulation** (`Data/modules/market_sim/`) — causal OHLCV engine, strategy versions, multi-agent deliberation + brain hooks, paper fills only (flagged);
- **Model Control Plane** (`Data/modules/models/`) — registry, profiles, providers, gateway, router, lifecycle, import/download, probes;
- OpenAI-compatible LLM client used as the inference executor (LM Studio–friendly);
- SQLite persistence + migrations through **v17**;
- Domain modules through Master gates including Universal Module Manager, neuro residual adapters, cortex runtime, memory snapshots, ModelData absorb via Knowledge V2, training recipes, subprocess isolation flag;
- Honest stubs: Training execution / Browser / Media / Voice / Native / Trading / llama.cpp managed runtime;
- React + TypeScript + Vite frontend with operator `/status`, production `/models`, **Coding Agent** `/coding`, **Market Sim** `/trading`, and **MCP** `/mcp` UI;
- typed frontend API client;
- honest failure semantics (no fabricated success).

**Not claimed:**

- Real browser/media/voice/native runtimes; live broker trading;
- Legacy MCP SSE transport; full OS container isolation adapter; MCP resources/prompts/sampling;
- **weight-backed HF residual inject** as default; production GPU residual hooks;
- Programmatic LM Studio load/unload (external management);
- Managed llama.cpp inference engine;
- Chat SSE streaming transport (preference stored only);
- training execution with real metrics; production APM / certification / cloud backup sync.

**Model Control Plane:**

- UI → `/api/models*` + `/api/model-providers*` → `ModelControlPlane` → Registry / Router / Gateway / RuntimeManager → Provider adapters → runtime
- Providers: LM Studio (discover/health/inference), Ollama (discover/pull/delete/inference), OpenAI-compatible, llama.cpp boundary (unsupported)
- Active model ≠ selected model; profiles persisted; fallback + role routing with traced decisions
- Capability probing caches declared vs verified; never gates tools via keyword NLU

**Neuro Layer (Phases 46–51):** remains as previously documented.

**Implemented through Phase 45:** remains as previously documented.

---

# 2. Repository layout

```text
LEVIATHAN/
├── Data/
│   ├── backend/          # Python control plane (FastAPI, DB, LLM, config, migrations)
│   ├── frontend/         # React/TypeScript/Vite UI
│   ├── modules/          # Domain modules (gateway, neuro, module_manager, …)
│   ├── functions/        # On-demand cold-path helpers
│   └── docs/             # buildplan.md, leviathan_system.md, cursor.md, neuro_layer_architecture.md
├── leviathan.py          # Uvicorn launcher helper
├── requirements.txt
├── .env.example
├── installer.bat
├── run_leviathan.bat
└── README.md
```

Ownership rule: one responsibility → one clear owner. Do not invent parallel databases, model clients, or approval systems.

---

# 3. Backend

## 3.1 Composition root — `Data/backend/main.py`

FastAPI application (`version=0.55.0-phase52`).

Responsibilities:

- lifespan DB initialize + optional ModuleManager discover/load/initialize;
- `/api/*` route registration;
- wire shared stores, gateway, neuro advisor, module manager;
- serve the Vite production build from `Data/frontend/dist`.

`main.py` must remain composition-oriented. Domain logic belongs in dedicated modules/services as the system grows.

## 3.2 Configuration — `Data/backend/config.py`

`Settings` dataclass loaded from environment / `.env`:

| Setting | Env var | Default |
|---|---|---|
| LLM base URL | `LEVIATHAN_LLM_BASE_URL` | `http://127.0.0.1:1234/v1` |
| Model id | `LEVIATHAN_LLM_MODEL` | empty → discover first `/v1/models` entry |
| API key | `LEVIATHAN_LLM_API_KEY` | `not-needed` |
| Timeout | `LEVIATHAN_LLM_TIMEOUT_SECONDS` | `90` |
| Database path | `LEVIATHAN_DATABASE_PATH` | `Data/backend/data/leviathan.db` |
| Knowledge top-k | `LEVIATHAN_KNOWLEDGE_TOP_K` | `5` |
| History window | `LEVIATHAN_MAX_HISTORY_MESSAGES` | `24` |
| Reasoning | `LEVIATHAN_REASONING_ENABLED` | `true` |

Path constants: `PROJECT_ROOT`, `DATA_ROOT`, `BACKEND_ROOT`, `FRONTEND_ROOT`, `FRONTEND_DIST`.

## 3.3 Persistence — `Data/backend/database.py` + migrations

SQLite with WAL + foreign keys. Schema evolution via `Data/backend/migrations.py` (`schema_migrations`, currently through **v15**).

Core chat tables (also ensured in `Database.initialize`):

- `conversations`, `messages`, knowledge (+ FTS5 when available)

Model Control Plane tables (migration v13):

- `model_providers`, `model_registry`, `model_profiles`, `model_control_state`
- `model_capability_results`, `model_downloads`, `model_audit_log`

Datasets / Training / Research (migration v14): dataset_*, training_*, research_* tables.

Coding Agent (migration v15):

- `coding_sessions`, `coding_turns`, `coding_steps`, `coding_patches`

Additional domain tables from earlier migrations: artifacts, approvals, jobs, observations/effects, evidence, memory, workflows, schedules, verification_reports, neuro_memory_snapshots.

## 3.4 Reasoning — `Data/backend/reasoning.py`

`ReasoningEngine.analyze(message, has_knowledge) → ReasoningPlan`.

`ReasoningPlan` fields: `intent`, `complexity`, `use_knowledge`, `steps`.

Public summary only — **no private chain-of-thought persistence**.

Deterministic keyword/heuristic classification. Not authoritative for security or side effects.

## 3.5 Model client + Model Control Plane

**Executor:** `Data/modules/model_runtime/OpenAICompatibleLLM` — HTTP chat completions against a resolved endpoint/model.

**Control plane owner:** `Data/modules/models/ModelControlPlane`

- Provider adapters: LM Studio, Ollama, OpenAI-compatible, llama.cpp (boundary)
- Registry reconciles discovery vs persistence; never trusts persisted `loaded=true` after restart without rediscovery
- Router precedence: explicit → agent → role → active → fallback → optional cloud
- Gateway tracks real inflight/queue/errors (never synthetic)
- Profiles persisted per model; activation is explicit
- Lifecycle load/unload gated by adapter `RuntimeCapabilities` (unsupported → HTTP 409)

Routes: `Data/backend/routes/models.py` (`/api/models*`, `/api/model-providers*`, `/api/model-downloads*`).

## 3.6 Chat orchestration flow

```text
POST /api/chat
  → ensure/create conversation
  → persist user message
  → ReasoningEngine.analyze
  → optional Knowledge search
  → ModelControlPlane.resolve_for_chat (+ gateway acquire)
  → LLM.chat (endpoint/model/profile from router)
  → gateway release; persist assistant message OR HTTP error
  → return reasoning + optional routing metadata
```

If the registry is empty / router exhausted and no explicit model was requested, chat may fall back to legacy settings-based LLM resolution (recorded as fallback).

Completion of a chat turn means: model returned usable text and the assistant message was persisted.

## 3.6b Coding Agent flow

Owner: `Data/modules/coding/` · UI: `/coding` · Flag: `LEVIATHAN_FEATURE_CODING` (requires AGENTS).

```text
POST /api/coding/sessions + /turn
  → persist user turn; status=RUNNING; wake CodingWorker
  → CodingLoop (background thread):
       ReasoningEngine → optional NeuroAdvisor (advisory)
       ContextBuilder(mode=coding) with CODING_SYSTEM_PROMPT
       LLM.chat (temperature 0.1) → parse XML <capability> tags
       READ → ExecutionGateway; WRITE/EXECUTE → ApprovalService then WAITING_APPROVAL
       observations / coding_patches / VerificationEngine
  → UI polls GET /api/coding/sessions/{id}
```

Workspace default: `LEVIATHAN_CODING_WORKSPACE` (`D:/leviathan/codingworkspace`). HADES paths denied. No private shell/FS/DB.

## 3.7 Knowledge V2 / RAG V3

Owner: `Data/modules/knowledge/`. See also `Data/docs/rag_v3_architecture.md`.

- Documents with ingest status (`DISCOVERED`…`READY`/`FAILED`/…), content hash, provenance path/mtime, parser metadata
- Chunks with hashes, span offsets, confidence, source_type, provenance JSON; READY only after successful chunk/index write
- Lexical chunk FTS (LIKE fallback); metadata `source` filter
- `EmbeddingProvider` interface: `NullEmbeddingProvider`, `LocalHashEmbeddingProvider`, optional SentenceTransformers
- `HybridRetriever` V3 — lexical + dense fusion + optional reranker; never fabricates vectors when unavailable
- Cold Atlas (mutable interpretation) + Deep Recall + Why Library behind feature flags
- Directional relation atoms + chunk embeddings in central SQLite (no parallel vector DB)
- Incremental file ingest under `LEVIATHAN_DATA_ROOT` with change detection / re-chunk on edit
- API: CRUD, search, atlas, deep-recall, why, document+chunks, `ingest/path`, `ingest/scan`

## 3.8 Health

`GET /api/health` returns:

- process ok / version;
- database path;
- reasoning flag;
- frontend dist readiness;
- LLM availability (honest unavailable state).

## 3.9 Frontend serving

Production UI is the Vite build at `Data/frontend/dist`.

- `/` and `/chat` (+ `/chat.html` compatibility) serve `dist/index.html`;
- `/assets` mounts `dist/assets` when present;
- SPA fallback returns `index.html` for non-API paths;
- missing build → HTTP 503 with build instructions.

Dev alternative: `npm run dev` in `Data/frontend` (Vite proxies `/api` → `:8765`).

---

# 4. Frontend

## 4.1 Stack

React 19 · TypeScript · Vite 7 · React Router · oxlint · Vitest

## 4.2 Layout

```text
Data/frontend/
├── package.json
├── vite.config.ts
├── tsconfig*.json
├── index.html
├── public/assets/          # static imagery
├── dist/                   # production build (gitignored)
└── src/
    ├── main.tsx
    ├── App.tsx
    ├── api/client.ts       # typed API client
    ├── types/api.ts
    ├── components/         # Header, Sidebar, Footer, Toast, BrandMark
    ├── layouts/AppShell.tsx
    ├── pages/CommandPage.tsx
    ├── pages/ChatPage.tsx
    ├── hooks/
    ├── state/
    └── styles/             # tokens.css, leviathan.css, chat.css
```

## 4.3 Visual identity

Design tokens in `src/styles/tokens.css` preserve the LEVIATHAN gold/dark shell:

- Cinzel display + Inter UI fonts;
- gold accents (`--lv-gold*`);
- existing layout class names (`lv-*`).

Phase 1 is a **framework migration**, not a visual redesign.

## 4.4 Routes

| Path | Page | Backend truth |
|---|---|---|
| `/` | Command dashboard shell | Visual + navigation; prompt can hand off draft to chat |
| `/chat` | Chat | Real conversations / messages / LLM / reasoning metadata |
| `/chat.html` | redirect → `/chat` | Compatibility |

Reserved nav items without a real page stay section-local tabs — they are **not** fake backend pages. `/coding` is a real Coding Agent surface (not a chat redirect).

## 4.5 Typed API client

`src/api/client.ts` owns fetch against:

- `/api/health`
- `/api/conversations`
- `/api/chat`

Components must not scatter raw `fetch` for these contracts.

## 4.6 Frontend state rule

Frontend state is a projection. Canonical conversation/message/knowledge state lives in SQLite via the backend.

---

# 5. Modules and functions

`Data/modules/` now owns (among others):

- `reasoning/` — ReasoningEngine
- `context/` — ContextBuilder / ContextPack
- `model_runtime/` — OpenAICompatibleLLM
- `run/` — RunStore, RunState, events
- `artifacts/` — ArtifactStore + content hashing
- `knowledge/` — KnowledgeStore V2 + HybridRetriever
- `function_runtime/` — FunctionRegistry + FunctionRuntime
- `execution/` — CapabilityCatalog + ExecutionGateway
- `memory/` — MemoryStore (controlled; EPISODIC/DECISION kinds)
- `neuro/` — NeuroAdvisor + residual/cortex/critic/memory_tiers contracts
- `module_manager/` — Universal Module Manager (`ILeviathanModule`)
- `plugins/` — PluginRegistry (declarative catalog bindings; not a second loader)
- `observability/` — ObservabilityHub

`Data/functions/` holds ON_DEMAND implementations (`text_file_read`, `csv_inspector`, `pdf_parser`).
Runtime ownership: `Data/modules/function_runtime/` (registry + lazy execute/cleanup).

### Neuro + Module Manager dataflow

```text
ReasoningPlan → CortexPlanner (optional)
             → NeuroMemoryFacade (Tier0/1/2 via Memory + Knowledge)
             → ProcessCritic (advisory)
             → ResidualStreamPort (Unsupported today → degrade)
             → NeuroSignal[] (never authority)

ModuleManager discover(Data/modules + ModelData/plugins)
  → load/initialize ILeviathanModule
  → execute(op) contained
  → side-effecting work still via ExecutionGateway
```

Full Neuro design: `Data/docs/neuro_layer_architecture.md`.

---

# 6. Security / trust (current)

- Default bind: loopback (`127.0.0.1:8765`);
- no authentication layer (local-operator assumption);
- no tool/execution plane yet;
- Knowledge text is labeled as data, not system policy, in the model prompt;
- secrets belong in `.env` (gitignored), never in docs or frontend bundles.

---

# 7. Tests currently present

Backend (`python3 -m unittest Data.backend.tests.test_foundation -v`):

- conversation/message persistence;
- Knowledge retrieval;
- reasoning intent / knowledge gating.

Frontend:

- `npm run typecheck`
- `npm run lint`
- `npm run build`
- `npm run test` (ApiError unit test)

Live LLM integration is **NOT** claimed by unit tests. When no model server is available, chat returns 503.

---

# 8. Important classes / symbols

| Symbol | File | Role |
|---|---|---|
| `Settings` | `config.py` | Typed env settings |
| `Database` | `database.py` | SQLite persistence |
| `ReasoningEngine` / `ReasoningPlan` | `reasoning.py` | Deterministic plan seam |
| `OpenAICompatibleLLM` / `LLMUnavailable` | `llm.py` | Model gateway (v0) |
| `app` | `main.py` | FastAPI composition |
| `api` | `frontend/src/api/client.ts` | Typed UI client |

---

# 9. Current system invariants

1. Backend owns conversation/knowledge truth.
2. Model unavailability is reported as failure, not fake success.
3. Reasoning output is public structured metadata, not private CoT storage.
4. Retrieved Knowledge is context data, not elevated authority.
5. `main.py` is composition; keep domain growth out of it.
6. Optional future capabilities must not be claimed by UI chrome alone.
7. Bulk corpora belong outside Git (`D:/ModelData/` when Knowledge V2 arrives).

---

# 10. Phase status snapshot

| Phase | Status | Notes |
|---|---|---|
| Phase 0 — Current-state audit | PASS | Map + drift correction + migration plan documented |
| Phase 1 — Frontend foundation | PASS | React/TS/Vite; visual tokens preserved; chat wired |
| Phase 2 — Typed configuration | PASS | Nested Settings domains + validation + feature flags |
| Phase 3 — Core module ownership | PASS | reasoning / context / model_runtime modules |
| Phase 4 — Run + Event model | PASS | Canonical RunStore wired into `/api/chat` |
| Phase 5 — Migration foundation | PASS | `schema_migrations` + baseline v1 |
| Phase 6 — Artifact system | PASS | Metadata DB + filesystem bytes + hash verify |
| Phase 7 — Knowledge V2 | PASS | Chunks, provenance, ingest states, hybrid retrieval |
| Phase 8 — Function runtime | PASS | Registry, ON_DEMAND lazy load/unload, builtins |
| Phase 9 — Capability + Gateway | PASS | Catalog, ExecutionGateway, effect ledger, WRITE needs approval_id |
| Phase 10 — Approval + Policy | PASS | Durable approvals, PolicyEngine, single-use consume |
| Phase 11 — Job Runtime | PASS | JobStore, ResourceManager, gateway-backed worker |
| Phase 12 — Observations + Effects | PASS | Durable ToolObservation + effect_ledger |
| Phase 13 — Evidence | PASS | Artifact/file/observation evidence with verify |
| Phase 14 — Context Engine | PASS | Token budget packing, dedupe, provenance |
| Phase 15 — Memory | PASS | Controlled memory store; rejects model_output trust |
| Phase 16 — Verification | PASS | Evidence-based requirements; unmeasured ≠ passed |
| Phase 17 — Agents skeleton | PASS | Gateway-only AgentRuntime; feature-flagged OFF |
| Phase 18 — Workflows | PASS | Ordered capability sequences via gateway |
| Phase 19 — Schedules | PASS | Interval job/workflow triggers + explicit tick |
| Phase 20 — Observability | PASS | In-process telemetry hub + /api/telemetry |
| Phase 21 — Neuro advisory | PASS | Flagged advisor; signal ≠ authority |
| Phase 22 — Plugins/MCP | PASS | Declarative bindings; gateway-only invoke |
| Phase 23 — Evaluation | PASS | Foundation suite; unmeasured ≠ passed |
| Phase 24 — Isolation | PASS | Requested vs effective isolation |
| Phase 25 — Training stub | PASS | Register only; start honestly unimplemented |
| Phase 26 — Browser stub | PASS | UNSUPPORTED; no fabricated pages |
| Phase 27 — Media stub | PASS | UNSUPPORTED; no fabricated media |
| Phase 28 — Voice stub | PASS | UNSUPPORTED; no fabricated audio/text |
| Phase 29 — Release gates | PASS | Local BLOCK/WARN readiness checks |
| Phase 30 — Multi-agent | PASS | Sequential shared-gateway coordinator |
| Phase 31 — Coding depth | PASS | VERIFY + CSV capability planning |
| Phase 32 — Research depth | PASS | Search + VERIFY planning notes |
| Phase 33 — Security audit | PASS | Posture checks; not a pentest |
| Phase 34 — Native stub | PASS | Native unavailable; Python-first |
| Phase 35 — Trading stub | PASS | Orders refused; no fabricated fills |
| Phase 36 — Verification reports | PASS | Durable store + list/get APIs |
| Phase 37 — Frontend API client | PASS | Expanded typed operator client |
| Phase 38 — Env/config docs | PASS | `.env.example` + backup/chaos knobs |
| Phase 39 — Backup/restore | PASS | Local snapshots; confirm required |
| Phase 40 — Metrics surface | PASS | In-process `/api/metrics` |
| Phase 41 — Chaos helpers | PASS | Default OFF; loopback-gated |
| Phase 42 — Integration harness | PASS | Approval→gateway→evidence→verify |
| Phase 43 — Operator UI | PASS | `/status` + honest Command signals |
| Phase 44 — Security hardening | PASS | Extra posture findings |
| Phase 45 — Master gates | PASS | Program summary; not prod cert |
| Phase 46 — Neuro Layer MVP | PASS | Module Manager + neuro contracts; residual GPU not wired |
| Phase 47 — Residual adapters | PASS | Deterministic toy + HF config-ready; ablations UNMEASURED |
| Phase 48 — Memory + absorb | PASS | Snapshots v12; Knowledge ingest_scan; contrastive lexical |
| Phase 49 — Cortex + recipes | PASS | CortexRuntime; training recipes registered ≠ trained |
| Phase 50 — Harden | PASS | Subprocess isolation flag; neuro release/master gates |
| Phase 51 — Neuro ops complete | PASS | Chat/context wire; absorb schedule; soak; Status UI; stubs |
| Phase 52 — Neuro Grok-level depth | PASS | Weight-backed HF opt-in; smarter cortex/critic/memory; honest recipe execute |

---

# 11. Appendix — HADES lessons (reference only)

HADES proved invariants LEVIATHAN should preserve when those subsystems are built:

```text
model output != evidence
request boolean != authority
discoverable capability != authorized capability
dispatch != completion
requested isolation != effective isolation
unmeasured != passed
retrieved context != trusted fact
neural signal != authority
```

Do not copy HADES structure wholesale. Extract invariants, design smaller LEVIATHAN contracts, implement and test.
