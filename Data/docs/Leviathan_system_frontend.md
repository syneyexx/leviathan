# LEVIATHAN System Frontend Reference

> **Canonical frontend reference.** This file is the single human-readable source of truth for LEVIATHAN’s React operator interface: bootstrap, routing, navigation, API contracts, state, pages, components, styling, truth semantics, tests and exact code locations.
>
> **Snapshot:** `main` at `1c30a3d062b03f8b77eb14b9ae8dee16979fcb61` (2026-09-28), after the autonomous trading research closed-loop merge.
>
> Backend companion: [`Leviathan_system_backend.md`](./Leviathan_system_backend.md).

---

# 1. Documentation contract

`Data/docs/` contains two canonical LEVIATHAN system documents only: this frontend reference and the backend reference. Component-local README/spec/test files may exist beside code, but they do not supersede these canonical maps.

Frontend product-truth rules:

```text
page exists != backend capability is available
button exists != action is authorized
spinner != work completed
model prose != tool/verification receipt
selected model != resident model
configured provider != healthy provider
TRAIN-positive != qualified trading strategy
mock fixture != production state
UNMEASURED / UNAVAILABLE / BLOCKED != green success
```

Production UI must derive truth from backend contracts. Explicit mock/demo data must remain labeled and isolated from production routes.

---

# 2. Stack, build and entrypoints

Primary frontend root: `Data/frontend/`.

Current stack:

- React 19;
- React Router 7;
- TypeScript 5.9;
- Vite 7;
- Vitest 3;
- oxlint;
- browser-native fetch/EventSource-style streaming through the central API layer.

Core files:

| File | Role |
|---|---|
| `Data/frontend/src/main.tsx` | browser bootstrap/mount |
| `Data/frontend/src/App.tsx` | authoritative route graph, lazy trading routes, ErrorBoundary/Suspense |
| `Data/frontend/src/layouts/AppShell.tsx` | common application shell |
| `Data/frontend/src/navigation/menu.ts` | main/sidebar/subnavigation model |
| `Data/frontend/src/api/client.ts` | central compatibility API facade |
| `Data/frontend/src/api/http.ts` | shared HTTP helper |
| `Data/frontend/src/api/domains/` | domain-split clients, incrementally replacing giant-client internals |
| `Data/frontend/src/types/` | shared backend-facing TypeScript contracts |
| `Data/frontend/src/hooks/` | shared live/status/telemetry/toast hooks |
| `Data/frontend/src/state/` | shared UI state |
| `Data/frontend/src/styles/` | global/page design system CSS |
| `Data/frontend/src/assets/` | production static imagery |
| `Data/frontend/src/mocks/` | explicit test/demo fixtures only |
| `Data/frontend/vite.config.ts` | Vite build/dev configuration |
| `Data/frontend/package.json` | scripts/dependencies |

Production output is `Data/frontend/dist/`.

Optional `editor/` integration is not a default frontend dependency: the Vite editor plugin is loaded only when the editor mode environment switch is explicitly enabled and the plugin is available. LEVIATHAN’s production client must build without the editor tree.

---

# 3. App shell and layout ownership

The UI is one application shell, not a collection of independent micro-frontends.

`src/layouts/AppShell.tsx` owns the page frame around routed content. Shared shell components live in `src/components/` (header/sidebar/footer/navigation/status/supporting common components). `main#main-content` and the skip link provide the primary keyboard/a11y landmark.

General layout contract:

```text
App
 └─ ErrorBoundary
     └─ BrowserRouter
         └─ AppShell
             ├─ global/header chrome
             ├─ primary navigation
             ├─ secondary navigation where configured
             ├─ routed main content
             └─ global toast/status overlays
```

Shell status must be measured. App chrome must not claim “SYSTEMS ONLINE/OPERATIONAL” merely because the React app mounted.

Relevant shared hooks:

- `src/hooks/useShellStatus.ts` — health/readiness projection;
- `src/hooks/useSystemTelemetry.ts` — telemetry;
- `src/hooks/useLiveEvents.ts` — live backend events;
- `src/hooks/useClock.ts` — UI clock;
- `src/hooks/useToast.ts` — toast surface.

Tests include `shellStatus.test.ts` / `useShellStatus.test.ts` and page-specific contract tests.

---

# 4. Navigation model

`src/navigation/menu.ts` is the human-facing navigation source. Current groups are:

| Group | Main destinations |
|---|---|
| Hades AI | Chatten, Coding Agent, Taken |
| LLM | Modellen, Agents, Training, Dataset Management, Offline Datasets, Statestieken |
| Media Control | Overview, YouTube, TikTok, Instagram, Facebook, Queue, Viral Radar, Calendar, Analytics, Library, Personas |
| TradingCenter | Simulation, Strategies, Market Data, Portfolio, PAPER, BROKER, Onderzoek, Research Lab, Control Room |
| Onderzoek & Kennis | Research, Brain, Geheugen, Knowledge, Evidence, Datasets |
| Plugin & Runtime | Performance, Tools, Modules, Skills, MCP, Workflows, Console |
| Settings | General plus behavior, studio, security, benchmarks, media, storage, runtime, logs, RAG, cognition, agents, tools, market-sim and data/research sections |

The “Hades AI” navigation label is UI naming. It does not make `Data/HADES/` the canonical owner of Chat/Coding/Tasks; those routes are backed by LEVIATHAN’s normal backend systems.

---

# 5. Authoritative route map

`src/App.tsx` is the final routing authority. Current routes:

## Core

| Route | Page/behavior |
|---|---|
| `/` | `CommandPage` |
| `/status` | redirect to `/tasks` |
| `/tasks` | `TasksPage` |
| `/chat` | `ChatPage` |
| `/coding` | `CodingPage` |
| `/models` | `ModelsPage` |
| `/training` | `TrainingPage` (V2) |
| `/dataset-management` | `DatasetManagementPixelPage` |
| `/offline-datasets` | `OfflineDatasetsPixelPage` |
| `/agents` | `AgentsPage` |
| `/analytics` | `AnalyticsPage` |

## Media

| Route | Page |
|---|---|
| `/media` | Media overview |
| `/media/youtube` | YouTube surface |
| `/media/tiktok` | TikTok surface |
| `/media/instagram` | Instagram surface |
| `/media/facebook` | Facebook surface |
| `/media/queue` | publication queue |
| `/media/viral` | Viral Radar |
| `/media/calendar` | media calendar |
| `/media/analytics` | current Media Analytics section surface |
| `/media/library` | media library |
| `/media/personas` | personas |

