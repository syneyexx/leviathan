# Cursor Guide — LEVIATHAN Repository Map

This file tells Cursor where LEVIATHAN functionality belongs and where to look before changing anything.

## Primary rule

LEVIATHAN is a **Python-first** project.

The backend/control plane lives under:

`Data/backend/`

The browser UI lives under:

`Data/frontend/`

Reusable feature modules live under:

`Data/modules/`

Small reusable helpers/functions live under:

`Data/functions/`

Project architecture and build documentation lives under:

`Data/docs/`

Do not recreate parallel root-level `backend`, `frontend`, `assets`, `css`, or `js` structures.

---

# Current repository structure

```text
LEVIATHAN/
├── Data/
│   ├── __init__.py
│   ├── backend/
│   │   ├── __init__.py
│   │   ├── config.py
│   │   ├── database.py
│   │   ├── llm.py
│   │   ├── main.py
│   │   ├── reasoning.py
│   │   └── tests/
│   │       ├── __init__.py
│   │       └── test_foundation.py
│   ├── frontend/
│   │   ├── index.html
│   │   ├── chat.html
│   │   ├── assets/
│   │   ├── css/
│   │   └── js/
│   ├── functions/
│   │   ├── __init__.py
│   │   └── README.md
│   ├── modules/
│   │   ├── __init__.py
│   │   └── README.md
│   └── docs/
│       ├── leviathan_system.md
│       ├── cursor.md
│       └── buildplan.md
├── .env.example
├── .gitignore
├── requirements.txt
├── README.md
└── RUN_LEVIATHAN.bat
```

---

# What each backend file does

## `Data/backend/main.py`

Main FastAPI application and current API composition root.

Current responsibilities:

- initialize the database at application startup;
- expose health endpoint;
- expose conversation endpoints;
- expose `/api/chat`;
- expose Knowledge CRUD/search endpoints;
- connect ReasoningEngine, Database and LLM client;
- serve the dashboard and chat frontend;
- mount frontend static assets.

When adding a new subsystem, avoid placing all of its logic directly in `main.py`.

`main.py` should increasingly become a composition/API layer rather than a large application monolith.

## `Data/backend/config.py`

Central environment/configuration loader.

Look here for:

- project paths;
- `Data/backend` path;
- `Data/frontend` path;
- LLM base URL;
- selected model;
- API key;
- LLM timeout;
- database path;
- Knowledge retrieval settings;
- reasoning enable/disable state.

New global runtime configuration should normally be declared here or later in a dedicated configuration subsystem.

Do not hardcode provider URLs or database paths inside feature modules.

## `Data/backend/database.py`

Current SQLite persistence layer.

Current responsibilities include:

- database initialization;
- conversations;
- messages;
- conversation titles;
- Knowledge documents;
- Knowledge FTS index;
- Knowledge search;
- Knowledge deletion.

If persistence grows substantially, split this into repositories/services later instead of making this file indefinitely larger.

Future likely repositories:

- ConversationRepository;
- KnowledgeRepository;
- RunRepository;
- MemoryRepository;
- ArtifactRepository;
- EvidenceRepository;
- ApprovalRepository.

## `Data/backend/llm.py`

OpenAI-compatible model client.

Current responsibilities:

- model discovery using `/v1/models` when no model is pinned;
- model health/status;
- chat completion calls;
- provider request formatting;
- injecting selected local Knowledge into the model context;
- reporting provider/model failures honestly.

This file should remain provider-facing.

Do not put task lifecycle, permissions, database writes or tool execution authority into the LLM client.

## `Data/backend/reasoning.py`

Current lightweight deterministic reasoning/planning seam.

Current responsibilities:

- basic request intent classification;
- rough complexity classification;
- deciding whether local Knowledge retrieval is useful;
- creating a compact public execution-plan summary.

This is intentionally simple in Step 1.

Future advanced planning/routing should evolve behind a structured contract instead of scattering keyword conditions throughout the application.

The current reasoning output is not private model chain-of-thought.

## `Data/backend/tests/test_foundation.py`

Step 1 regression tests.

Currently checks:

- conversation persistence;
- message persistence;
- Knowledge retrieval;
- basic reasoning behavior.

Every core behavior added to LEVIATHAN should gain tests close to the subsystem that owns it.

---

# Frontend map

## `Data/frontend/index.html`

Current LEVIATHAN dashboard/Command page.

This is primarily the visual dashboard shell.

Do not move backend logic into this file.

## `Data/frontend/chat.html`

Current LEVIATHAN chat interface.

Contains the visual chat shell, conversation rail, composer and context/tool/agent presentation areas.

The backend remains authoritative for actual conversation/model state.

## `Data/frontend/js/chat.js`

Client-side chat behavior.

Current responsibilities include connecting the chat page to the real backend APIs, loading conversations, sending messages, rendering responses and handling model/connection state.

If backend response contracts change, inspect this file before changing endpoint shapes.

## `Data/frontend/js/app.js`

Shared/demo shell behavior for the visual interface, navigation and clock interactions.

## `Data/frontend/css/`

- `tokens.css`: visual design tokens;
- `leviathan.css`: shared shell/dashboard styling;
- `chat.css`: chat-specific styling.

## `Data/frontend/assets/`

Current static images used by the dashboard and chat shell.

---

# `Data/modules/`

Use this for larger optional or domain-specific subsystems.

Examples of future modules:

