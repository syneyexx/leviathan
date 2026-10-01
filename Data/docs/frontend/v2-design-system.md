# Leviathan V2 Frontend Design System

## Purpose

Screen 1 (Dashboard / Command Center) is the first page migrated onto a **global** V2 design system. Future pages (Research, Trading, Models, Training, …) must reuse the same tokens, shell, and primitives — not invent page-local CSS.

## Namespace

All V2 styles are scoped under `.lv-v2` so legacy gold/black pages keep working until they opt in.

- Tokens: `src/styles/tokens.css` (`.lv-v2 { --lv2-* }`)
- Global primitives + shell: `src/styles/leviathan-v2.css`
- Import order: `tokens.css` → `leviathan.css` (legacy) → `leviathan-v2.css`

## Shell contract

Use `AppShell` with `variant="v2"`:

- `AppTopbarV2` — title, subtitle, refresh, clock, status
- `AppSidebarV2` — `V2_PRIMARY_NAV` + System Status
- No legacy gold footer / right rail on V2 pages

Navigation truth lives in `src/navigation/v2Nav.ts` (primary rail) and `src/navigation/menu.ts` (legacy footer submenus for unmigrated pages).

## Primitives (`src/components/ui/`)

Reusable across all migrated pages:

`Panel`, `MetricCard`, `Button`, `Badge`, `ProgressBar`, `Gauge`, `Sparkline`, `StatusDot`, `EmptyState`, `ErrorState`, `LoadingState`

Layout: `BrandV2`, `AppSidebarV2`, `AppTopbarV2`

## Allowed page composition

Pages may compose semantic blocks in TSX (e.g. `DashboardHero`).  
**Do not** add:

- `dashboard.css` / `CommandPage.css` / page-specific stylesheets for migrated pages
- duplicated button/card/table CSS copies
- production hardcoded Screen 1 metrics

Small dynamic CSS variables (`style={{ "--lv2-progress": n }}`) are allowed.

## Live-data truth

Screenshot numbers are **not** production defaults. Missing sensors must read `N/A` / `UNMEASURED` / `UNAVAILABLE` / `—`. Measured zero stays zero.

Dashboard data orchestration: `useDashboardOverview()`.

## Visual regression

1. Reference: `Data/docs/ui_reference/dashboard-v2-reference.png` (not bundled into production UI)
2. Playwright: `e2e/dashboard-v2.visual.spec.ts`
3. Viewport: **1664 × 936**, `deviceScaleFactor = 1`
4. Fixture: `src/mocks/dashboardV2VisualFixture.ts` via `installDashboardV2VisualFixture` (test-only)
5. Frozen clock: `window.__LV_V2_FROZEN_NOW__`

Compare screenshots against Screen 1. Do not “fix” pixel drift by replacing the authority reference with whatever the app happens to render.

## Accessibility

Keep semantic buttons/links, focus-visible, landmarks (`SkipLink` + `#main-content`), and `prefers-reduced-motion` respect.

## Migration path

1. Opt the page into `AppShell variant="v2"`
2. Replace page chrome with V2 primitives
3. Wire real APIs (no new stores)
4. Add/extend visual coverage
5. Delete unused legacy CSS only after no route depends on it

Media Control, Plugin & Runtime, Coding Agent, and other deep links remain registered even when not shown in the Screen 1 sidebar.

## Brain migration

- `/brain` uses `AppShell variant="v2"` with the shared `AppSidebarV2` / `AppTopbarV2`.
- DNA double-helix network (`BrainDnaNetwork` + `BrainLivingNetworkCanvas` + `brain-helix-engine` / legacy `brain-dna-layout`) is the default Graph visualization inside **Kennis Netwerk**, with Relaties mode and Research Workbench tabs; Celestial / Technical / Tree / Timeline / Clusters / Analytics remain under the advanced graph surface.
- Research group children are adapted from `MAIN_MENU` via `v2ChildrenFromMainMenu` — one canonical route source, V2 presentation only.
- No page-local Brain V2 CSS file; styles live in `leviathan-v2.css` under knowledge-network sections.
- Visual fixture: `src/mocks/brainV2VisualFixture.ts` + `e2e/brain-v2.visual.spec.ts` (reference: `docs/ui_reference/brain-v2-reference.png`).
- Next pages (Research, Memory, Evidence, …) must reuse the same shell, tokens, and primitives.

## Chat migration