## TradingCenter

Trading pages are lazy-loaded and rendered inside Suspense/ErrorBoundary.

| Route | Page |
|---|---|
| `/trading` | redirect to `/trading/simulatie` |
| `/trading/simulatie` | `SimulatiePage` |
| `/trading/strategieen` | `StrategieenPage` |
| `/trading/marktdata` | `MarktdataPage` |
| `/trading/portefeuille` | `PortefeuillePage` |
| `/trading/paper` | `PaperTradingPage` |
| `/trading/broker` | `BrokerTradingPage` |
| `/trading/onderzoek` | `OnderzoekPage` → Research Command |
| `/trading/lab` | `ResearchLabPage` |
| `/trading/control-room` | `InstitutionalControlRoomPage` |

## Research/knowledge

| Route | Page |
|---|---|
| `/research` | `ResearchPage` |
| `/brain` | `BrainPage` |
| `/cognition` | `CognitionPage` |
| `/memory` | `GeheugenPage` |
| `/knowledge` | `KnowledgeLibraryPage` |
| `/evidence` | `EvidenceVaultPage` |
| `/datasets` | `DatasetsPage` |

## Plugin/runtime

| Route | Page |
|---|---|
| `/performance` | `PerformancePage` |
| `/tools` | `ToolsPage` |
| `/modules` | ModuleManager operator console |
| `/skills` | `SkillsPage` |
| `/mcp` | `McpPage` |
| `/workflows` | `WorkflowsPage` |
| `/console` | `ConsolePage` |

## Settings/compatibility

`/settings` and settings subroutes use `SettingsPage`. Historical settings aliases redirect to the canonical sections. `/chat.html` is a compatibility redirect to `/chat`; wildcard routes redirect to `/`.

When route documentation and an old page file disagree, `App.tsx` wins.

---

# 6. API/client architecture

Frontend code should not create page-local transport stacks when a central client/domain module exists.

## 6.1 Shared HTTP

`src/api/http.ts` owns common request behavior. `src/api/client.ts` is the public facade used by much of the app and contains compatibility wrappers while domain clients are split incrementally.

Domain clients live under `src/api/domains/`; for example `marketSimLab.ts` owns Research Lab calls instead of page-local `fetch()`.

Shared API types are under `src/types/`. Keep these aligned with backend response contracts instead of weakening them to broad `any`.

## 6.2 Streaming/events

`src/hooks/useLiveEvents.ts` and chat streaming helpers consume public operational events. Eligible UI events include cognition state, tool/module/job progress, artifact/source observations, worker status and structured **activity** events (`event: activity`). Private reasoning/chain-of-thought is never a UI event contract.

Chat status helpers under `src/lib/` normalize shared semantics, including `jobStatus.ts`, `executionFabric.ts` and `activityProjector.ts` (client-side reconciliation mirroring backend `ActivityProjector`).

## 6.3 Errors

API failures must remain errors/degraded state. Do not convert a missing response into zero counts or “healthy”. The global ErrorBoundary catches rendering failures; route/page state still owns domain-specific loading/error/empty states.

---

# 7. Product-truth presentation model

Common backend statuses include `SUPPORTED`, `UNSUPPORTED`, `UNMEASURED`, `UNAVAILABLE`, `NOT_CONFIGURED`, `FEATURE_GATED`, `WAITING_APPROVAL`, `BLOCKED`, `DEGRADED`, `PARTIAL`, `READY`, `FAILED`, etc. Pages should preserve the backend distinction.

Rules:

- Unknown dataset state uses neutral/muted UI, never “processed” green.
- A module discovered in the catalog is not RUNNING/READY.
- A model registered in the catalog is not resident/healthy.
- Search enabled is not web-search ready.
- An agent’s confidence is not verification.
- Trading TRAIN/validation/sealed/qualification are distinct states.
- Paper trading is simulated capital and visually distinct from live broker state.
- Backend `UNMEASURED` fields display dashes/labels, not numeric zero.

Explicit demo/mock data must use demo/mock labeling. Production route code should not import decorative mocks as runtime truth.

---

# 8. Chat UI

Primary file: `src/pages/ChatPage.tsx`.

Supporting chat code includes:

- `src/pages/chatTelemetry.ts` — converts real `assistant_telemetry`/cognition fields into display data;
- `src/pages/chat/CapabilityResultCards.tsx` — backend-backed tool result cards;
- `src/pages/chat/MessageList.tsx` — messages + institutional activity timeline;
- `src/components/activity/ActivityTimeline.tsx` — reusable ActivityTimeline / DecisionReceiptView (global V2);
- `src/types/activity.ts` — ActivityEvent / ActivityProjection / DecisionReceipt contracts;
- `src/lib/activityProjector.ts` — dedupe/order/stale reconciliation;
- chat streaming/status helpers and tests near the page/lib directories.

Current Chat surfaces:

- conversation history/input;
- requested/effective reasoning information when returned;
- Direct vs TEAM collaboration selector;
- model identity/status;
- Brain/Memory/Evidence/retrieval usage;
- sources/citations/web usage;
- tool calls with backend status/duration/receipt/result/artifact/source information;
- specialist/agent delegation;
- verification/quality/completion state;
- **structured operational activity timeline** (compact / detailed / developer) backed by backend `activity` SSE + `done.activity`;
- decision receipts when the backend attaches authoritative DecisionPacket/risk projections;
- Stop/abort for in-flight streams (timeline shows cancellation requested/propagating/cancelled from backend truth).

Legacy `reasoning.steps` (`understand_request`, `generate_answer`) remain a compatibility fallback only when no activity projection is present. The UI never asks a model to invent operational state. Missing/disconnected activity renders STALE/UNKNOWN — never synthetic COMPLETED.

TEAM quality data is backend-owned. Criterion labels/rations come from `/api/chat`/`/api/team`; the UI never invents a “7/10 rounds” target for open-ended TEAM work.

No private chain-of-thought panel exists or should be added. Public plan/event/rationale metadata is acceptable when explicitly emitted by the backend.

Contract tests: `src/pages/chatCodingContracts.test.ts`, `src/lib/activityProjector.test.ts` and chat-specific tests.

