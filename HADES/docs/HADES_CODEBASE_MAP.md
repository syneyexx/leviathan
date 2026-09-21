# HADES codebase map

Use this map to avoid re-reading the full repository for every task.

## Root entry points

| File | Purpose |
|---|---|
| `main.tsx` | React browser entry point; imports global CSS and mounts HADES. |
| `components/hades/hades-app.tsx` | Application shell, navigation, top-level health/settings integration. |
| `lib/hades-api.ts` | Canonical frontend API types and HTTP client. |
| `app/globals.css` | Main HADES styling. Large file; search selectors before opening broad ranges. |
| `HADES.bat` | One-click Windows start flow. |
| `HADES_LAUNCHER.py` | Launcher logic/browser opening. |
| `PREPARE_HADES.bat` | First-run dependency setup + release verification. |
| `VERIFY_HADES.bat` | Repeatable release gates. |

## Backend

| File | Responsibility |
|---|---|
| `backend/config.py` | Environment/runtime configuration. |
| `backend/database.py` | Core SQLite repository: settings, profiles, conversations, messages, tasks, memories, brain data. WAL checkpoints are owned by `sqlite_runtime.py`. |
| `backend/platform_db.py` | Platform storage: knowledge, research, work steps/checkpoints, agents, plugins/tools/toolcalls, paper trading support tables. |
| `backend/sqlite_runtime.py` | Shared SQLite connection helper + WAL checkpoint owner (PASSIVE interval, TRUNCATE on shutdown). |
| `backend/perf.py` | Process-local performance counters (SQLite, discovery, retrieval, TTFT). |
| `backend/model_discovery.py` | TTL + request-scoped cache for LM `/models` used by Chat `resolve_model`. |
| `backend/lm_studio.py` | LM Studio HTTP client/OpenAI-compatible calls. |
| `backend/platform_services.py` | Thin public facade: re-exports from `platform_services_core` + `PluginManager` subclass for bounded dependency installation. Prefer searching symbols here only for the dependency-install override. |
| `backend/platform_services_core.py` | Large service module: KnowledgeService, WebResearchService, ResearchRunner, core PluginManager. Search class/method first; do not read entire file by default. |
| `backend/trading_service.py` | PAPER trading service + offline strategy bot (market bars, discovery, backtest, knowledge). |
| `backend/trading_lab/` | Trading Lab: point-in-time market history, exchange/ledger/risk simulation, strategy research, independent evaluation, agent roles, `/api/trading/lab/*`. Simulation/paper only. See `docs/TRADING_LAB.md`. |
| `backend/main.py` | FastAPI app plus orchestration: reasoning profiles, retrieval, web refresh, tool routing, Work Runtime, API routes. Large hotspot; search function/route first. Brain/Models routes extracted to `brain_routes.py` / `models_routes.py`; lifespan delegates to `app_lifecycle.py`. |
| `backend/hades_brain/` | One Brain façade: shared contracts, domain runtime boundary, cost ledger, tool-schema shortlist, mission views. See `docs/ONE_BRAIN_ARCHITECTURE.md`. |
| `backend/cognitive/` | Cognitive Runtime (Pillars II): self-model, perception, epistemic, ontology, immune, mental models, homeostasis, self-repair, scientific method, credit. Under One Brain — not a second Brain. `/api/cognitive/*`. |
| `backend/mcpmarket/` | MCPMarket.com discovery connector (untrusted catalog → MCP Host draft). Does not execute tools. See `docs/MCPMARKET_INTEGRATION.md`. |
| `backend/brain_graph.py` / `backend/brain_routes.py` | Brain graph assembly (sync I/O) + HTTP routes (layout, nodes, links). |
| `backend/models_routes.py` | Models list/profile + shared gateway overview routes. |
| `backend/app_lifecycle.py` | Ordered startup/shutdown helpers for the single FastAPI lifespan (not a second manager). |
| `backend/infrastructure/native/` | Canonical C++ companion facade (supervisor, transport, typed clients, observability). |
| `backend/native_runtime.py` | Compatibility re-export of the native facade. |
| `backend/errors/` | Unified error taxonomy + correlation IDs. |
| `backend/native_routes.py` | `/api/native/status|diagnostics|restart|metrics|benchmark`. |
| `docs/architecture/python-cpp-boundary.md` | Ownership, cancellation, overload, crash/reconciliation model. |
| `backend/api_contracts.py` | Shared transport models (errors, pagination, coding jobs page meta). |
| `backend/run_lifecycle.py` | A12 ownership map + Work completion gate (`decide_work_task_completion`). |
| `native/` | C++20 `hades_native_runtime` sources, CMake, CTest. |
| `runtime/native/` | Stable installed native binary location (not build trees). |
| `tools/export_openapi.py` | Reproducible OpenAPI subset + `lib/generated/api-contracts.ts`; `--check` for CI drift. |
| `backend/fastapi_nested_annotations.py` | Resolves PEP 563 types on nested FastAPI handlers so `/openapi.json` can build. |