- `/chat` uses `AppShell variant="v2"` with shared `AppSidebarV2` / `AppTopbarV2` (generic `actions` slot for Nieuwe chat / Manage / Gesprekken).
- Hades AI expandable group owns Chat / Reasoning (`/cognition`) / Agents link / Bibliotheek (`/knowledge`) / Prompts / Evaluations — Dashboard keeps home + Taken.
- Three-column workspace primitives live in `leviathan-v2.css` (`.lv-v2-page--chat`, select cards, history, composer, inspector, meters, source rows). No `chat-v2.css`.
- Reusable UI additions: `Dialog`, topbar `actions` / `hideRefresh`.
- Visual fixture: `src/mocks/chatV2VisualFixture.ts` + `e2e/chat-v2.visual.spec.ts` (reference: `docs/ui_reference/chat-v2-reference.png`).
- Production never hardcodes Screen 1 model/metrics/sources; fixture-only via `__LV_CHAT_V2_FIXTURE_UI__`.
- Thin V2 surfaces: `/prompts`, `/evaluations` (real evaluation APIs). Coding and other deep links remain registered.

## Research migration

- `/research` uses `AppShell variant="v2"` with shared `AppSidebarV2` / `AppTopbarV2`.
- Overview (Screen 1) + selected-run workspace; create/start/cancel, ingestion, evidence, claims, gaps, web readiness, and Brain sync remain on canonical Research APIs.
- Research group children stay MAIN_MENU-derived via `v2ChildrenFromMainMenu` — no duplicate Research route tree.
- No page-local Research V2 CSS file; layout lives in `leviathan-v2.css` under `.lv-v2-page--research` / workspace primitives (segmented filters, type cards, stepper, template rows).
- Visual fixture: `src/mocks/researchV2VisualFixture.ts` + `e2e/research-v2.visual.spec.ts` (reference: `docs/ui_reference/research-v2-reference.png`).
- Trading Research (`/trading/onderzoek`, `/trading/lab`) is untouched.

## Agents migration

- `/agents` uses `AppShell variant="v2"` with shared `AppSidebarV2` / `AppTopbarV2` (title "LLM / Agents").
- **MAIN_MENU owns Agents under LLM.** The V2 rail has no standalone top-level Agents owner. LM's `match` claims `/models` and `/agents`; on `/agents` LM auto-expands with the Agents child selected. Hades → Agents still deep-links to `/agents` but must not stay active after navigation.
- Fleet vs Worker distinction is mandatory: Active Agents ≠ Active Workers; missions/jobs/workers remain separate concepts.
- Agent Architecture on this page is **agent-oriented** (orchestrator / specialists / Worker Fabric / tools / models / knowledge) — not the separate full Leviathan Architecture product.
- Model assignment uses real `modelRef` → Model Control Plane. GPU split / VRAM reserve / LM Studio load options stay on `/models` (link out via "Open Models").
- Capabilities / tools remain governed by ExecutionGateway; UI never invents fractional permission counts.
- Resource meters on the Agents page are host/system telemetry or UNMEASURED — never fake per-agent GPU attribution.
- Composition: `useAgentsWorkspace` + `src/components/agents/*` + preserved modals under `pages/agents/*` (editor, launch mission, worker scale, core inventory, trade orchestra).
- No page-local Agents V2 CSS file; layout lives in `leviathan-v2.css` under `.lv-v2-page--agents` / `.lv-v2-agents-*`.
- Visual fixture: `src/mocks/agentsV2VisualFixture.ts` + `e2e/helpers/agentsV2Visual.ts` + `e2e/agents-v2.visual.spec.ts` (reference: `docs/ui_reference/agents-v2-reference.png`). Production never imports the fixture as defaults.

## Models migration