---

# 9. Cognition UI

`src/pages/CognitionPage.tsx` is the operator-facing cognition/run surface. It displays durable public run state rather than implementing reasoning in the browser.

Backend owner: `Data/modules/cognition/`; HTTP: `/api/cognition/*`.

The page may expose run state, plan/activity, requested/effective mode, evidence/tool/agent usage, verification, steering/cancel/resume controls where the API supports them. It must not fabricate unsupported frontier-reasoning gate states merely because machine program manifests mention them.

The frontier reasoning gate manifest under `Data/backend/tests/frontier_reasoning_gates.json` remains a conservative machine ledger. Frontend rendering should follow actual API fields, not phase-name marketing.

---

# 10. Models UI

Route: `/models` — Leviathan V2 (`AppShell variant="v2"`).

Canonical composition: `src/pages/models/ModelsPage.tsx` + `src/hooks/useModelsWorkspace.ts`
+ `src/components/models/*` (runtime provider, hardware, VRAM reserve, catalog, load config,
multi-GPU, advanced options, optimization, estimates, actions). Styling lives only in
`leviathan-v2.css` under `.lv-v2-page--models` (no Models-specific stylesheet).

Advanced panels remain reachable (import dialog, provider settings, gateway/router/residency
drawers):

- `HardwareInventoryPanel.tsx` — measured host/model hardware;
- `ModelCatalog.tsx` — registry/catalog;
- `ModelDownloadManager.tsx` — acquisition state/actions;
- `ModelGatewayPanel.tsx` — gateway/inflight/queue;
- `ModelImportDialog.tsx` — import;
- `ModelInspector.tsx` — model/profile detail;
- `ModelResidencyPanel.tsx` — residency;
- `ModelRouterPanel.tsx` — routing;
- `ModelServingPanel.tsx` — serving/runtime;
- `ModelStatusCards.tsx` — summary;
- `ModelTestConsole.tsx` — controlled inference test;
- `ProviderManager.tsx` — providers.

Load/estimate/optimize/unload go through the Model Control Plane API only (never browser →
LM Studio). Capability-unsupported controls are disabled with an honest reason. Visual
fixtures for Screen 1 live in `src/mocks/modelsV2VisualFixture.ts` (TEST ONLY).

The page must distinguish registry presence, provider availability, active routing, residency, READY serving and measured capabilities. Vision/tool/structured-response/reasoning support is only shown as supported when backend capability probes say so.

---

# 11. Agents and Worker Fabric UI

Route: `/agents`; primary file `src/pages/AgentsPage.tsx` (V2 shell).

`/agents` is owned by **LLM → Agents** in MAIN_MENU / V2 LM group (no standalone top-level Agents rail owner). Workspace orchestration lives in `src/hooks/useAgentsWorkspace.ts`; Screen 1 panels under `src/components/agents/`. Supporting modals/helpers remain under `src/pages/agents/` (editor, launch mission, Worker Fabric, Signal Fabric, trade orchestra). `agentsPageContracts.test.ts` protects important source/API contracts. Visual fixture: `src/mocks/agentsV2VisualFixture.ts` + `e2e/agents-v2.visual.spec.ts`.

The page combines **agent identity** and **execution infrastructure** without confusing them:

- Agent Fleet cards come from backend agent/system inventory.
- Trading agents are ordinary Fleet-backed roles.
- Worker Fabric monitor reads `GET /api/workers/dashboard` (advanced drawer + architecture pools).
- “Active Agents” is fleet health (enabled + known state); Active Workers remain a separate worker-registry concept.
- STARTING worker is not healthy READY.
- Model assignment uses `modelRef` → Model Control Plane; GPU/VRAM tuning stays on `/models`.
- Native compute status is backend-probed, not mocked; unmeasured tool-call KPIs read UNMEASURED.

Primary worker panel: `WorkerPoolsPanel` within the Agents supporting component tree (advanced surfaces).

---

# 12. Coding and Tasks UI

## Coding

Route `/coding`; `src/pages/CodingPage.tsx` with local contracts under `src/pages/coding/`.

It operates on real CodingControlPlane sessions/actions. File/test claims must come from backend receipts; the browser does not perform the coding mutation itself.

## Tasks

Route `/tasks`; `src/pages/TasksPage.tsx`.

**Dashboard / Taken** is a V2 AppShell projection of TaskService + JobRuntime (not a second task runtime).

Composition:

- `hooks/useTasksWorkspace.ts` — bounded `/api/tasks*` polling (~5.5s, visibility-aware, no overlapping loads), filters, selection via `?task=`, stale/error flags, system telemetry for Resource Gebruik / sidebar meters;
- `components/tasks/TasksHero.tsx` / `TasksMetrics.tsx` / `TasksOverviewTable.tsx` / `TasksDetailPanel.tsx` / `TasksBottomGrid.tsx`;
- `pages/tasks/TaskCreateDialog.tsx` — canonical create path (`POST /api/tasks`);
- styles under `.lv-v2-page--tasks` in `leviathan-v2.css` (no page-local Taken CSS import).

Truth rules:

- KPI totals/running/waiting/completedLast7Days/failed/typeCounts/sparklines come from `GET /api/tasks/summary`;
- table rows are real `TaskRecord` enrichments (`taskType`, `operationalStatus`, `displayId`, `progressKnown`, `controls`);
- progress unknown stays unknown (never silent `0%`);
- Pauzeren is disabled — JobRuntime has no pause; Stop/cancel/duplicate/priority use TaskService;
- Results tab reads linked `GET /api/jobs/{jobId}` when present; logs are bounded task events; config arguments are redacted server-side;
- Resource meters use `useSystemTelemetry` (`UNAVAILABLE` when unmeasured).

Navigation: MAIN_MENU Dashboard child **Taken** → `/tasks`. `/status` redirects here. Kanban helpers under `pages/tasks/TaskBoard.tsx` remain in-tree but are not the active Taken surface.

Reference: `Data/docs/ui_reference/taken-v2-reference.png` (design authority; not production data).

---

# 13. Brain, Memory, Knowledge and Evidence UI

These are intentionally distinct backend concepts.

## Brain — `/brain`

`src/pages/BrainPage.tsx` composes:

- `components/brain/BrainNetworkSection.tsx` — **Kennis Netwerk** Panel (`BrainDnaNetwork` + workbench) beside **Geselecteerde Node**; shared `overview.setSelectedId`;
- `pages/brain/BrainLivingNetworkCanvas.tsx` — Canvas 2D double-helix / Relaties mode (refs + rAF; keyboard index for a11y);
- `pages/brain/BrainNetworkWorkbench.tsx` — Bewijs / Kennishiaten / Vergelijken / Agents / Wijzigingen / Bewaren inside `.lv-v2-brain-network-panel`;
- `pages/brain/brain-helix-engine.ts` / `brain-activation.ts` / `brain-knowledge-model.ts` — pure layout, Chat→Brain activation projection, gap/evidence helpers (no mock demo data);
- `hooks/useKnowledgeActivation.ts` — projects `brain.knowledge_activation` runtime events (SSE `/api/events/stream`);
- `pages/brain/BrainGraphCanvas.tsx` — technical graph with hover labels for node identity/type/cluster (no detached promo badges);
- Celestial Nexus / `BrainSpaceCanvas.tsx` — live celestial visualization with intentionally slower orbital/ambient motion for readability;
- `BrainTreeView.tsx` — hierarchy;
- `BrainClustersView.tsx` + `brain-cluster-layout.ts` — clusters layout (deterministic cluster keys, expanded canvas sizing for dense graphs);
- `brain-graph-layout.ts` / tests — force/cluster positioning contracts;
- `BrainAnalyticsView.tsx` — analytics;
- `BrainTimelineView.tsx` — timeline;
- `brain-live.ts` — live API mapping;
- `brain-shared.tsx` — shared contracts/components;
- explicitly named mock support for tests/reference only.

Current graph views are backed by `/api/brain/graph`; selection/filter state remains under BrainPage / `useBrainOverview` ownership. Hover labels are graph-native (title/type/cluster), not floating marketing chips.

The Brain main owns vertical scrolling because the legacy shell slot uses `display: contents`. The knowledge section must not flex-shrink: its canvas, activation strip and workbench determine the panel height. The mobile shell column uses `minmax(0, 1fr)` to keep the stage inside the viewport. Canvas backing dimensions track the actual panel size and device pixel ratio.

Rotation follows the pause control, including when a node is selected. Reset restores angle, tilt, zoom and display defaults; background graph refreshes preserve an explicitly cleared selection. Labels use bounded collision avoidance, all loaded nodes remain keyboard-selectable, and relation layout is calculated once per frame rather than once per node. Memory mutations refresh the authoritative graph.

### Chat → Brain knowledge activation

When chat retrieval completes with document/memory ids, the backend emits observability event `brain.knowledge_activation` (`Data/modules/brain/activation_events.py`) with `node_ids` mapped to Brain facade ids (`knowledge:document:…`, `memory:…`), plus `request_id` / `conversation_id` / `run_id` / `hit_count` / `identifiers_available`. Hit counts alone never light nodes — Brain shows “Geen node-identificatie beschikbaar”. Open `/chat` and `/brain` in separate tabs; Brain follows live events without manual refresh. Multiple concurrent requests are selectable in the Kennis Netwerk status strip.

The activation strip reports how many retrieved IDs are visible in the current bounded/filtered graph and shows stream connection status. It does not invent or fetch unrelated nodes to fill gaps. Explicit document IDs take precedence over chunk IDs. Automatic request following uses first observed request sequence, so a late completion cannot take focus from a newer request within the event buffer; cancelled/unavailable requests clear their highlights.

Historical graph snapshots are **not** reconstructed from `created_at`. Workbench history tab states unavailability honestly until a real snapshot contract exists.

## Memory — `/memory`

`src/pages/GeheugenPage.tsx` presents the Leviathan V2 **Geheugen** control plane under `AppShell variant="v2"` with shared `AppSidebarV2` / `AppTopbarV2`.

Composition: `useMemoryWorkspace` + `src/components/memory/*` (hero, KPIs, search/table, right column, bottom analytics, dialogs/drawer).

Screen 1 layout lives only in global `leviathan-v2.css` under `.lv-v2-page--memory` / `.lv-v2-memory-*` — no page-local Memory CSS.

Research group children stay MAIN_MENU-derived via `v2ChildrenFromMainMenu` — Geheugen is selected on `/memory`; screenshot submenu labels are not navigation truth.

Production UI never falls back to mock/demo Memory totals. Screen 1 parity data exists only in `src/mocks/memoryV2VisualFixture.ts` (Playwright). Reference: `docs/ui_reference/memory-v2-reference.png`.

Backend authority remains `MemoryStore` on the CONTROL database:

- cursor pagination + filters on `GET /api/memory`
- overview aggregates on `GET /api/memory/overview`
- real pin/unpin (`POST .../pin|unpin`), PATCH metadata, correction/supersede, archive/restore/revoke
- lexical / semantic / hybrid search with honest degradation
- semantic index on CONTROL (`memory_embeddings`) via memory worker → embedding.batch
- analytics / activity / search telemetry
- automatic processing policy in Settings (`memory.processing.*`)

Memory ≠ Knowledge ≠ Brain. Document upload opens Knowledge; web save opens Research; conversation save is an explicit operator action.

## Knowledge — `/knowledge`

`src/pages/KnowledgeLibraryPage.tsx` presents documents, retrieval/index/ingestion state and related operations.

## Evidence — `/evidence`

`src/pages/EvidenceVaultPage.tsx` presents evidence/verification records.

Do not merge their concepts into a single fake “brain database” UI.

---

# 14. General Research UI

Route `/research`; owner `src/pages/ResearchPage.tsx`. `ResearchMockPage.tsx` is explicit mock/reference code and is not the canonical route.

Configuration: `src/config/research.ts`.

The page projects real ResearchService state:

- project/run lifecycle;
- research plan and workers;
- local retrieval;
- source upload/ingestion;
- claims/evidence/conflicts/reports;
- real source URLs/citations;
- outbound network and web-search readiness as separate states;
- `READY`, `FETCH ONLY` or `UNAVAILABLE` from `/api/research/web/readiness`;
- web research probe via `/api/research/web/probe`;
- Normal/Custom/TEAM execution modes.

Evidence=0 alone is not a diagnosis. The UI should display backend reasons such as search unavailable, no sources, fetch blocked or no supporting evidence.

---

# 15. Datasets UI

Two related surfaces exist:

- `/datasets` → `src/pages/DatasetsPage.tsx` and `src/pages/datasets/` — research/knowledge dataset surface;
- `/dataset-management` → `src/pages/pixel/DatasetManagementPixelPage.tsx` — operator management view;
- `/offline-datasets` → `src/pages/pixel/OfflineDatasetsPixelPage.tsx` — offline dataset tooling.

Supporting dataset code includes:

- `DatasetActivityConsole.tsx`;
- `datasetActivity.ts`;
- `useDatasetActivity.ts`;
- `datasetsInventory.ts`;
- `datasetLearningState.ts`;
- dataset activity/management tests.

Dataset Management uses `displayName ?? name`, category/tags/search and semantic re-analysis APIs. `REINDEX_REQUIRED` is never shown as learned Brain state.

Job/activity panels expose backend compute truth (`python_streaming` / `rust_native`) and progress. Missing peak RSS/spill/throughput remains UNMEASURED.

Explicit demo rows are labeled DEMO and are protected from appearing as live inventory.

---

# 16. Training and evaluation-facing UI

`/training` routes to the Leviathan V2 **Model Training** page (`TrainingPage` + `useTrainingWorkspace` + `src/components/training/*`) under the canonical **LLM → Training** menu ownership (`v2ChildrenFromMainMenu("llm")`). There is no top-level Training rail owner.

Visual language lives only in global `leviathan-v2.css` under `.lv-v2-page--training` / `.lv-v2-training-*` — no Training-specific stylesheet.

Production UI never falls back to mock/demo training state. Screen 1 parity data exists only in `src/mocks/trainingV2VisualFixture.ts` (Playwright). Reference: `docs/ui_reference/training-v2-reference.png`.

The Training Engine card shows **Leviathan Trainer** (PyTorch / Transformers / PEFT / TRL). LM Studio is an inference runtime, not the trainer.

Training pages display real jobs, capabilities, hardware, datasets/versions, trainable models, checkpoints, and metrics. Method badges and readiness come from `/api/training/capabilities` — fixture-only environments are not production-ready. A configured recipe must not be shown as “trained” or “GPU completed” without backend evidence.

Evaluation/analytics data used by Training or model pages should come through central API contracts; no client-side score fabrication.

---

# 17. Analytics and command surfaces

- `src/pages/CommandPage.tsx` — root command/dashboard;
- `src/pages/AnalyticsPage.tsx` — LLM/system analytics;
- `src/pages/PerformancePage.tsx` — performance/native/DB contention read model;
- `src/pages/ConsolePage.tsx` — console/operator projection;
- `src/pages/SectionPage.tsx` — generic section/fallback surface for unfinished submenu destinations.
- `src/pages/PlaceholderPage.tsx` — **deprecated** re-export of `SectionPage` (WAVE 42 inventory). Do not delete while imports remain; new code must use `SectionPage`.

Operational numbers use backend telemetry. Zero is a measurement only when the backend measured zero.

---

# 18. TradingCenter — shared architecture

Primary tree: `src/pages/trading/`.

Shared page support: `src/pages/trading/shared.tsx` and trading-specific view-model/helper folders. Backend authority is MarketSim; the UI does not calculate canonical PnL/qualification itself.

Current top-level pages:

- `SimulatiePage.tsx` — simulation;
- `StrategieenPage.tsx` — strategy definitions/versions;
- `MarktdataPage.tsx` — data registration/inspection;
- `PortefeuillePage.tsx` — portfolio;
- `PaperTradingPage.tsx` — paper execution/operator page;
- `BrokerTradingPage.tsx` — explicit live broker boundary;
- `OnderzoekPage.tsx` — re-exports Research Command page;
- `researchLab/ResearchLabPage.tsx` — autonomous Research Lab;
- institutional Control Room page under trading tree.

`/api/market-sim/capabilities` is the UI capability authority: family support, operating modes, execution granularity and action matrix. BAR_OHLCV must never be drawn/labeled as L2/L3. Unknown/unmeasured/blocked capability uses neutral/degraded styling.

**Live-money trading remains BLOCKED.** Broker UI presence is not readiness, and no page may expose an unguarded live-enable control.

---

# 19. Simulation, strategies and market data pages

## Simulation — `/trading/simulatie`

`src/pages/trading/SimulatiePage.tsx` builds causal MarketSim runs. Run builder explicitly exposes capital/engine/cadence instead of silently creating a multi-agent topology. Activity/orders/metrics are API-backed.

## Strategies — `/trading/strategieen`

`StrategieenPage.tsx` lists/creates/inspects strategy definitions and versions from MarketSim. Status/lineage/compatibility are backend truth.

## Market data — `/trading/marktdata`

`MarktdataPage.tsx` handles registered/imported sources, readiness and provider metadata. Historical data version/seal/split state comes from MarketSim; frontend does not infer data quality from file presence.

## Portfolio — `/trading/portefeuille`

`PortefeuillePage.tsx` displays canonical MarketSim portfolio/accounting state.

---

# 20. Paper Trading UI

Route `/trading/paper`; source is `PaperTradingPage.tsx` plus `pages/trading/paper/`.

Important components include:

- `PaperTradingChartPanel.tsx` — chart from backend OHLCV;
- `PaperTradingChartShell.tsx` — chart panel chrome/state;
- additional paper orchestrator/portfolio/positions/orders/analytics/risk/activity components in the same directory;
- styles in `src/styles/trading-paper.css`.

The page consumes real paper-session/portfolio/capability APIs. Equity/PnL/positions/orders are backend sourced. If profit factor or another metric is not exposed, it remains unavailable rather than being synthesized.

Durable A3/A4 deployments are simulated capital. Kill switch/flatten/pause controls call canonical paper APIs.

---

# 21. Trading Research Command UI

Route `/trading/onderzoek`.

`src/pages/trading/OnderzoekPage.tsx` re-exports `researchCommand/ResearchCommandPage.tsx`. Supporting code:

- `researchCommand/ResearchCommandPage.tsx` — composition;
- `researchCommand/ResearchCommandPanels.tsx` — panels;
- `researchCommand/useResearchCommand.ts` — data/action hook;
- `researchCommandContracts.test.ts` — source contract coverage.

Research Command is an operator **composition** over existing TradingOrchestra, paper portfolio, news and Research Lab. It is not a frontend or backend second learner.