## Frontend pages

| Page | File |
|---|---|
| Chat | `components/hades/pages/chat-page.tsx` |
| Tasks | `components/hades/pages/tasks-page.tsx` |
| Mission Control | `components/hades/pages/mission-control-page.tsx` |
| Agents | `components/hades/pages/agents-page.tsx` |
| Research | `components/hades/pages/research-page.tsx` |
| Trading | `components/hades/pages/trading-page.tsx` (Trading Lab tab shell; tabs in `components/hades/pages/trading-lab/`) |
| Media | `components/hades/pages/media-page.tsx` |
| Plugins | `components/hades/pages/plugins-page.tsx` |
| MCP | `components/hades/pages/mcp-page.tsx` |
| Brain | `components/hades/pages/brain-page.tsx` |
| Models | `components/hades/pages/models-page.tsx` |
| Memory | `components/hades/pages/memory-page.tsx` |
| Files | `components/hades/pages/files-page.tsx` |
| Settings | `components/hades/pages/settings-page.tsx` (+ Spraak tab, Interface preset, Native runtime panel) |

Dual UI: **HADES Lux Atelier** (`components/hades/lux/lux-shell.tsx`) remains the
**coded default** (`ui_style=lux` in settings / `database.py`). **FINALBETA**
(`components/hades/finalbeta/`) is the Chat-primary optional shell (selectable via
Settings → Interface; not the coded default). Obsidian / BETA / BETA 2 trees remain
removed. Style context: `components/hades/ui-style.tsx`. Docs: `docs/UI_STYLE_SYSTEM.md`,
`docs/design/HADES_LUX_CONCEPT.md`, `docs/NATIVE_RUNTIME.md`, `docs/CAPABILITY_INTELLIGENCE.md`.

Reusable HADES UI helpers live in `components/hades/ui.tsx`. Generic UI primitives live under `components/ui/`.

Frontend architecture:
- `components/hades/features/chat/` — chat timeline/composer, high-level execution types, streaming run hook and verification/trace views; `pages/chat-page.tsx` remains the stateful page composition layer.
- `components/hades/features/agent-ux/` — reusable observable execution progress, tool calls, file changes and verification UI (never private chain-of-thought).
- `components/hades/route-error-boundary.tsx` — route render recovery; non-primary pages are lazy-loaded from `hades-app.tsx`.
- `hooks/use-hades-query.ts` — internal deduplicated server-state cache with staleness, cancellation, invalidation and visibility-aware refresh.
- `styles/tokens.css` / `styles/accessibility.css` — semantic HADES token aliases and shared focus/reduced-motion behavior, imported by `app/globals.css`.

## Tests