- `/models` uses `AppShell variant="v2"` with shared `AppSidebarV2` / `AppTopbarV2` (title "LM / Models").
- LM is an expandable nav group, derived from `MAIN_MENU` via `v2ChildrenFromMainMenu("llm")`. Its `match` claims `/models`, `/training`, `/agents`, and `/analytics`. On those routes LM auto-expands with the matching child selected — there is no separate top-level Training owner. Datasets live under Onderzoek & Kennis, not LLM.
- `ModelsPage.tsx` composes four card rows (Runtime Provider / Hardware / VRAM; Model list / Load Config / Multi-GPU / Advanced; wide Optimalisatie; Resource Estimate / Performance / Actions) plus a manage-links footer that opens drawers for the existing `ProviderManager`, `ModelGatewayPanel`, `ModelRouterPanel`, and `ModelResidencyPanel` panels — those advanced surfaces are reused unchanged, not rebuilt.
- All page composition lives in `src/components/models/*` (11 focused card components + `useModelsWorkspace` for data/mutation orchestration). No page-local CSS file; layout, form controls (select/range/toggle rows, tables, meters) live in `leviathan-v2.css` under `.lv-v2-page--models` / `.lv-v2-models-*`.
- Capability-gating truth discipline: controls are enabled/disabled from the backend
  capability field matrix (`capabilities.fields[]` with support/scope/transport/reasonCode)
  via `ws.capSupport()` / `ws.capNote()` / `ws.capField()`. Seed is SDK load-scoped when
  the official SDK is reachable; `cpuThreads` / speculative draft are inference-scoped
  and never enter the load payload. Arbitrary per-GPU % splits stay disabled with
  `SDK_SPLIT_STRATEGY_ONLY` when the provider only exposes evenly/favorMainGpu.
- Runtime Provider card shows provider health **and** separate `modelRuntime` Worker
  Fabric state (`COLD` / `READY` / …). Load/unload await JobRuntime terminal state;
  **Stoppen** cancels the Leviathan job/optimizer only (never kills LM Studio).
- No fake hardcoded hardware/metrics in the production path — `useModelsWorkspace` only calls the real Model Control Plane APIs (`Data/backend/routes/models.py`, `Data/modules/models/*`, including the LM Studio control (`lm_studio_control.py`) and optimizer (`optimizer.py`) modules). Only the dedicated visual-fixture module below may contain deterministic mock data, gated behind `window.__LV_V2_VISUAL_FIXTURE__`.
- Visual fixture: `src/mocks/modelsV2VisualFixture.ts` + helper `e2e/helpers/modelsV2Visual.ts` + `e2e/models-v2.visual.spec.ts` (reference: `docs/ui_reference/models-v2-reference.png`), covering load, nav-ownership, and interaction flows (select model, search, edit context/offload/GPU-split, estimate, optimize, load/unload).

## Training migration

- `/training` uses `AppShell variant="v2"` with shared `AppSidebarV2` / `AppTopbarV2` (title "LLM / Model Training").
- **MAIN_MENU owns Training under LLM.** The V2 rail has no standalone top-level Training owner. On `/training` LM auto-expands with the Training child selected (same architecture as Agents/Models).
- Composition: `TrainingPage` + `useTrainingWorkspace` + `src/components/training/*` (engine, hardware, stats, datasets, models, config, runs, metrics chart, run detail, checkpoints, preflight drawer).
- Training Engine card shows **Leviathan Trainer** (PyTorch / Transformers / PEFT / TRL) — LM Studio is never presented as the fine-tune provider.
- Production methods: SFT / LoRA / QLoRA / DPO. Fixture is test-only and never appears in the production method selector or as green readiness.
- GPU selection uses `stableDeviceId`; multi-GPU is not exposed unless a real strategy exists.
- No page-local Training CSS file; layout lives in `leviathan-v2.css` under `.lv-v2-page--training` / `.lv-v2-training-*`.
- Visual fixture: `src/mocks/trainingV2VisualFixture.ts` + `e2e/helpers/trainingV2Visual.ts` + `e2e/training-v2.visual.spec.ts` (reference: `docs/ui_reference/training-v2-reference.png`). Production never imports the fixture as defaults.

## Settings / Systeem Instellingen migration

- `/settings` uses `AppShell variant="v2"` with shared `AppSidebarV2` / `AppTopbarV2` (title "Settings / Systeem Instellingen").
- Canonical ownership remains the Settings Control Plane (`Data/modules/settings/`). Providers remain Model Control Plane. No second settings DB / provider registry / telemetry stack.
- Composition: `SettingsPage` + `useSettingsWorkspace` + `src/components/settings/*` (hero, metrics, category nav, algemeen panel, providers, system config, catalog fields).
- Algemeen preferences live as `ui.*` catalog keys on `Settings.ui`. System config sliders edit existing keys (`managed_serving.gpu_memory_limit_pct`, `context.token_budget`, `resources.max_model_concurrency`, `model.timeout_seconds`).
- No page-local Settings CSS file; layout lives in `leviathan-v2.css` under `.lv-v2-page--settings` / `.lv-v2-settings-*`.
- Docs: `Data/docs/frontend/settings-v2.md`. Reference: `docs/ui_reference/settings-v2-reference.jpg`.
- Screenshot categories Gebruikers/Abonnement are not fabricated as subsystems; Users KPI reports local-operator truth.

