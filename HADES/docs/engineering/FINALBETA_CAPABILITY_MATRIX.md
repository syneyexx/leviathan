# FINALBETA Capability Matrix

**Baseline SHA:** `3a89df0c77318c738c5fcc41f8cfbcd01f32bec3`  
**Branch:** `cursor/finalbeta-production-wiring-0721`  
**Updated:** 2026-09-18 (production wiring pass — living document)

Status legend:

| Status | Meaning |
|---|---|
| `LIVE_E2E_PROVEN` | Real UI → API → backend → verified effect |
| `LIVE` | Wired to real API; host E2E not fully proven here |
| `PARTIAL` | Mixed live + local/presentation state |
| `MOCK` | Production page still driven by mock runtime data |
| `BLOCKED` | Capability exists; policy/approval/env blocks |
| `NOT_IMPLEMENTED` | No backend owner yet — must not fake |
| `ENV_DEPENDENT` | Correct wiring; needs LM Studio / GPU / credentials / etc. |

Canonical route list: `components/hades/finalbeta/routes.ts` → `FINALBETA_PAGES`.

---

## Hades AI

| route | page file | data source | status | API / backend owner | notes |
|---|---|---|---|---|---|
| `login` | `pages/login-page.tsx` | local entry | `PARTIAL` | none (local session) | Local HADES has no real auth; must not fake security |
| `dashboard` | `pages/dashboard-page.tsx` | `useDashboardLive` | `LIVE` | `/health`, `/agents`, native, training hardware | Metrics show unavailable honestly |
| `chat` | `pages/chat-page.tsx` | `useChatLive` + shared chat runtime | `LIVE` / `ENV_DEPENDENT` | `/conversations`, send/stream, tool engine | Shared runtime; tools need LM + policy |
| `coding` | `pages/coding-page.tsx` | `useCodingLive` + shared coding runtime | `LIVE` / `ENV_DEPENDENT` | `/coding/*`, CodingAgent | Recent A–Z repair on main |
| `tasks` | `pages/tasks-page.tsx` + `pages/tasks/*` | `useHadesTasks` | `LIVE` | `/tasks`, Work Runtime | Shared source for kanban/list tabs |
| `mission-control` | alias → `tasks` | — | alias | — | Redirect only |

## LLM

| route | page file | data source | status | API / backend owner | notes |
|---|---|---|---|---|---|
| `models` | `pages/models-page.tsx` | `hadesApi.models` | `LIVE` / `ENV_DEPENDENT` | `/models` | Needs LM Studio for discovery |
| `model-training` | `pages/model-training-page.tsx` + tabs | **mocks/model-training** | `MOCK` | training / neural APIs where present | Unavailable features must not fake |
| `agents` | `pages/agents-page.tsx` | `hadesApi.agents` | `LIVE` | `/agents` | |
| `llm-stats` | `pages/llm-stats-page.tsx` | `useHadesLlmStats` | `LIVE` / `ENV_DEPENDENT` | `/models`, gateway, `/agents`, `/tasks`, health | Honest empty when LM offline |

## Media Control

| route | page file | data source | status | API / backend owner | notes |
|---|---|---|---|---|---|
| `media` | `pages/media-page.tsx` | `useHadesMedia` | `LIVE` / `ENV_DEPENDENT` | `/media/overview` + channels/projects/trends | Honest empty; no fake reach |
| `youtube` / `tiktok` / `instagram` / `facebook` | `pages/media-channels-page.tsx` | **mocks/media-channels** | `MOCK` | `/media/channels` | AUTH_REQUIRED when unset |
| `media-queue` | `pages/media-queue-page.tsx` | `useHadesMedia` | `LIVE` | `/media/publish` + overview queue | Honest empty queue |
| `media-viral` | `pages/media-viral-page.tsx` | `useHadesMedia` | `LIVE` | `/media/trends` | Discover wired; no fake momentum |
| `media-calendar` | `pages/media-calendar-page.tsx` | `useHadesMedia` | `LIVE` | projects + publish queue | Calendar from live dates |
| `media-analytics` | `pages/media-analytics-page.tsx` | `useHadesMedia` | `LIVE` | `/media/analytics` | Honest empty until posts exist |
| `media-library` | `pages/nav-stubs.tsx` | stub | `MOCK` / `NOT_IMPLEMENTED` | `/media/assets` | |
| `media-personas` | `pages/nav-stubs.tsx` | stub | `MOCK` / `NOT_IMPLEMENTED` | TBD | |

## TradingCenter

| route | page file | data source | status | API / backend owner | notes |
|---|---|---|---|---|---|
| `trading` | `pages/trading-page.tsx` | `useHadesTrading` | `LIVE` | `/trading/dashboard`, `/trading/lab/overview` | Paper/sim only; never fake live balances |
| `trading-marketdata` | `pages/trading-marketdata-page.tsx` | `useHadesTrading` | `LIVE` | bars + lab instruments/datasets | No fake orderbook/feeds |
| `trading-strategies` | `pages/trading-strategies-page.tsx` | `useHadesTrading` | `LIVE` | dashboard strategies | Paper/lab catalog |
| `trading-simulation` | `pages/nav-stubs.tsx` | stub | `MOCK` | lab runs | |
| `trading-portfolio` | `pages/trading-portfolio-page.tsx` | `useHadesTrading` | `LIVE` | paper positions | Paper only |
| `trading-paper` | `pages/trading-paper-page.tsx` | `useHadesTrading` | `LIVE` | `/trading/*` paper | Never fake live balances |
| `trading-broker` | `pages/trading-broker-page.tsx` | honest gate | `NOT_IMPLEMENTED` / protected | must stay opt-in | No mock balances |