| File | Coverage |
|---|---|
| `backend/tests/test_api.py` | FastAPI flows including chat, work runtime, plugin permission/tool behavior. |
| `backend/tests/test_database.py` | Core persistence/migrations/state transitions. |
| `backend/tests/test_platform.py` | Knowledge, research formats, plugin packaging/lifecycle/security, paper trading. |
| `backend/tests/test_gen2.py` | Gen2 Eval Lab, Context Compiler, Flight Recorder, Mission Control, Committee, Factory, Sandbox, Graph, Finance, Compute. |
| `backend/tests/test_native_runtime.py` | Native bridge modes, handshake, fake protocol, real binary integration when present. |
| `backend/tests/test_capability_*.py` | Capability Intelligence: normalization, upstream adapters, routing, collaboration, integration. |
| `backend/tests/test_coding_omniroute.py` | Optional Coding OmniRoute backend: off-path identity, plugin eligibility, fallback, catalog-not-in-prompt, cache, secrets, resume/cancel. |
| `tests/source-contracts.test.mjs` | Release/source contracts and Windows/scaffold checks. |
| `tests/ui-components.test.mjs` | Production CSS + selected SSR component/accessibility checks. |
| `tests/ui-style-system.test.mjs` | Lux shell contracts and scoped CSS. |
| `tests/gui-consolidation.test.mjs` | Main interface authority; obsolete shells removed. |
| `tests/capability-intel-ui.test.mjs` | Main GUI capability groups + Chat routing diagnostics. |

## Minimal read-set by subsystem

### Plugin Manager / Tool Runtime
Start with:
- `docs/PLUGIN_RUNTIME_CONTRACT.md`
- `docs/MCP_HOST.md` — first-class MCP page/sessions (does not replace PluginManager)
- `backend/capability_intel/` — Capability Intelligence Layer: taxonomy, adapters, canonical registry, hybrid routing, skills, collaboration, Work Runtime bridge, **Capability Broker** (`broker.py`) for model-facing search/inspect/invoke
- `backend/core_tools/` — first-party HADES Tool Kernel (Chat model-visible schemas only; ≤ 12)
- `docs/architecture/HADES_TOOL_KERNEL_AND_CAPABILITY_BROKER.md` — stable `hades.*` API vs dynamic plugin/MCP capabilities
- `backend/hades_brain/` — One Brain contracts/façade (`docs/ONE_BRAIN_ARCHITECTURE.md`)
- `backend/cognitive/` — Cognitive Runtime pillars under One Brain (`/api/cognitive/*`, self-model on `/api/hades-brain/self-model`)
- `backend/mcpmarket/` — MCPMarket discovery (`docs/MCPMARKET_INTEGRATION.md`); execution stays in MCP Host
- `backend/mcp_host/` — manager, clients, store, routes, catalog, oauth, secrets, policy, validation, lifecycle
- `backend/platform_services.py` — `PluginManager` only
- `backend/folder_picker.py` — native local folder dialog for packing
- `backend/platform_db.py` — plugin/tool/toolcall methods only (+ MCP migrations 15–16)
- `backend/main.py` — `shortlist_plugin_tools`, `run_model_with_optional_tool`, permission helpers and `/api/plugins/*` routes
- `components/hades/pages/plugins-page.tsx`
- `components/hades/pages/mcp-page.tsx`
- plugin-related types/methods in `lib/api/plugins.ts` (wired onto `hadesApi` via `lib/hades-api.ts`)
- plugin tests in `backend/tests/test_api.py` and `backend/tests/test_platform.py`
- `backend/tests/test_mcp_host_management.py`, `test_mcp_host_hardening_regressions.py`, `test_mcp_host_integration.py`
- `backend/tests/test_tool_kernel_capability_broker.py` — tool-count invariant + broker E2E (MarkItDown/Puppeteer/MCP)

Do **not** inspect ResearchRunner just because it shares `platform_services.py`.