## Taken migration

- `/tasks` uses `AppShell variant="v2"` with shared `AppSidebarV2` / `AppTopbarV2` (title "Dashboard / Taken").
- **MAIN_MENU owns Taken under Dashboard** (`/` + `/chat` + `/tasks`). V2 rail expands Dashboard with Taken selected on `/tasks`.
- Composition: `TasksPage` + `useTasksWorkspace` + `src/components/tasks/*` (hero, metrics, overview table, detail panel, bottom telemetry grid) + preserved `TaskCreateDialog`.
- No page-local Taken CSS import; layout lives in `leviathan-v2.css` under `.lv-v2-page--tasks` / `.lv-v2-tasks-*`. Legacy `tasks-reference.css` is unused by the production page.
- Production never ships screenshot mock rows; KPIs/table/activity/resources come from TaskService + system telemetry. Unknown progress/resources stay unknown/`UNAVAILABLE`.
- Reference: `docs/ui_reference/taken-v2-reference.png`.

## Memory / Geheugen migration

- `/memory` uses `AppShell variant="v2"` with shared `AppSidebarV2` / `AppTopbarV2` (title "Onderzoek & Kennis / Geheugen").
- Research group children stay MAIN_MENU-derived — Geheugen selected; do not copy screenshot submenu labels.
- Composition: `GeheugenPage` + `useMemoryWorkspace` + `src/components/memory/*`.
- No page-local Memory CSS; layout lives in `leviathan-v2.css` under `.lv-v2-page--memory` / `.lv-v2-memory-*`.
- KPIs/search/table/analytics/semantic-index/processing are real API-backed; fixture-only Screen 1 numbers live in `src/mocks/memoryV2VisualFixture.ts`.
- Visual: `e2e/helpers/memoryV2Visual.ts` + `e2e/memory-v2.visual.spec.ts` (reference: `docs/ui_reference/memory-v2-reference.png`).
- Memory ≠ Knowledge ≠ Brain — document/web actions deep-link to Knowledge/Research authorities.
## Modules migration

- `/modules` uses `AppShell variant="v2"` with shared `AppSidebarV2` / `AppTopbarV2` (title "Runtime & Tools / Modules").
- MAIN_MENU parent label is **Runtime & Tools** (`id: runtime` unchanged). Children stay MAIN_MENU-derived via `v2ChildrenFromMainMenu`.
- Composition: `ModulesPage` + `useModulesWorkspace` + `src/components/modules/*` (hero, metrics, local nav, library, detail, install drawer, projection views).
- No page-local Modules CSS; layout lives in `leviathan-v2.css` under `.lv-v2-page--modules` / `.lv-v2-modules-*`. Legacy `modules-page.css` is unused by `/modules`.
- Lifecycle enqueue awaits JobRuntime terminal state; Feature Flag / KPIs / filters / update evidence are API-backed.
- Local views `?view=runtimes|installation|environments` are projections — not new backend systems.
- Visual fixture: `src/mocks/modulesV2VisualFixture.ts` + `e2e/modules-v2.visual.spec.ts` (reference: `docs/ui_reference/modules-v2-reference.png`, 1672×941). Production never imports fixture defaults.

## Tools migration

- `/tools` uses `AppShell variant="v2"` with shared `AppSidebarV2` / `AppTopbarV2` (title "Runtime & Tools / Tools").
- Composition: `ToolsPage` + `useToolsWorkspace` + `src/components/tools/*` (hero, six KPIs, library, detail tabs, bottom MCP/plugins/recent, modals).
- No page-local Tools CSS; layout lives in `leviathan-v2.css` under `.lv-v2-page--tools` / `.lv-v2-tools-*`.
- KPIs / library / usage / recent calls come from CapabilityCatalog + CapabilityReceiptStore + PluginRegistry + MCP bridge via `/api/capabilities/overview` and `/library`.
- Test uses ExecutionGateway; custom tools are declarative wrappers only (CONTROL table `custom_capability_definitions`).
- Visual fixture: `src/mocks/toolsV2VisualFixture.ts` + `e2e/helpers/toolsV2Visual.ts` + `e2e/tools-v2.visual.spec.ts` (reference: `docs/ui_reference/tools-v2-reference.jpg`). Production never imports fixture defaults.