## Onderzoek & Kennis

| route | page file | data source | status | API / backend owner | notes |
|---|---|---|---|---|---|
| `research` | `pages/research-page.tsx` | `useHadesResearch` | `LIVE` / `ENV_DEPENDENT` | `/research`, ResearchRunner | network_policy / robots respected |
| `brain` | `pages/brain-page.tsx` | `useHadesBrain` | `LIVE` | `/brain`, layout APIs | Empty graph honest |
| `memory` | `pages/memory-page.tsx` | `useHadesMemory` | `LIVE` | `/memories` | |
| `knowledge` | `pages/knowledge-page.tsx` | `useHadesKnowledge` | `LIVE` | `/knowledge` | Presentation chrome may remain |
| `evidence` | `pages/evidence-page.tsx` | `useHadesEvidence` | `LIVE` | `/claims`, `/knowledge/pack` | Honest confidence; empty OK |
| `files` | `pages/files-page.tsx` | `useHadesFiles` | `LIVE` | `/files` | Workspaces/index from API; no fake storage totals |

## Plugin & Runtime

| route | page file | data source | status | API / backend owner | notes |
|---|---|---|---|---|---|
| `workflows` | `pages/workflows-page.tsx` | `useHadesWorkflows` | `LIVE` | Gen2 `/workflows` validate/dry-run | Honest empty list; canvas from live steps |
| `performance` | `pages/performance-page.tsx` | `useDashboardLive` | `LIVE` / `PARTIAL` | health/native metrics | Disk/net charts honest empty until API exists |
| `tools` (Plugins) | `pages/tools-page.tsx` | `useHadesPlugins` | `LIVE` | `/plugins`, PluginManager | Ready ≠ enabled surfaced |
| `mcp` | `pages/mcp-page.tsx` | `useHadesMcp` | `LIVE` | `/mcp/*`, mcp_host | No fake online servers |
| `tasks` | `pages/tasks-page.tsx` + tabs | `useHadesTasks` | `LIVE` | `/tasks`, Work Runtime | Shared source for tabs |
| `models` | `pages/models-page.tsx` | `hadesApi.models` | `LIVE` / `ENV_DEPENDENT` | `/models` | Needs LM Studio for discovery |
| `agents` | `pages/agents-page.tsx` | `hadesApi.agents` | `LIVE` | `/agents` | |
| `memory` | `pages/memory-page.tsx` | `useHadesMemory` | `LIVE` | `/memories` | |
| `settings-*` (core) | `finalbeta-settings-page.tsx` | `useHadesSettings` | `LIVE` / `PARTIAL` | `/settings` | Policies live; some UI chrome presentation-only |

## Instellingen

| route | page file | data source | status | API / backend owner | notes |
|---|---|---|---|---|---|
| `settings-general` | `pages/finalbeta-settings-page.tsx` | `useHadesSettings` | `LIVE` / `PARTIAL` | `/settings`, control plane | Policies/autonomy live; some chrome presentation-only |
| `settings-interface` | same | mocks + ui_style | `PARTIAL` | `/settings` | |
| `settings-llm-behavior` | same | mostly local | `PARTIAL` | reasoning_profile, max_tool_rounds, … | |
| `settings-security` | same | mostly local | `PARTIAL` | file/network/subprocess policies | |
| `settings-storage` | same | mostly local | `PARTIAL` | storage paths | |
| `settings-llm-studio` | `nav-stubs.tsx` | stub | `MOCK` | LM Studio settings | |
| `settings-benchmarks` | stub | stub | `MOCK` / `NOT_IMPLEMENTED` | gen2 evals if wired | |
| `settings-python` | stub | stub | `MOCK` | runtime | |
| `settings-logs` | stub | stub | `MOCK` | logs | |
| `settings-backups` | stub | stub | `MOCK` / `NOT_IMPLEMENTED` | | |
| `settings` / `system` | aliases | — | alias | — | → general / console |

---

## Production mock import inventory (pages)

Files currently importing `../mocks` or `../../mocks` for **presentation chrome** (allowlisted) or remaining runtime mocks:

**Allowlisted presentation-only:** `tools`, `mcp`, `settings`, `tasks`, `memory`, `knowledge`, `research`, `model-training` (tab ids).

**Still mock runtime (subpages / stubs):**
- Media channel pixel pages (`media-channels`) + library/personas stubs
- Trading simulation stub; Model Training panels; settings stubs/console

**Already live / honest-gated:** overviews + media queue/viral/calendar/analytics; trading paper/strategies/marketdata/portfolio; broker page is opt-in gate (no fake balances); plus Chat/Coding/Dashboard/Files/Brain/Evidence/Research/Performance/Stats/Workflows/Plugins/Settings/MCP/Tasks/Memory/Knowledge/Models/Agents.

---

## Shared architecture targets

```
FINALBETA page
  → features/*/hooks (or finalbeta/hooks)
    → hadesApi / lib/api/*
      → FastAPI routes
        → PluginManager / Work Runtime / KnowledgeService / mcp_host / …
```

Do not duplicate business logic in TSX. Lux remains a consumer of the same backends.
