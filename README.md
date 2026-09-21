# LEVIATHAN

LEVIATHAN is a Python-first, local-first AI system. The current foundation provides persistent chat, an OpenAI-compatible LLM connection, a small reasoning layer, local SQLite Knowledge, and a React/TypeScript/Vite frontend that preserves the LEVIATHAN visual identity.

## Repository layout

```text
Data/
├── backend/          # Python runtime, API, LLM, reasoning, database, tests
├── frontend/         # React + TypeScript + Vite UI
├── modules/          # Future stateful domain modules
├── functions/        # Future on-demand cold-path functions
└── docs/             # buildplan, system reference, cursor map
```

## Architecture (current)

```text
React SPA (Data/frontend)
   ↓ typed API client
FastAPI /api/chat
   ↓
ReasoningEngine
   ↓
Knowledge retrieval (SQLite + FTS5)
   ↓
OpenAI-compatible LLM
   ↓
Persisted conversation + response
```

## Run

Python 3.11+ and Node.js 20+ are recommended.

### Windows (recommended)

1. Double-click `installer.bat` once — creates `.venv`, installs Python + npm deps, builds the frontend, and creates `.env`.
2. Double-click `run_leviathan.bat` to start the app.

### Manual

```bash
python3 -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env

cd Data/frontend
npm install
npm run build
cd ../..

python3 -m uvicorn Data.backend.main:app --host 127.0.0.1 --port 8765
```

Open:

- Dashboard: `http://127.0.0.1:8765/`
- Chat: `http://127.0.0.1:8765/chat`
- API docs: `http://127.0.0.1:8765/docs`

Frontend development (API proxy to backend):

```bash
# terminal 1 — backend
python3 -m uvicorn Data.backend.main:app --host 127.0.0.1 --port 8765

# terminal 2 — Vite
cd Data/frontend && npm run dev
```

## Frontend gates

```bash
cd Data/frontend
npm run typecheck
npm run lint
npm run test
npm run build
```

## Backend tests

```bash
python3 -m unittest Data.backend.tests.test_foundation -v
```

## LLM configuration

Default endpoint: `http://127.0.0.1:1234/v1`

See `.env.example` for `LEVIATHAN_LLM_*` and related variables. When `LEVIATHAN_LLM_MODEL` is empty, LEVIATHAN discovers the first model from `/v1/models`.

Unavailable models produce HTTP 503 — no fabricated assistant success.

## Documentation

- `Data/docs/buildplan.md` — chronological build record (newest first)
- `Data/docs/leviathan_system.md` — how LEVIATHAN currently works
- `Data/docs/cursor.md` — repository ownership map

## Current boundary

Implemented: chat, LLM client, Knowledge CRUD/search, lightweight reasoning, React/Vite UI.

Not yet: tools/execution gateway, approvals, Run runtime, agents, Memory, Evidence, Neuro, training/eval frameworks.
