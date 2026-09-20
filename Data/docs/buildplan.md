# LEVIATHAN Build Plan

This document records what has been completed so far, the current system boundary, and the intended direction for future build phases.

LEVIATHAN is a **Python-first rebuild from the ground up**. HADES is used as a functional/architectural reference, not as a codebase to copy wholesale.

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