Current projections include session state, orchestration/decision/news state, paper portfolio, bound lab run mode/stage, active hypotheses, best-candidate/qualification summary and paper-forward drift tickets when available.

Start/pause/flatten/kill-switch/evolution actions call their backend owners. Live remains blocked.

---

# 22. Autonomous Research Lab UI

Route `/trading/lab`; root `src/pages/trading/researchLab/`.

Current files/directories:

- `ResearchLabPage.tsx` — three-column operator workspace and modal composition;
- `hooks/useResearchLab.ts` — API-backed state, polling, lifecycle and create flow;
- `components/` — run rail, tabs/panels/details/create dialog support;
- `viewModels.ts` — backend→display derivation;
- `viewModels.test.ts` — truth/derivation tests;
- API domain: `src/api/domains/marketSimLab.ts`;
- relevant styles under `src/styles/` trading/research-lab files.

## 22.1 Create modes

The create flow supports:

**AUTONOMOUS_DISCOVERY**
- no existing `strategyId` required;
- research objective/hypothesis;
- READY market data source;
- autonomy ceiling/budgets;
- optional model/chart-vision research policy;
- optional research scope/dataset bundle from backend contracts.

**SEED_EXISTING_STRATEGY**
- retains strategy selector/version seed behavior.

The frontend must not manufacture a dummy seed strategy for autonomous discovery.

## 22.2 Lab data surfaces

Current lab APIs/client methods cover overview, cost pack, feed health, list/get/create/start/pause/resume/cancel, learning state, generations, candidates, run trials, lessons, hypotheses, perception, strategy-family labels and candidate explainability.

Tabs/panels expose only backend-backed data:

- overview/progress;
- generations/population and family probabilities;
- candidate lineage/proposal method;
- hypotheses;
- causal numeric/chart perception when measured;
- validation/qualification information when returned;
- evidence-linked lessons;
- paper/forward/drift context;
- public run events/logs.

Candidate labels distinguish TRAIN leader, validation/sealed/qualified states. A high TRAIN score is not rendered as “profitable/qualified” without the corresponding backend evidence.

## 22.3 Chart perception

Chart vision is advisory. The page may render a deterministic backend artifact and typed observation if the backend measured a chart-capable model. `UNAVAILABLE` chart vision is a valid state; numeric perception continues. Visual observations never create order controls.

## 22.4 Explain candidate

`GET /api/market-sim/lab/runs/{labId}/candidates/{candidateId}/explain` returns structured evidence for explanation drawers/cards. The UI should display the hypothesis, proposal origin/lineage, measured trials, rejection gates and evidence refs rather than asking an LLM to invent a retroactive story.

---

# 23. Institutional Control Room UI

Route `/trading/control-room`.

The page consumes `GET /api/market-sim/institutional/control-room` and related institutional projections. It surfaces live-trading BLOCKED state, qualification/research/data-plane/fabric information, reconciliation breaks/exceptions and audit-chain state when measured.

A catalog entry or missing metric must never be painted green. Empty/unmeasured is explicit.

---

# 24. Broker/live boundary UI

Route `/trading/broker`; `BrokerTradingPage.tsx`.

This page is a boundary/status surface. It must preserve backend LiveTradingGuard posture and cannot add a hidden UI-only bypass. Paper controls are not live controls. External finance modules/tools remain research/analytics capabilities unless MarketSim explicitly exposes a safe paper action.

---

# 25. Media Control UI

Media pages live in `src/pages/media/` with shared widgets/components in `src/components/media/`. Static imagery/crops live under `src/assets/media-control/`.

When media providers are not connected, pages use truthful `NOT CONNECTED` / `UNAVAILABLE` presentation through shared truth banners/unavailable shells. Follower/reach/revenue KPIs must not be fabricated from reference/mock assets.

Routes are listed in section 5. The Media Analytics route currently uses the generic section surface in `App.tsx`; route truth should be updated here when a dedicated page becomes active.

---

# 26. Tools UI

Route `/tools`; `src/pages/ToolsPage.tsx`.

Tools represent ExecutionGateway/CapabilityCatalog truth. Availability, risk/approval, last invocation and receipts are backend-owned. Chat capability cards reuse shared execution presentation where possible.

No page should call a tool provider directly to bypass central capability policy.

---

# 27. ModuleManager UI

Route `/modules`.

Canonical workspace: `src/pages/plugin-runtime/ModulesPage.tsx` plus `src/pages/plugin-runtime/modules/` (`viewModels.ts`, workspace hook/components) and `src/styles/modules-page.css`. Any top-level compatibility wrapper should delegate to this workspace.

Supported operator functions include:

- discover/refresh;
- install planning/install;
- start/stop/restart/ensure-ready;
- health/logs/jobs/capabilities;
- execute;
- sweep idle modules;
- check update/version list;
- install version/activate/rollback.

## Dependency-aware install UI

The UI requests the backend install plan, showing declared runtime/application/system dependencies, detected package manager, privilege needs, blockers and planned actions. If privileged system changes require approval, the operator approves the exact plan/argument digest and then starts the persisted install operation.

Phase state is polled from `/api/modules/{id}/install-state`, e.g. planning → system deps → fetch/stage → runtime/app deps → post-install → verify → READY/FAILED.

Client helpers include `moduleInstallPlan`, `moduleInstallState` and `installModule` on the API facade/domain code. The frontend never treats a click as installation success.

Layout invariant: module header/search/filters are compact; `.lv-mod-rows` owns remaining scroll height. Search/icon styling must remain scoped to the module page.

---

# 28. Skills UI

Route `/skills`; `src/pages/plugin-runtime/SkillsPage.tsx`.

The page supports installed skills and bounded external catalog search. Enable/disable and instruction load use `/api/skills`. Instruction bodies are loaded on demand; catalog scale does not imply thousands of instructions enter prompt/context.

Skill execution still uses backend capability authority. Catalog presence and enabled state are separate.

---

# 29. MCP, Workflows and Console UI

- `/mcp` → `src/pages/McpPage.tsx`: server/session/tool state from backend MCP bridge;
- `/workflows` → `src/pages/WorkflowsPage.tsx`: workflow store/runtime control;
- `/console` → `src/pages/ConsolePage.tsx`: operator console projection;
- `/performance` → `src/pages/PerformancePage.tsx`: performance/native/DB read model.

