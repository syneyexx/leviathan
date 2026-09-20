# LEVIATHAN

LEVIATHAN is a Python-first AI system being rebuilt from the ground up. Step 1 provides a working persistent chat, an OpenAI-compatible LLM connection, a small reasoning layer, and a local SQLite knowledge system.

## Repository layout

```text
Data/
├── backend/          # Python runtime, API, LLM, reasoning, database, tests
├── frontend/         # Existing dashboard/chat HTML, CSS, JS and assets
├── modules/          # Future larger Python feature modules
└── functions/        # Future reusable Python functions/helpers
```

The system/runtime logic belongs in Python. The existing frontend remains a static browser UI served by the Python FastAPI backend.

## Step 1 architecture

```text
Browser chat
   ↓
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

The reasoning layer is deliberately small. It classifies the request, estimates basic complexity, decides whether local knowledge should be retrieved, and produces a compact execution plan. It is a clean seam for later expansion; it is not model chain-of-thought and it has no authority over security or side effects.

## Included in Step 1

- Existing LEVIATHAN dashboard and chat UI under `Data/frontend/`.
- Python FastAPI backend under `Data/backend/`.
- Persistent conversations and messages.
- New-chat and conversation switching.
- OpenAI-compatible LLM connection.
- LM Studio model auto-discovery when `LEVIATHAN_LLM_MODEL` is empty.
- Lightweight reasoning metadata (`intent`, `complexity`, `steps`).
- SQLite knowledge database.
- FTS5 full-text knowledge retrieval with LIKE fallback.
- Knowledge CRUD/search API.
- Truthful LLM failure handling: no fake assistant response is persisted when the model server is unavailable.
- Reserved Python namespaces for `Data/modules/` and `Data/functions/`.

## Run

Python 3.11+ is recommended.

```bash
python -m venv .venv
```

Windows:

```bash
.venv\Scripts\activate
pip install -r requirements.txt
copy .env.example .env
RUN_LEVIATHAN.bat
```

macOS/Linux:

```bash
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
python -m uvicorn Data.backend.main:app --host 127.0.0.1 --port 8765 --reload
```

Open:

- Dashboard: `http://127.0.0.1:8765/`
- Chat: `http://127.0.0.1:8765/chat.html`
- API docs: `http://127.0.0.1:8765/docs`

`Data/backend/config.py` loads the repository-root `.env` file when it exists.

## LLM configuration

Default endpoint:

```text
http://127.0.0.1:1234/v1
```

Environment variables:

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

When `LEVIATHAN_LLM_MODEL` is empty, LEVIATHAN calls `/v1/models` and uses the first model returned by the configured server.

## Knowledge database

The database is created automatically at:

```text
Data/backend/data/leviathan.db
```

Add knowledge:

```bash
curl -X POST http://127.0.0.1:8765/api/knowledge \
  -H "Content-Type: application/json" \
  -d '{"title":"Leviathan architecture","content":"LEVIATHAN is rebuilt around a clean runtime.","source":"manual"}'
```

Search:

```text
GET /api/knowledge/search?q=architecture
```

## Tests

```bash
python -m unittest Data.backend.tests.test_foundation -v
```

The foundation tests cover conversation persistence, knowledge retrieval, and the deterministic reasoning seam. Live LLM behavior requires an actual configured model server and is not represented as a fabricated passing unit test.

## Current boundary

Step 1 does not yet add tools, autonomous execution, MCP, agents, web research, neural learning, trading, or workflow orchestration. Those will be added deliberately in later steps on top of the Python runtime.
