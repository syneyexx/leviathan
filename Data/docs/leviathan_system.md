# LEVIATHAN System Reference — Current Architecture

> Purpose: describe **how LEVIATHAN currently works**.
>
> This is the implementation truth for the repository as of Phase 0 (audit) and Phase 1 (React/TypeScript/Vite frontend foundation).
>
> HADES remains a behavioral reference for future subsystems. It is **not** implemented here.

When this document disagrees with executable code and tests, **code and tests win**.

---

# 1. What LEVIATHAN is today

LEVIATHAN is a Python-first, local-first AI system in early foundation stages.

**Implemented and real:**

- FastAPI backend composition root;
- OpenAI-compatible LLM client (LM Studio–friendly);
- SQLite persistence for conversations, messages, and Knowledge documents;
- lightweight deterministic ReasoningEngine;
- Knowledge FTS5 search with LIKE fallback;
- React + TypeScript + Vite frontend preserving the LEVIATHAN visual identity;
- typed frontend API client;
- honest LLM failure semantics (no fabricated assistant success).

**Not implemented (do not treat UI shell labels as capability):**

- Memory domains;
- Agents / Neuro / Training / Evaluation frameworks;
- native model runtime / residual-stream research.

**Implemented through Phase 14:**

- Context Engine token budgeting; Evidence; Observations; Jobs; Approvals; Capability Gateway;
- Function Runtime; Knowledge V2; Artifacts; Run/Event; migrations; Settings; React SPA.

---

# 2. Repository layout

```text
LEVIATHAN/
├── Data/
│   ├── backend/          # Python control plane (FastAPI, DB, LLM, reasoning)
│   ├── frontend/         # React/TypeScript/Vite UI
│   ├── modules/          # Reserved for future stateful domain modules
│   ├── functions/        # Reserved for on-demand cold-path helpers
│   └── docs/             # buildplan.md, leviathan_system.md, cursor.md
├── leviathan.py          # Uvicorn launcher helper
├── requirements.txt
├── .env.example
├── RUN_LEVIATHAN.bat
└── README.md
```

Ownership rule: one responsibility → one clear owner. Do not invent parallel databases, model clients, or approval systems.

---

# 3. Backend

## 3.1 Composition root — `Data/backend/main.py`

FastAPI application (`version=0.9.0-phase8`).

Responsibilities:

- lifespan DB initialize;
- `/api/*` route registration;
- wire `Database`, `ReasoningEngine`, `OpenAICompatibleLLM`;
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

## 3.3 Persistence — `Data/backend/database.py`

SQLite with WAL + foreign keys.

Tables:

- `conversations` — id, title, created_at, updated_at;
- `messages` — id, conversation_id, role, content, created_at;
- `knowledge_documents` — id, title, content, source, created_at, updated_at;
- `knowledge_fts` — FTS5 virtual table when available.

No migration version table yet (Phase 5 target). Schema is created with `CREATE TABLE IF NOT EXISTS`.

## 3.4 Reasoning — `Data/backend/reasoning.py`

`ReasoningEngine.analyze(message, has_knowledge) → ReasoningPlan`.

`ReasoningPlan` fields: `intent`, `complexity`, `use_knowledge`, `steps`.

Public summary only — **no private chain-of-thought persistence**.

Deterministic keyword/heuristic classification. Not authoritative for security or side effects.

## 3.5 Model client — `Data/backend/llm.py`

`OpenAICompatibleLLM`:

- resolve model (pinned or `/v1/models`);
- `health()`;
- `chat(history, knowledge, plan)` → `(answer, model_id)`;
- raises `LLMUnavailable` on provider failure.

Knowledge is injected into the system prompt as **untrusted context data**, labeled as such.

Context assembly currently lives here. Future Context Engine should own this.

## 3.6 Chat orchestration flow

```text
POST /api/chat
  → ensure/create conversation
  → persist user message
  → ReasoningEngine.analyze
  → optional Knowledge search
  → load history window
  → LLM.chat
  → persist assistant message OR HTTP 503 on LLMUnavailable
  → return reasoning summary + knowledge source metadata
```

Completion of a chat turn means: model returned usable text and the assistant message was persisted. There is not yet a canonical Run completion contract.

## 3.7 Knowledge V2

Owner: `Data/modules/knowledge/`.

- Documents with ingest status (`DISCOVERED`…`READY`/`FAILED`/…), content hash, provenance path/mtime, parser metadata
- Chunks with hashes; document becomes READY only after successful chunk/index write
- Lexical chunk FTS (LIKE fallback); metadata `source` filter
- `EmbeddingProvider` interface + `NullEmbeddingProvider` (no fabricated vectors)
- `HybridRetriever` — lexical now; vector fusion only when a real provider is available
- Incremental file ingest under `LEVIATHAN_DATA_ROOT` with change detection
- API: CRUD, search (`hits`+`documents`), document+chunks, `ingest/path`, `ingest/scan`

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

Reserved nav items (Research, Agents, Memory, …) toast as future steps — they are **not** fake backend pages.

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

`Data/modules/` now owns:

- `reasoning/` — ReasoningEngine
- `context/` — ContextBuilder / ContextPack
- `model_runtime/` — OpenAICompatibleLLM
- `run/` — RunStore, RunState, events
- `artifacts/` — ArtifactStore + content hashing
- `knowledge/` — KnowledgeStore V2 + HybridRetriever
- `function_runtime/` — FunctionRegistry + FunctionRuntime

`Data/functions/` holds ON_DEMAND implementations (`text_file_read`, `csv_inspector`, `pdf_parser`).
Runtime ownership: `Data/modules/function_runtime/` (registry + lazy execute/cleanup).

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
| Phase 14+ | NOT STARTED | Context Engine / Memory / Agents / … |

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
