# Architecture hotspots

Measured on frontier baseline (`artifacts/baselines/frontier_hardening_before.json`).

## Largest Python modules

| LOC | Path | Responsibility (current) |
|---|---|---|
| ~5939 | `backend/main.py` | FastAPI app, chat/work orchestration, many routes |
| ~2973 | `backend/platform_services_core.py` | PluginManager, research runners, knowledge |
| ~2305 | `backend/gen2/mission_control.py` | Mission IR / compiler / acceptance |
| ~2138 | `backend/gen2/store.py` | Gen2 SQLite persistence |
| ~2034 | `backend/platform_db.py` | Platform tables/migrations |
| ~1687 | `backend/gen2/workflows.py` | Workflow definitions/promote |
| ~1678 | `backend/database.py` | Core SQLite |
| ~1491 | `backend/capability_routes.py` | Capability HTTP surface |

## Extraction strategy (incremental)

Do **not** one-shot rewrite. For each extraction:

1. characterization tests
2. extract stable boundary
3. focused tests
4. API compatibility
5. logical commit

Preferred first extractions (already partially done):

- `runtime/execution_gateway.py` — policy skip / fail-closed
- `runtime/effect_ledger.py` — at-least-once effect intents
- `brain_routes.py` / `models_routes.py` / `app_lifecycle.py` (existing)

Next candidates:

1. Chat routes + `send_message` helpers → `backend/api/chat_routes.py`
2. Plugin routes → `backend/api/plugin_routes.py`
3. TaskRunner → `backend/services/task_runner.py`
4. Platform DB migrations vs domain methods split

## Maintainability risk

Circular imports are the main failure mode. Prefer:

- constructors / explicit deps over process globals
- thin FastAPI routers that call services
- keep `PluginManager.invoke` as the plugin side-effect kernel