### Chat / reasoning / context
Start with:
- `backend/reasoning/` — contracts, specialists, plan_scheduler, model_router, retrieval, conversation_state, verification, events, run_control, tool_workflows
- `backend/project_continuity.py` — durable project goals/decisions/constraints/assumptions + context package
- `backend/result_contracts.py` — executable mission/task result contracts
- `backend/proactive_triggers.py` — opt-in proactive suggestions with dedupe
- `backend/research_conflicts.py` — conflict presentation without invented resolution
- `backend/main.py` — `runtime_values`, `effective_reasoning`, `chat_payload`, retrieval/context helpers, tool loop, `send_message`, `TaskRunner`
- `backend/database.py` — settings/profile/conversation/message methods
- `backend/lm_studio.py` — includes `chat_stream` for provisional deltas
- `backend/chat_commands.py`, `backend/mentions.py`, `backend/terminal_tool.py`, `backend/practice_api.py`
- `backend/workspace_symbols.py`, `backend/lsp_light.py`, `backend/voice_tasks.py`, `backend/voice/` (local ASR/TTS session), `backend/speech/` (VoiceStudio TTS/STT provider), `backend/debug_agent.py`
- `backend/coding_agent.py`, `backend/coding_investigate.py`, `backend/coding_jobs.py`, `backend/coding_job_control.py`, `backend/coding_requirement_map.py`, `backend/coding_delivery.py`, `backend/coding_autonomy.py`, `backend/coding_omniroute.py`, `backend/repo_intelligence.py`, `backend/coding_context.py`, `backend/coding_plan.py`, `backend/coding_edits.py`, `backend/coding_failures.py`, `backend/coding_verification.py`, `backend/coding_candidates.py`, `backend/coding_metrics.py`, `backend/coding_memory.py`, `backend/evals/judges.py`, `backend/evals/quality_suite.py`, `backend/evals/independent_tasks.py`, `backend/evals/dev_partner_suite.py`, `backend/evals/dev_partner_harness.py`, `backend/evals/frontier_coding_suite.py`, `backend/evals/functional/` (campaign scoreboard/intent/retrieval/ablation), `backend/reasoning/chat_coordinator.py`, `backend/language_servers.py`, `backend/investigate_selector.py`
- Architecture ledger: `docs/architecture/frontier-coding-agent.md`
- `components/hades/pages/chat-page.tsx`
- `components/hades/pages/coding-agent-page.tsx`
- `components/hades/features/project-continuity-panel.tsx`
- chat/settings types in `lib/hades-api.ts`
- Product direction: Chat-primary HADES-10 (`docs/DECISIONS.md` D018); archived Gen2 planning under `docs/archive/planning/`
- Gen1 baseline (archived): `docs/archive/HADES_WORLD_CLASS_VISION.md`
- relevant API/database tests plus `tests.test_reliable_orchestration` / `tests.test_practice_scenarios` / `tests.test_capability_wave2` / `tests.test_milestone1_quality_investigate_jobs` / `tests.test_reliable_coding_jobs_m2` / `tests.test_autonomous_work_partner` / `tests.test_coding_omniroute`

### Work Runtime / agents
Start with:
- `backend/main.py` — `route_agent`, `TaskRunner`
- `backend/platform_db.py` — agent/work step/checkpoint methods
- `components/hades/pages/tasks-page.tsx`
- `components/hades/pages/agents-page.tsx`
- work-related API types in `lib/hades-api.ts`
- focused work tests

### Research / Knowledge / Files
Start with:
- `backend/platform_services.py` / `platform_services_core.py` — `KnowledgeService`, `WebResearchService` (`harvest_site_documents`), `ResearchRunner`
- `backend/chat_commands.py` — slash + natural harvest intents
- `backend/platform_db.py` — knowledge/research/workspace/indexed-file methods
- research/file/harvest/brain routes in `backend/main.py`
- `components/hades/pages/research-page.tsx`
- `components/hades/pages/files-page.tsx`
- `components/hades/pages/brain-page.tsx` (+ brain-graph/inspector/graph-adapter helpers)
- relevant API types/tests (`tests.test_world_class_capabilities`)

### Memory / Brain
Start with:
- `backend/database.py` — memory/brain methods and migrations (`update_brain_node`, `delete_brain_node`, `add_brain_link`)
- memory/brain routes in `backend/main.py` (`GET/POST/PUT/DELETE /api/brain*`)
- external brain links in `backend/platform_db.py`
- `components/hades/pages/memory-page.tsx`
- `components/hades/pages/brain-page.tsx` (live API; no mock graph)
- focused tests