MCP tool invocation is not a direct browser-to-MCP channel; backend gateway/approval semantics remain authoritative.

---

# 30. Settings UI

Route `/settings`; `src/pages/SettingsPage.tsx` plus `src/pages/settings/` and V2 composition under `src/components/settings/`:

- V2 shell via `AppShell variant="v2"` + `useSettingsWorkspace`;
- `SettingsCategoryNav` / `SettingsGeneralPanel` / providers & system config panels;
- `SettingField.tsx` — typed field editor (catalog);
- `RestartRequiredBadge.tsx` — apply-mode truth;
- `settingsPage.test.ts` — contracts.

Canonical docs: `Data/docs/frontend/settings-v2.md`. Reference: `docs/ui_reference/settings-v2-reference.jpg`.

Current settings sections are catalog-driven (Algemeen UI prefs, LLM behavior, LLM Studio, Rights & Security, Model Benchmarks, MediaCenter, Storage, Python & Runtime, Console, Logs, Knowledge & RAG, Cognition & Neuro, Agents & Coding, Tools & MCP, Market Simulation and Data & Research).

Settings are catalog-driven from the backend. Type/range/enum/secret/restart semantics should not be redefined page-locally.

Native compute, worker, market and research controls appear only if present in the backend Settings catalog.

Provider rows on Algemeen are Model Control Plane projections — credentials never round-trip to the browser.

---

# 31. SQLite Manager UI

The SQLite Manager is an operator surface over CONTROL/KNOWLEDGE/MARKET and is normally reached through relevant runtime/settings tooling.

Frontend API methods in the central client cover overview, tables/schema/index/FKs, bounded rows, read/write SQL, row insert/update/delete, integrity, WAL checkpoint, ownership audit and runtime/commit/backup metadata.

Mutation safety rules:

- selected database domain is explicit;
- changing domain clears previous table/row/query mutation state;
- backend requires `confirmDomain` for writes;
- update/delete requires deterministic row identity;
- schema DDL is not a console operation.

Frontend never treats SQLite Manager as a fourth data store.

---

# 32. Shared components, hooks, libraries, state and types

## Components

`src/components/` owns reusable visual pieces including shell/navigation, error/demo/truth wrappers, media widgets and cross-page presentation components. Prefer shared components over page-specific copies when semantics match.

## Hooks

`src/hooks/` owns cross-page behavior: live events, shell status, telemetry, clock, toasts and other generic hooks. Domain-heavy hooks should live beside the domain page (e.g. Research Lab workspace hook).

## Libraries

`src/lib/executionFabric.ts` — shared capability/execution display contracts.

`src/lib/jobStatus.ts` — JobRuntime status formatting/normalization.

Other `src/lib/` helpers should remain pure/shared; backend authority stays in API responses.

## State

`src/state/` contains global UI state such as toast/application coordination. Avoid duplicating backend durable state in a browser store when polling/SSE/API is already authoritative.

## Types

`src/types/` contains shared TypeScript contracts. Domain APIs may keep narrower colocated types where appropriate, but do not create conflicting duplicate shapes for the same response.

---

# 33. Assets and styles

## Assets

`src/assets/` includes core hero/background/avatar/globe imagery and `media-control/` assets. Assets are presentation only and never evidence that a capability is connected.

## Styles

Global/page CSS lives under `src/styles/`. Preserve the common LEVIATHAN design language rather than introducing a new design system for every screen.

Trading, modules, research, brain and media pages have dedicated style files where the layout requires it. Prefer scoped selectors for page-specific SVG/flex behavior to avoid global regressions.

Responsive layouts should preserve scroll ownership and information hierarchy at typical desktop widths. Dense operator pages should scroll the data panel, not expand compact header/search elements to consume the viewport.

---

# 34. Accessibility and resilience

Current application-level protections include:

- global ErrorBoundary;
- React.lazy/Suspense around the TradingCenter route family;
- skip-to-content link and `main#main-content`;
- semantic buttons/labels for interactive controls;
- explicit loading/error/empty/degraded states.

A11y additions should preserve keyboard navigation and visible focus without bypassing the common AppShell.

---

# 35. Frontend testing

Primary commands:

```bash
cd Data/frontend
npm test
npm run typecheck
npm run lint
npm run build
```

Tests live beside relevant pages/helpers and include shell status, Chat/Coding, Agents, datasets, Settings, Research Lab view-models/contracts, Research Command contracts, module/skills/chat fabric contracts and truth-state helpers.

Bounded Playwright E2E lives under `Data/frontend/e2e/` (`npm run test:e2e`) covering smoke startup, Brain Graph, Brain Clusters, and agent/worker fabric surfaces with stubbed `/api`. CI job `frontend-e2e` is optional (`continue-on-error`) and skips honestly when browsers are unavailable — never a fake PASS. Live-backend browser integration remains separate. Hover-first Brain Graph labels and celestial reduced-motion/delta-clamp are covered by unit tests under `src/pages/brain/`.

Playwright/MSW full live-backend coverage remains feature-gated unless CI runs against a live control plane. Never claim E2E coverage because a plan mentions it.

For a UI PR, minimum expectation is typecheck + relevant Vitest + build; lint when configured/available.

---

# 36. Backend contract map for frontend work

| UI area | Backend owner / route family |
|---|---|
| Chat | `POST /api/chat`, Cognition, Brain, ExecutionGateway |
| Cognition | `/api/cognition/*`, `/api/team/*` |
| Models | `/api/models/*`, Model Control Plane |
| Agents | `/api/agents/*`, Agent Fleet |
| Worker Fabric | `/api/workers/*` |
| Coding | `/api/coding/*`, CodingControlPlane |
| Tasks | `/api/tasks/*`, JobRuntime/workflows |
| Brain | `/api/brain/*` |
| Memory | `/api/memory/*` |
| Knowledge | `/api/knowledge/*` |
| Evidence | `/api/evidence/*` |
| Research | `/api/research/*` |
| Datasets | `/api/datasets/*` |
| Training | `/api/training/*` |
| Tools | `/api/capabilities/*`, `/api/functions/*` |
| Modules | `/api/modules/*` |
| Skills | `/api/skills/*` |
| MCP | `/api/mcp/*` |
| Workflows | `/api/workflows/*` |
| Settings | `/api/settings/*` |
| SQLite Manager | `/api/sqlite/*` |
| Trading | `/api/market-sim/*`, `/api/trading-orchestra/*` |
| Research Command | research-command route module/API family |
| Media | `/api/media/*` |
| Browser | `/api/browser*` |
| Voice | `/api/voice/*` |
| Host/runtime | `/api/host/*`, `/api/system/*`, `/api/performance/*`, events |