## Workflows migration

- `/workflows` uses `AppShell variant="v2"` with shared `AppSidebarV2` / `AppTopbarV2` (title "Runtime & Tools / Workflows").
- MAIN_MENU parent remains **Runtime & Tools**; Workflows child is canonical (`/workflows`).
- Composition: `WorkflowsPage` + `useWorkflowsWorkspace` + `src/components/workflows/*` (hero, metrics, library, canvas editor, center tabs, detail, bottom analytics, modals).
- No page-local Workflows CSS; layout lives in `leviathan-v2.css` under `.lv-v2-page--workflows` / `.lv-v2-wf-*`.
- Backend authority: WorkflowStore definitions/versions/executions + WorkflowRuntime + JobRuntime `workflow` pool + ScheduleRunner + ExecutionGateway. Active/Inactive is definition status, not latest execution state.
- Visual fixture: `src/mocks/workflowsV2VisualFixture.ts` + `e2e/helpers/workflowsV2Visual.ts` + `e2e/workflows-v2.visual.spec.ts` (reference: `docs/ui_reference/workflows-v2-reference.png`, 1664×936). Production never imports fixture defaults.

## Analytics / Statistieken migration

- `/analytics` uses `AppShell variant="v2"` with shared `AppSidebarV2` / `AppTopbarV2` (title "LLM / Statistieken").
- **MAIN_MENU owns Statistieken under LLM** (label corrected from typo `Statestieken`). On `/analytics` LM auto-expands with Statistieken selected.
- Composition: `AnalyticsPage` + `useAnalyticsWorkspace` + `src/components/analytics/*` (hero, six KPIs, growth/activity charts, donut distributions, rankings, resources/processing/activity).
- Reuses `.lv-an-*` in `analytics.css`; page shell/hero under `.lv-v2-page--analytics` in `leviathan-v2.css`.
- Backend: extended `AnalyticsService` multi-DB read model (`GET /api/analytics/dashboard`). Legacy analytics routes remain. No analytics database. Knowledge/Dataset/Research/Agent/Job/telemetry remain canonical owners.
- Search focuses dashboard panels (Ctrl+K). Refresh is bounded/non-overlapping; partial/stale/UNMEASURED stay honest.
- Visual fixture: `src/mocks/analyticsV2VisualFixture.ts` + `e2e/helpers/analyticsV2Visual.ts` + `e2e/analytics-v2.visual.spec.ts` (reference: `docs/ui_reference/analytics-v2-reference.png`, 1664×936). Production never imports fixture defaults.

## Datasets (Onderzoek & Kennis) — canonical workspace

- **Single surface:** `/datasets` under **Onderzoek & Kennis → Datasets**. There is no separate LLM Dataset Manager nav child.
- Legacy redirects (keep routes in `App.tsx`):
  - `/dataset-management` → `/datasets?mode=manage` (`DatasetManagementPage` Navigate shell)
  - `/offline-datasets` → `/datasets?mode=learning` (`OfflineDatasetsPixelPage` Navigate shell)
