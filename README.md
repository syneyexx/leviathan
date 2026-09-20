# LEVIATHAN

LEVIATHAN is being rebuilt from the ground up. The current repository contains the visual shell plus **Step 1 of the runtime**: a working persistent chat connected to an OpenAI-compatible LLM, a small reasoning/planning layer, and a local SQLite knowledge system.

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

The reasoning layer is deliberately small. It classifies the request, estimates basic complexity, decides whether local knowledge should be retrieved, and produces a compact execution plan. It is a stable seam for a later planner/router; it is **not** model chain-of-thought and it has no authority over security or side effects.

## Included in Step 1

- Existing LEVIATHAN dashboard remains intact.
- Chat page is connected to the backend.
- Persistent conversations and messages.
- New-chat and conversation switching.
- OpenAI-compatible LLM connection.
- LM Studio model auto-discovery when `LEVIATHAN_LLM_MODEL` is empty.
- Lightweight reasoning metadata (`intent`, `complexity`, `steps`).
- SQLite knowledge database.
- FTS5 full-text knowledge retrieval with a LIKE fallback.
- Knowledge CRUD/search API.
- Truthful LLM failure handling: no fake assistant response is persisted when the model server is unavailable.

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
python -m uvicorn backend.main:app --host 127.0.0.1 --port 8765 --reload
```

Open:

- Dashboard: `http://127.0.0.1:8765/`
- Chat: `http://127.0.0.1:8765/chat.html`
- API docs: `http://127.0.0.1:8765/docs`

`backend/config.py` automatically loads the repository-root `.env` file when it exists.

## LLM configuration

Default endpoint:

```text
http://127.0.0.1:1234/v1
```

Important environment variables:

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

## Knowledge API

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

The database is created automatically at `data/leviathan.db` by default.

## Tests

```bash
python -m unittest backend.tests.test_foundation -v
```

The foundation tests cover conversation persistence, knowledge retrieval, and the deterministic reasoning seam. Live LLM behavior requires an actual configured model server and is therefore not represented as a fake passing unit test.

## Current boundary

Step 1 does **not** add tools, autonomous execution, MCP, agents, web research, neural learning, trading, or workflow orchestration. Those should be layered on top of this runtime deliberately in later steps instead of being mixed into the first LLM/chat foundation.