Always inspect the current client function and backend route before adding a page-local endpoint spelling.

---

# 37. Complete frontend locator for Cursor

| Need | Start here |
|---|---|
| browser bootstrap | `src/main.tsx` |
| routes/lazy loading | `src/App.tsx` |
| primary/sub navigation | `src/navigation/menu.ts` |
| shell/chrome | `src/layouts/AppShell.tsx`, `src/components/` |
| backend HTTP | `src/api/http.ts`, `src/api/client.ts` |
| domain API | `src/api/domains/` |
| shared backend types | `src/types/` |
| live events | `src/hooks/useLiveEvents.ts` |
| shell health | `src/hooks/useShellStatus.ts` |
| telemetry | `src/hooks/useSystemTelemetry.ts` |
| Chat | `src/pages/ChatPage.tsx`, `src/pages/chat/`, `chatTelemetry.ts` |
| Cognition | `src/pages/CognitionPage.tsx` |
| Models | `src/pages/ModelsPage.tsx`, `src/pages/models/` |
| Agents/workers | `src/pages/AgentsPage.tsx`, `src/pages/agents/` |
| Coding | `src/pages/CodingPage.tsx`, `src/pages/coding/` |
| Tasks | `src/pages/TasksPage.tsx` |
| Brain | `src/pages/BrainPage.tsx`, `src/pages/brain/` |
| Memory | `src/pages/GeheugenPage.tsx` |
| Knowledge | `src/pages/KnowledgeLibraryPage.tsx` |
| Evidence | `src/pages/EvidenceVaultPage.tsx` |
| General Research | `src/pages/ResearchPage.tsx`, `src/config/research.ts` |
| Datasets | `src/pages/DatasetsPage.tsx`, `src/pages/datasets/`, `src/pages/pixel/*Dataset*` |
| Training | route in `App.tsx`, training/pixel page family |
| Analytics | `src/pages/AnalyticsPage.tsx` |
| Trading shared | `src/pages/trading/` |
| Simulation | `src/pages/trading/SimulatiePage.tsx` |
| Strategies | `src/pages/trading/StrategieenPage.tsx` |
| Market data | `src/pages/trading/MarktdataPage.tsx` |
| Portfolio | `src/pages/trading/PortefeuillePage.tsx` |
| Paper | `src/pages/trading/PaperTradingPage.tsx`, `src/pages/trading/paper/` |
| Broker boundary | `src/pages/trading/BrokerTradingPage.tsx` |
| Research Command | `src/pages/trading/researchCommand/`, `OnderzoekPage.tsx` |
| Research Lab | `src/pages/trading/researchLab/`, `src/api/domains/marketSimLab.ts` |
| Control Room | trading institutional Control Room page |
| Media | `src/pages/media/`, `src/components/media/`, `src/assets/media-control/` |
| Tools | `src/pages/ToolsPage.tsx` |
| Modules | `src/pages/plugin-runtime/ModulesPage.tsx`, `src/pages/plugin-runtime/modules/` |
| Skills | `src/pages/plugin-runtime/SkillsPage.tsx` |
| MCP | `src/pages/McpPage.tsx` |
| Workflows | `src/pages/WorkflowsPage.tsx` |
| Performance | `src/pages/PerformancePage.tsx` |
| Console | `src/pages/ConsolePage.tsx` |
| Settings | `src/pages/SettingsPage.tsx`, `src/pages/settings/` |
| execution display | `src/lib/executionFabric.ts` |
| job display | `src/lib/jobStatus.ts` |
| global state | `src/state/` |
| images | `src/assets/` |
| styles | `src/styles/` |
| mocks/demo | `src/mocks/` and explicitly named mock files |

---

# 38. Frontend contribution rules

When changing LEVIATHAN UI:

1. **Find the backend owner first.** The page is usually a projection/control surface, not the business-logic owner.
2. **Use the central API client/domain module.** Avoid page-local duplicate transports.
3. **Preserve truth states.** Missing/unmeasured/unavailable is not success or numeric zero.
4. **Do not expose hidden CoT.** Public plan/activity/evidence is fine; private reasoning is not.
5. **Do not create a second shell/design system.** Extend AppShell/shared components/styles.
6. **Do not make mocks production truth.** Keep them explicit and labeled.
7. **Keep TypeScript contracts strict.** Update backend/API/types together.
8. **Add relevant tests.** Prefer view-model/helper contract tests for truth-sensitive derivation.
9. **Update this document** whenever a route, page owner, API module, status contract or major file location changes.
10. **Update the backend companion** when the UI change requires a backend contract change.

---

# 39. High-value invariants

```text
App.tsx is route truth
menu.ts is navigation truth
backend is capability/status truth
central API/domain clients own transport
AppShell owns common chrome
page-local state does not replace durable backend state
UNMEASURED is neutral, never green
mock/demo is never production truth
model output is not execution proof
public reasoning metadata may be shown; hidden CoT may not
MarketSim owns trading metrics/qualification
Research Command is composition, not a second learner
Research Lab may discover strategies autonomously without a fake seed
chart vision is advisory
paper uses simulated capital
live-money trading remains BLOCKED
```

---

# 40. Institutional UI notes (CURRENT)

- **Brain graph hover labels / celestial slower / clusters layout** — see §13 Brain; layout owners `brain-graph-layout.ts`, `brain-cluster-layout.ts`, celestial motion tuned in `brain-space.ts` / `BrainSpaceCanvas.tsx`.
- **Paper trading operator surface** — `/trading/paper` projects RiskGuard envelope, kill switch, autonomous loop receipts; does not invent broker authority.
- **Research claim graph** — Research UI may show SUPPORTS/CONTRADICTS/QUALIFIES/BACKGROUND/INSUFFICIENT edges from backend claim graphs; model prose is not relation proof.
- **Governance** — PRs use `.github/PULL_REQUEST_TEMPLATE.md`; branch protection requirements in `Data/docs/github_branch_protection.md` (operator-applied, not agent-claimed).
- **Autonomous paper runbook** — backend companion §31.