- Modes: default inventory, `?mode=manage`, `?mode=learning` (fleet via `listLearningFleet`).
- `/datasets` uses `AppShell variant="v2"` with shared `AppSidebarV2` / `AppTopbarV2` (title "Kennis & Onderzoek / Datasets").
- **MAIN_MENU owns Datasets under Onderzoek & Kennis.** Research group children stay MAIN_MENU-derived via `v2ChildrenFromMainMenu("research")`.
- Composition: `DatasetsPage` + `useDatasetsWorkspace` + `useDatasetMutations` + `src/components/datasets/*` + shared `DatasetActivityConsole`.
- Composition layout (reference 1664×936): topbar → 5 KPI cards → action/search toolbar → filter pills + Filters/Kolommen/list-grid → inventory table + detail panel → **exactly 4** bottom widgets (Verwerking / Bron Integraties / Opslag / Activiteit).
- No standalone hero in the primary composition. `DatasetsHero` is preserved but not rendered on `/datasets`.
- Activity console is compact in the 4th bottom widget; expanded cancel/clear lives in the activity modal. Health remains a secondary modal (not a 5th bottom card).
- No page-local Datasets V2 CSS; layout lives in `leviathan-v2.css` under `.lv-v2-page--datasets` / `.lv-v2-ds-*`. Legacy `datasets-dashboard.css` remains only for shared `.lv-dac` activity console base styles. Obsolete `.lv-v2-page--dataset-mgmt` / `.lv-v2-dm-*` rules may remain until CSS cleanup.
- Production presentation contracts live in `src/pages/datasets/constants.ts`. Production code must not import fixture data from `mocks/datasets-dashboard`. Visual fixture: `src/mocks/datasetsV2VisualFixture.ts` + `e2e/helpers/datasetsV2Visual.ts` (reference: `docs/ui_reference/datasets-v2-reference.png`). Redirect coverage: `e2e/dataset-management-v2.visual.spec.ts`.
- Inventory uses bounded server pagination (`limit`/`offset`/`hasMore`/`total`/`nextCursor`) via `GET /api/datasets` with `sourceScope` / `indexed` / `updatedAfter`/`updatedBefore` / exact `tags`. KPI totals come from `GET /api/datasets/overview`. Page size never defines catalog totals.
- Detail primary tabs: Overzicht / Analyse / Voorbeeld / Metadata. Versions + Activity + Health remain via secondary “Meer” / modals. Analyse deep-links to `/research?dataset=…` (no second analysis engine). Charts render only from bounded numeric preview series — never hardcoded BTC.
- Toolbar: Nieuwe dataset / Importeren / Externe bron (HF) / Verwerken (bulk materialize) / Indexeren (bulk index). UI does **not** call `POST /api/datasets/jobs/process`. Tags mutate via `PATCH /api/datasets/{id}/semantic`. Download uses export/download DatasetService paths. Delen copies an internal deep link only.
- Unknown status ≠ Ready. Unmeasured progress ≠ invented %. Capacity unknown ≠ fake 1 TB. Screenshot KPI numbers exist only in test fixtures.

## Console migration

- `/console` uses `AppShell variant="v2"` with shared `AppSidebarV2` / `AppTopbarV2` (title "Runtime & Tools / Console").
- MAIN_MENU parent remains **Runtime & Tools**; Console child is canonical (`/console`).
- Composition: `ConsolePage` + `useConsoleWorkspace` + `src/components/console/*` (metrics, panel, filters, services, bottom analytics, modals).
- No page-local Console CSS; layout lives in `leviathan-v2.css` under `.lv-v2-page--console` / `.lv-v2-console-*`.
- Backend authority: ObservabilityHub / EventStore (`GET /api/events`, `/api/events/stream`, `/api/console/overview`, `/api/console/command`) + product-truth components for Actieve Services. Pause/clear are client-buffer semantics; durable history is never deleted by Wissen.
- Visual fixture: `src/mocks/consoleV2VisualFixture.ts` + `e2e/helpers/consoleV2Visual.ts` + `e2e/console-v2.visual.spec.ts` (reference: `docs/ui_reference/console-v2-reference.png` when present). Production never imports fixture defaults.

## Knowledge Library migration

- `/knowledge` uses `AppShell variant="v2"` with shared `AppSidebarV2` / `AppTopbarV2` (title "Knowledge Library").
- **MAIN_MENU owns Knowledge Library under Onderzoek & Kennis.** Research group children stay MAIN_MENU-derived via `v2ChildrenFromMainMenu("research")`.
- Composition (reference 1664×936): topbar + Ctrl+K search → 5 KPI cards → feature nav → type/tag sidebars + library table + selected source → ingestion progress + recent + related sources.
- No page-local Knowledge CSS; layout lives in `leviathan-v2.css` under `.lv-v2-page--knowledge` / `.lv-v2-kl-*`.
- Composition: `KnowledgeLibraryPage` + `useKnowledgeLibraryWorkspace` + `src/components/knowledge/*` + `src/pages/knowledge/`.
- Library listing/overview/ingestion use additive `/api/knowledge/library*` contracts on KnowledgeStore + SourceIngestionService. Vector Search reuses `/api/knowledge/search`. Graph/Datasets/Notes/Settings navigate to canonical owners.
- Production never imports `mocks/knowledgeLibraryV2VisualFixture` as defaults. Visual fixture: `src/mocks/knowledgeLibraryV2VisualFixture.ts` + `e2e/helpers/knowledgeLibraryV2Visual.ts` + `e2e/knowledge-v2.visual.spec.ts` (reference: `docs/ui_reference/knowledge-library-v2-reference.png`).
- Totale Bronnen counts Knowledge documents (not chunks). Totale Grootte is measured-bytes + coverage. Embedding Status uses chunk coverage; NOT CONFIGURED when provider absent. READY ≠ embedded.