### Neural Memory (experimental, isolated)
Start with:
- `docs/neural/STATUS.md`, `docs/neural/BASELINE.md`, `docs/neural/ARCHITECTURE.md`
- `backend/neural/` — parametric associative memory, checkpoints, sample compiler/job
- `backend/neural/samples.py` — Dataset Brain → neural samples (provenance, redaction)
- `backend/neural/sample_job.py` — resumable/cancellable streaming compile jobs
- `backend/neural/runtime.py` — Phase 3 frozen toy Transformer + residual fusion
- `backend/neural/encoding.py`, `backend/neural/slow_train.py` — Phase 4 frozen-encoding slow training
- `backend/neural/fast_memory.py` — Phase 5 bounded verified fast-memory session writes
- `backend/neural/experience.py` — Phase 6 verified-experience → reward/learning signals
- `backend/neural/consolidation.py` — Phase 7 evaluate-then-promote slow consolidation
- `backend/neural/runtime_lifecycle.py` — Phase 9 lifecycle boundary (start/stop/health/infer)
- `backend/neural/runtime_worker.py` — optional isolated Neural Runtime process
- `backend/neural/runtime_compat.py` — checkpoint/runtime compatibility checks
- `backend/reasoning/runtime_selection.py` — Phase 10 Standard vs Neural policy
- `backend/reasoning/model_runtime_bridge.py` — opt-in ModelGateway neural bridge
- `backend/reasoning/model_chat_dispatch.py` — real `gateway_chat` neural-aware dispatch
- `backend/reasoning/neural_settings.py` — settings/env resolution (default OFF)
- `backend/neural/dual_retrieval.py` — Phase 11 Exact + Neural dual retrieval
- `backend/neural/learning_lifecycle.py` — Phase 12 fail-closed learning states
- `backend/neural/toy_transformer.py`, `backend/neural/fusion.py`
- `backend/tests/test_neural_*.py`
- Not wired into ModelGateway / FastAPI / GUI. Default mode OFF. Optional torch.

### Settings / models / Control Plane
Start with:
- `backend/control/` — registry, resolver, capabilities, presets, Limit Inspector, `/api/control/*`
- `docs/architecture/control-plane.md`
- `docs/architecture/configuration-limit-audit.md`
- `backend/database.py` — `DEFAULT_SETTINGS`, `DEFAULT_PROFILE`, settings/profile repository methods
- `backend/config.py`
- model/settings routes in `backend/main.py`
- `backend/lm_studio.py`
- `components/hades/pages/settings-page.tsx` (+ Advanced → `components/hades/control-center.tsx`)
- `components/hades/pages/models-page.tsx`
- related `lib/hades-api.ts` types

### Trading
Start with:
- `backend/trading_service.py` (`PaperTradingService`, `TradingBotService`, `TradingJobRunner`)
- trading persistence/migration v6 tables in `backend/platform_db.py` (`market_bars`, `trading_strategies`, `trading_strategy_runs`, `trading_bot_settings`)
- trading routes in `backend/main.py` (`/api/trading`, `/api/trading/dashboard`, market/bot/runs)
- `components/hades/pages/trading-page.tsx`
- `lib/hades-api.ts` trading types/methods
- paper-trading + strategy discovery tests

Trading flow: seed/import OHLCV → discover/backtest/paper_bot runs → deterministic fills via `PaperTradingService` → strategy learnings ingested as Knowledge (`source_type=trading_strategy`). This is the legacy paper desk, preserved as one tab of the Trading Lab.

