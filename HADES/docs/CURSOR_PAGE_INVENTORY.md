# HADES Cursor page inventory

Purpose: give Cursor the exact page boundary before it searches broader code. This is an inventory only; it is not a TODO list, roadmap, or implementation plan.

## Routing and rendering

- Browser entry: `main.tsx` -> `components/hades/hades-app.tsx` (`HadesApp`).
- Canonical page IDs and navigation live in `components/hades/hades-app.tsx` (Werk / Kennis / Systeem).
- Sole product shell: `components/hades/lux/lux-shell.tsx` wrapping `classicPages` from `hades-app.tsx`.
- Obsidian / BETA / BETA 2 trees are removed.
- Shared frontend API contract: `lib/hades-api.ts`.
- Shared page UI helpers: `components/hades/ui.tsx`; generic primitives: `components/ui/`.
- Shared styling: `app/globals.css` + `components/hades/styles/lux/`.

## Page ownership map

| Page ID | UI entry points | Primary backend / domain owners |
|---|---|---|
| `chat` | `pages/chat-reasoning-page.tsx` -> `pages/chat-page.tsx`; `features/chat/` | `backend/main.py` chat/retrieval/tool loop, `backend/reasoning/`, `backend/capability_intel/`, `backend/database.py`, `backend/lm_studio.py`, voice/speech helpers |
| `tasks` | `pages/tasks-page.tsx`; `execution-completion-banner.tsx` | `backend/main.py` TaskRunner/task routes, `backend/run_lifecycle.py`, `backend/platform_db.py`, `backend/schedules.py`, `backend/voice_tasks.py` |
| `mission-control` | `pages/mission-control-page.tsx`; `features/project-continuity-panel.tsx` | `backend/gen2/routes.py`, `backend/gen2/services.py`, `backend/gen2/store.py`, `backend/project_continuity.py` |
| `workflows` | `pages/workflows-page.tsx` | Gen2 workflow routes/services/store under `backend/gen2/` |
| `agents` | `pages/agents-page.tsx`; `features/agents/` | agent/work routes in `backend/main.py`, `backend/platform_db.py`, `backend/practice_api.py`, specialist contracts under `backend/reasoning/`, `backend/capability_intel/` |
| `coding-agent` | `pages/coding-agent-page.tsx`; `coding-agent-helpers.ts`; `features/agent-ux/` | `backend/coding_agent.py`, `coding_jobs.py`, `coding_job_control.py`, `coding_investigate.py`, `coding_requirement_map.py`, `coding_delivery.py`, `coding_autonomy.py`, symbol/LSP helpers |
| `research` | `pages/research-page.tsx` | `backend/platform_services_core.py` ResearchRunner/WebResearchService, `backend/platform_db.py`, research routes in `backend/main.py`, `backend/research_conflicts.py` |
| `trading` | `pages/trading-page.tsx` (Trading Lab tab shell), `pages/trading-lab/*` | `backend/trading_lab/`, `backend/trading_service.py`, `backend/platform_db.py`, trading routes in `backend/main.py` |
| `brain` | `pages/brain-page.tsx` plus brain graph/inspector helpers and CSS | `backend/brain_routes.py`, `backend/brain_graph.py`, brain persistence in `backend/database.py` |
| `memory` | `pages/memory-page.tsx` | memory repository methods in `backend/database.py`, memory routes in `backend/main.py` |
| `files` | `pages/files-page.tsx` | files/knowledge routes and services |
| `models` | `pages/models-page.tsx` | `backend/models_routes.py`, `backend/model_discovery.py`, `backend/lm_studio.py` |
| `plugins` | `pages/plugins-page.tsx` | PluginManager / capability intel / platform_db |
| `mcp` | `pages/mcp-page.tsx` | `backend/mcp_host/` |
| `media` | `pages/media-page.tsx` | media routes/services |
| `settings` | `pages/settings-page.tsx`; `control-center.tsx`; `native-runtime-panel.tsx` | `backend/database.py`, `backend/config.py`, settings routes, `backend/control/`, `backend/native_routes.py` |

Style docs: `docs/UI_STYLE_SYSTEM.md`, concept: `docs/design/HADES_LUX_CONCEPT.md`.