```text
Data/modules/
├── coding/
├── research/
├── neural/
├── agents/
├── automation/
├── trading/
├── media/
├── plugins/
└── mcp/
```

A module should own substantial domain behavior.

Modules should depend on explicit backend/core contracts and should not directly manipulate frontend internals.

Avoid creating a module for every tiny helper.

---

# `Data/functions/`

Use this for small reusable Python helpers that do not justify a full subsystem.

Possible future examples:

```text
Data/functions/
├── text.py
├── hashing.py
├── ids.py
├── time.py
├── paths.py
└── validation.py
```

Functions here should ideally be:

- small;
- deterministic where possible;
- easy to test;
- low-coupling;
- reusable across modules.

Do not put large stateful managers into `Data/functions/`.

---

# `Data/docs/`

## `leviathan_system.md`

Reference architecture document describing how HADES currently works and which architectural lessons/invariants should inform LEVIATHAN.

Read this before rebuilding a major HADES-equivalent subsystem.

## `cursor.md`

This file. Repository navigation and implementation placement rules for Cursor.

## `buildplan.md`

Chronological build record and current implementation boundary for LEVIATHAN.

Update it after major completed build phases.

---

# Root files

## `RUN_LEVIATHAN.bat`

Windows launcher.

Current runtime entry point:

```text
Data.backend.main:app
```

## `requirements.txt`

Python dependencies for the runtime.

Current stack includes:

- FastAPI;
- Uvicorn;
- HTTPX;
- Pydantic;
- python-dotenv.

Avoid adding dependencies without a concrete need.

## `.env.example`

Reference environment configuration.

Current important variables include:

```text
LEVIATHAN_LLM_BASE_URL
LEVIATHAN_LLM_MODEL
LEVIATHAN_LLM_API_KEY
LEVIATHAN_LLM_TIMEOUT_SECONDS
LEVIATHAN_DATABASE_PATH
LEVIATHAN_KNOWLEDGE_TOP_K
LEVIATHAN_MAX_HISTORY_MESSAGES
LEVIATHAN_REASONING_ENABLED
```

## `.gitignore`

Keeps local environment/runtime artifacts such as `.env`, virtualenvs, Python caches and SQLite runtime files out of Git.

---

# Current runtime flow

```text
Data/frontend/chat.html
        │
        ▼
Data/frontend/js/chat.js
        │
        ▼
POST /api/chat
        │
        ▼
Data/backend/main.py
        │
        ├── ReasoningEngine
        │      └── Data/backend/reasoning.py
        │
        ├── Knowledge retrieval
        │      └── Data/backend/database.py
        │
        ├── LLM call
        │      └── Data/backend/llm.py
        │
        └── conversation persistence
               └── Data/backend/database.py
```

---

# Where to place future functionality

Use this rule before creating a new file.

| Functionality | Preferred location |
|---|---|
| API route/composition | `Data/backend/` |
| provider/model communication | `Data/backend/` or future backend provider package |
| database repository/storage | `Data/backend/` initially; later dedicated storage package |
| substantial feature subsystem | `Data/modules/<feature>/` |
| small reusable pure helper | `Data/functions/` |
| dashboard/chat browser UI | `Data/frontend/` |
| architecture/build documentation | `Data/docs/` |
| tests for backend/core behavior | near backend/module test package |

---

# Rules for Cursor changes

1. **Inspect before changing.** Read the owning file and tests first.
2. **Python first.** Core runtime/orchestration belongs in Python.
3. **Do not recreate HADES debt.** HADES is a behavioral reference, not a structure to copy blindly.
4. **Do not make `main.py` a god file.** New substantial logic gets a service/module.
5. **One source of truth.** Backend state owns execution/completion; frontend reflects it.
6. **No fake success.** If a model/provider/tool is unavailable, report failure honestly.
7. **No silent fallback that changes security semantics.** Requested and effective execution must be distinguishable later when execution subsystems arrive.
8. **Model text is not execution evidence.** Do not mark real actions complete only because the LLM says they happened.
9. **Persistent data belongs under the configured data path, not in Git.**
10. **Add tests with behavior.** Important control-plane behavior must be testable.
11. **Update `Data/docs/buildplan.md` after major completed phases.**
12. **Update `Data/docs/leviathan_system.md` when the intended architecture changes materially.**

---

# HADES lookup rule

When implementing functionality that existed in HADES:

1. inspect current HADES behavior;
2. inspect its regression tests;
3. identify the useful invariant;
4. identify obsolete/duplicated structure;
5. design the LEVIATHAN contract first;
6. implement the smallest clean LEVIATHAN version;
7. add tests;
8. only then expand.

Do not copy large HADES subsystems wholesale simply because they already exist.

---

# Immediate Step 1 boundary

LEVIATHAN currently supports:

- dashboard UI;
- real chat UI;
- Python/FastAPI runtime;
- OpenAI-compatible LLM;
- LM Studio-friendly model discovery;
- persistent SQLite conversations;
- simple reasoning metadata;
- local Knowledge storage/retrieval.

It does **not** yet have full production implementations of:

- tools/capabilities;
- execution gateway;
- approval service;
- Work runtime;
- Coding Agent;
- Research Agent;
- Memory;
- Evidence/Artifacts;
- Neural;
- plugins;
- MCP;
- native runtime;
- workflows/schedules;
- trading/media.

Treat those as future build phases, not as hidden existing functionality.
