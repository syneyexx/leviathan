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
└── RUN_LEVIATHAN.bat
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
| `Data/modules/reasoning/` | ReasoningEngine |
| `Data/modules/context/` | ContextBuilder |
| `Data/modules/model_runtime/` | OpenAICompatibleLLM |
| `Data/modules/run/` | RunStore / events / transitions |
| `Data/modules/artifacts/` | ArtifactStore |
| `Data/modules/knowledge/` | KnowledgeStore / HybridRetriever |
| `Data/modules/function_runtime/` | FunctionRegistry / FunctionRuntime |
| `Data/modules/execution/` | CapabilityCatalog / ExecutionGateway |
| `Data/modules/approvals/` | PolicyEngine / ApprovalStore / ApprovalService |
| `Data/modules/jobs/` | JobStore / JobRuntime / ResourceManager |
| `Data/modules/observations/` | ToolObservation / Effect ledger |
| `Data/modules/evidence/` | EvidenceStore / EvidenceService |
| `Data/modules/memory/` | MemoryStore |
| `Data/modules/verification/` | VerificationEngine |
| `Data/modules/agents/` | AgentRuntime (feature-flagged) |
| `Data/modules/workflows/` | WorkflowStore / WorkflowRuntime |
| `Data/modules/schedules/` | ScheduleStore / ScheduleRunner |
| `Data/modules/observability/` | ObservabilityHub |
| `Data/modules/neuro/` | NeuroAdvisor (advisory only) |
| `Data/modules/plugins/` | PluginRegistry / MCP stubs |
| `Data/modules/evaluation/` | EvaluationHarness |
| `Data/modules/isolation/` | IsolationGuard |
| `Data/modules/training/` | TrainingRegistry stub |

## Tests

`Data/backend/tests/` — foundation, config, context, run, migrations.

---

# Frontend ownership

## Entry

- `src/main.tsx` — React mount + router + toast provider
- `src/App.tsx` — routes `/`, `/chat`, `/chat.html` redirect

## Pages

- `src/pages/CommandPage.tsx` — dashboard/Command shell
- `src/pages/ChatPage.tsx` — real chat against `/api/*`

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
| Workflows | `Data/modules/workflows/` |
| Schedules | `Data/modules/schedules/` |
| Observability | `Data/modules/observability/` |
| Neuro | `Data/modules/neuro/` (advisory; feature-flagged) |
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

**Real today:** dashboard + chat UI, FastAPI, LLM client, SQLite chat/Knowledge, lightweight reasoning, React/Vite frontend foundation.

**Not real yet:** tools, execution gateway, approvals, Run runtime, agents, Memory, Evidence, Neuro, training, jobs, migrations framework.