### Trading Lab (research, simulation, evaluation)
Start with:
- `docs/TRADING_LAB.md` (architecture, capability matrix, verification status), `docs/TRADING_LAB_GAP_ANALYSIS.md`
- `backend/trading_lab/` — contracts/capabilities, `clock.py` (point-in-time), `bar_store.py` + `catalog.py` (market history), `execution.py` + `accounting.py` + `risk.py` (order path), `engine.py` (run loop), `research.py` + `evaluation.py` + `registry.py` (experiments, verdicts, lifecycle), `experience.py` + `regimes.py` + `learning.py` + `evolution.py` + `champions.py` + `learning_cycle.py` (durable learning loop), `agents.py`, `jobs.py`, `store.py` (`lab_*` tables including experiences/beliefs/cycles), `service.py`, `routes.py`
- mount in `backend/main.py` (`mount_trading_lab_routes`, `/api/trading/lab/*`)
- `components/hades/pages/trading-page.tsx` (tab shell) + `components/hades/pages/trading-lab/*` (including `learning-tab.tsx`)
- `lab*` methods/types in `lib/hades-api.ts`
- `backend/tests/test_trading_lab_*.py` — learning suite 22/22 PASS on this branch; remaining Trading Lab files executed here (1 pre-existing capability-reason FAIL, see CURRENT_STATUS)

Trading Lab learning flow: delayed decision outcomes → idempotent experiences → deterministic aggregation → evidence-backed beliefs → bounded declarative mutations → development experiments → independent validation (not sealed holdout) → champion/challenger. Autonomy default OFF.

Lab flow: register instrument → import/download/generate dataset (validated, versioned, split) → register strategy with a falsifiable hypothesis → run on the simulation clock (observe → decide → risk veto → submit → fill on a later event → ledger) → delayed outcomes become experiences → aggregate → evidence-backed beliefs → bounded candidate mutations → development experiments → independent validation → champion/challenger. Simulation/paper only.

### Media Intelligence
Start with:
- `docs/media/ARCHITECTURE.md`, `docs/media/PLATFORMS.md`, `MEDIA_SETUP_REQUIRED.md`
- `backend/media/` — store, service, orchestrator, platforms, routes, rendering, trends, creative
- mount in `backend/main.py` (`media_ctx`, `/api/media/*`)
- `components/hades/pages/media-page.tsx` (+ Obsidian wrapper)
- media methods/types in `lib/hades-api.ts`
- `backend/tests/test_media_intelligence.py`

Media flow: channel/campaign → trend evidence → research → script/critics → storyboard → FFmpeg master → platform variants → durable publish → metrics → learning.

### Gen2 / Advanced runtime modules
Start with:
- Archived planning only: `docs/archive/planning/` (not active backlog)
- `backend/gen2/` — `store.py`, `services.py`, `routes.py` (existing modules; reuse from Chat/Advanced)
- mount + durable event sink in `backend/main.py` (`gen2_ctx`, `_sync_gen2_services`)
- `components/hades/pages/mission-control-page.tsx` (Advanced console)
- Gen2 methods in `lib/hades-api.ts`
- `backend/tests/test_gen2.py`

## Important dependency flows

### Chat answer
`chat-page.tsx` -> `hades-api.ts` -> FastAPI `send_message` -> settings/model resolution -> optional web refresh -> Memory/Knowledge retrieval -> bounded plugin-aware model loop -> persist assistant message -> optional Knowledge/Memory update.

### Plugin manual run
`plugins-page.tsx` -> `/api/plugins/{id}/invoke` -> explicit approval + global policies -> `PluginManager.invoke` -> persisted toolcall -> structured result back to UI.

### Plugin autonomous run
Chat/Work orchestration -> shortlist eligible enabled/Ready/autonomous tools -> model selects structured call -> policy enforcement -> `PluginManager.invoke` -> failed/blocked/success result fed back to model -> final answer.

### Research
`research-page.tsx` -> research API -> persisted project -> `ResearchRunner` -> local/web sources -> Knowledge ingestion + Evidence -> iterative synthesis/mastery -> persisted report/events.

## Hotspots / refactor caution

- `backend/main.py` and `backend/platform_services_core.py` are large because orchestration accumulated there. `platform_services.py` is the thin re-export + dependency-install PluginManager subclass. Refactor by extracting one stable interface at a time; do not perform a broad rewrite without characterization tests.
- `lib/hades-api.ts` is a cross-cutting contract. Backend route/type changes often require coordinated frontend changes.
- `app/globals.css` is large. Search the selector before editing; avoid formatting/reordering the entire stylesheet.
- Database migrations must remain forward-compatible with existing local SQLite data.
