# LEVIATHAN System Frontend Reference

> **Canonical frontend documentation.** This is the single human-readable reference for LEVIATHAN's React/TypeScript UI, route structure, client contracts and frontend file organization.
>
> Snapshot: **2026-09-25**, based on `main` after the Frontier Reasoning F0 baseline merge. Code and tests are authoritative when this file becomes stale.
>
> Backend reference: [`Leviathan_system_backend.md`](./Leviathan_system_backend.md).

---

# 1. Frontend purpose and stack

The frontend is the operator interface for LEVIATHAN's control planes. It is not an independent source of capability truth: buttons, badges and status views should reflect backend state rather than invent availability or success.

Current stack (`Data/frontend/package.json`):

- React 19;
- React DOM 19;
- React Router DOM 7;
- TypeScript 5.9;
- Vite 7;
- Vitest 3;
- oxlint.

Scripts:

```bash
npm run dev
npm run build
npm run lint
npm run typecheck
npm test
npm run preview
```

Production builds are emitted to `Data/frontend/dist` and served by the FastAPI backend when present.

---

# 2. Frontend repository layout

```text
Data/frontend/
├── index.html
├── package.json
├── package-lock.json
├── vite.config.ts
├── tsconfig.json
├── tsconfig.app.json
├── tsconfig.node.json
├── .oxlintrc.json
├── public/
└── src/
    ├── App.tsx
    ├── main.tsx
    ├── editorContentRuntime.ts
    ├── api/
    ├── assets/
    ├── components/
    ├── config/
    ├── hooks/
    ├── layouts/
    ├── lib/
    ├── mocks/
    ├── navigation/
    ├── pages/
    ├── state/
    ├── styles/
    └── types/
```

`main.tsx` bootstraps React. `App.tsx` owns application routing. `layouts/AppShell.tsx` owns the shared shell. `navigation/menu.ts` owns the visible primary/submenu model.

---

# 3. Application shell

## Shared UI

`Data/frontend/src/components/`:

- `AppHeader.tsx` — top-level header/status controls;
- `AppSidebar.tsx` — primary navigation;
- `AppFooter.tsx` — footer/subnavigation shell;
- `BrandMark.tsx` — LEVIATHAN branding component;
- `Toast.tsx` — toast rendering;
- `media/` — shared Media Control UI components.

`Data/frontend/src/layouts/AppShell.tsx` composes the application chrome around routed content.

## Shared state

`Data/frontend/src/state/`:

- `ToastContext.tsx`;
- `toastContextValue.ts`;
- `useAppToast.ts`.

The current frontend deliberately keeps global client state relatively small; much operational state is backend-backed and queried through the typed API client/hooks.

---

# 4. Navigation model

`Data/frontend/src/navigation/menu.ts` is the canonical menu definition.

Current top-level groups:

1. **Hades AI** — Chatten, Coding Agent, Taken;
2. **LLM** — Modellen, Agents, Training, Dataset Management, Offline Datasets, Statestieken;
3. **Media Control** — overview/platform/queue/radar/calendar/analytics/library/personas;
4. **TradingCenter** — simulation, strategies, market data, portfolio, paper, broker, research;
5. **Onderzoek & Kennis** — Research, Brain, Geheugen, Knowledge Library, Evidence Vault, Datasets;
6. **Plugin & Runtime** — Performance, Tools, Modules, MCP, Workflows, Console;
7. **Instellingen** — general, LLM behavior/studio, rights/security, benchmarks, media, storage, Python/runtime, console/logs, Knowledge & RAG, Cognition & Neuro, Agents & Coding, Tools & MCP, Market Simulation, Data & Research.

The historical display label `Hades AI` is a UI navigation label; backend ownership and runtime documented here are LEVIATHAN.

---

# 5. Route map

`Data/frontend/src/App.tsx` currently wires the SPA routes.

| Route | UI owner |
|---|---|
| `/` | `CommandPage` |
| `/status` | redirects to `/tasks` |
| `/tasks` | `TasksPage` |
| `/chat` | `ChatPage` |
| `/chat.html` | compatibility redirect to `/chat` |
| `/coding` | `CodingPage` |
| `/models` | models control page |
| `/agents` | `AgentsPage` |
| `/training` | Training pixel/production page route |
| `/dataset-management` | Dataset Management pixel page |
| `/offline-datasets` | Offline Datasets pixel page |
| `/analytics` | `AnalyticsPage` |
| `/research` | `ResearchPage` |
| `/brain` | `BrainPage` |
| `/cognition` | `CognitionPage` |
| `/memory` | `GeheugenPage` |
| `/knowledge` | `KnowledgeLibraryPage` |
| `/evidence` | `EvidenceVaultPage` |
| `/datasets` | `DatasetsPage` |
| `/performance` | runtime performance page |
| `/tools` | `ToolsPage` |
| `/modules` | modules/runtime page |
| `/mcp` | `McpPage` |
| `/workflows` | `WorkflowsPage` |
| `/console` | console page |
| `/settings` | `SettingsPage` |

Media routes:

- `/media`
- `/media/youtube`
- `/media/tiktok`
- `/media/instagram`
- `/media/facebook`
- `/media/queue`
- `/media/viral`
- `/media/calendar`
- `/media/analytics`
- `/media/library`
- `/media/personas`

Trading routes:

- `/trading` → `/trading/simulatie`
- `/trading/simulatie`
- `/trading/strategieen`
- `/trading/marktdata`
- `/trading/portefeuille`
- `/trading/paper`
- `/trading/broker`
- `/trading/onderzoek`

Settings aliases route to `/settings?section=...` for the appropriate operator category.

---

# 6. Backend API client and live events

## `src/api/`

- `client.ts` — centralized typed API client for LEVIATHAN backend routes;
- `client.test.ts` — API-client contract tests;
- `chatStream.boundary.test.ts` — chat streaming boundary tests.

Do not introduce page-local duplicate fetch wrappers when a canonical client method exists. API types and backend truth should stay aligned.

## Hooks

`src/hooks/` currently contains:

- `useLiveEvents.ts` — live/backend event consumption;
- `useShellStatus.ts` — shell/runtime status;
- `useSystemTelemetry.ts` — system telemetry;
- `useClock.ts` — UI clock;
- `useToast.ts` — toast helper;
- `shellStatus.test.ts`, `useShellStatus.test.ts` — shell/status tests.

---

# 7. Chat and Cognition UI

## Current

- `pages/ChatPage.tsx` is the user-facing conversation UI.
- `pages/CognitionPage.tsx` exposes cognition/run state separately.
- Chat consumes the backend chat/cognition/model systems; the frontend must not synthesize reasoning success, tool execution or citations.

Current main contains the F0 baseline of the Frontier Reasoning program. The existing frontend has **not** yet earned the future F17 reasoning-control gate merely because the master program describes it.

## TARGET — Frontier Reasoning F17

Planned UI additions, only to be marked CURRENT after implementation/tests:

- per-message `Auto / Fast / Standard / Deep / Maximum` reasoning selector;
- requested versus effective reasoning mode;
- native-reasoning capability/effort where measured;
- public activity panel (plan/search/tool/test/verify events);
- model/tool/source/agent usage summary;
- verification/completion status;
- no private chain-of-thought rendering.

---

# 8. Models UI

`pages/ModelsPage.tsx` is a thin route-facing wrapper; the substantial model UI lives in `pages/models/`.

Verified current files include:

- `ModelsPage.tsx` — composed models workspace;
- `HardwareInventoryPanel.tsx` — host/model hardware visibility;
- `ModelCatalog.tsx` — registry/catalog;
- `ModelDownloadManager.tsx` — download state/actions;
- `ModelGatewayPanel.tsx` — gateway/inflight state;
- `ModelImportDialog.tsx` — model import workflow;
- `ModelInspector.tsx` — detailed model/profile inspection;
- `ModelResidencyPanel.tsx` — model residency controls/state;
- `ModelRouterPanel.tsx` — routing view;
- `ModelServingPanel.tsx` — serving/runtime view;
- `ModelStatusCards.tsx` — summary status;
- `ModelTestConsole.tsx` — controlled model testing;
- `ProviderManager.tsx` — provider management.

The UI must distinguish selected, active, resident, available and supported. A provider/model listed in the UI is not automatically loaded or capable of every operation.

TARGET from Frontier Reasoning: model profiles will additionally expose native reasoning capability/effort/token-budget support once backend F2/F3 support is implemented and verified.

---

# 9. Agents, Coding and Tasks UI

## Agents

`pages/AgentsPage.tsx` is the main agent control surface. Supporting files under `pages/agents/` include:

- `TradeOrchestraSection.tsx`;
- `helpers.ts`;
- `tradingHelpers.ts`.

`agentsPageContracts.test.ts` protects page/backend contracts.

Agent cards/status must reflect actual `AgentFleet`/SystemInventory/backend state. Orchestrators are represented through the same backend ownership rather than a fake second agent system.

## Coding

- `pages/CodingPage.tsx` — Coding Agent workspace;
- `pages/coding/types.ts` — local UI contracts;
- `chatCodingContracts.test.ts` — Chat/Coding contract tests.

The page operates on real CodingControlPlane sessions and must not claim file writes/tests without backend state/receipts.

## Tasks

`pages/TasksPage.tsx` is the durable task/operator surface. It consumes TaskService/job/workflow state rather than maintaining an independent task engine.

---

# 10. Brain, Memory, Knowledge and Evidence UI

## Brain

`pages/BrainPage.tsx` composes the visual Brain interface. `pages/brain/` contains:

- `BrainGraphCanvas.tsx` — graph visualization;
- `BrainTreeView.tsx` — hierarchical view;
- `BrainClustersView.tsx` — cluster view;
- `BrainAnalyticsView.tsx` — analytics;
- `BrainTimelineView.tsx` — timeline;
- `brain-live.ts` — live backend mapping;
- `brain-shared.tsx` — shared UI/contracts;
- `brain-mock.ts` — explicit mock/test support; production state must use live backend data.

## Memory

`pages/GeheugenPage.tsx` exposes durable memory views/actions.

## Knowledge

`pages/KnowledgeLibraryPage.tsx` exposes Knowledge/RAG documents/chunks/search/ingestion state.

## Evidence

`pages/EvidenceVaultPage.tsx` displays evidence/verification-related records.

These pages represent different backend concepts and should not collapse Brain, Memory, Knowledge and Evidence into one undifferentiated store.

---

# 11. Research UI

`pages/ResearchPage.tsx` is the active Research workspace. `ResearchMockPage.tsx` remains an explicit mock/reference page and is not the canonical `/research` route.

`src/config/research.ts` contains research UI configuration/constants.

Research UI should expose actual project/run/source/worker state and distinguish:

- local retrieval;
- outbound permission;
- configured web search;
- source upload/ingestion;
- active worker state;
- claims/evidence/conflicts.

Do not render fabricated “web searched” state when the backend provider is unavailable.

---

# 12. Dataset and Training UI

## Datasets

`pages/DatasetsPage.tsx` is the research/knowledge-side dataset surface. Supporting `pages/datasets/` files:

- `DatasetActivityConsole.tsx`;
- `datasetActivity.ts`;
- `useDatasetActivity.ts`;
- `datasetsInventory.ts`;
- `datasetActivity.test.ts`;
- `datasetManagementActions.test.ts`.

The LLM navigation also exposes dedicated Dataset Management and Offline Datasets pixel pages wired through `App.tsx`.

## Training

`/training` currently routes to the production/pixel Training page family. A legacy/top-level `TrainingPage.tsx` also exists in the tree; route truth in `App.tsx` wins.

Training UI must show real training jobs, recipes, readiness, candidate versions and evaluation state. It must not imply that a training recipe ran on GPU or promoted a model unless backend evidence says so.

---

# 13. TradingCenter UI

`pages/trading/` contains:

- `SimulatiePage.tsx` — causal simulation/runs/agents/activity with explicit run builder (`initialCash`, `engine` single|multi, `decisionCadence`); default is single-strategy (no silent multi-agent roster);
- `StrategieenPage.tsx` — strategy definitions/versions;
- `MarktdataPage.tsx` — market-data registration/inspection;
- `PortefeuillePage.tsx` — portfolio view;
- `PaperTradingPage.tsx` — paper trading against real `/api/market-sim/paper` + capabilities;
- `BrokerTradingPage.tsx` — broker/live boundary and guarded state (live remains BLOCKED);
- `OnderzoekPage.tsx` — trading research;
- `shared.tsx` — shared TradingCenter components/contracts.

This UI sits on the existing `MarketSimControlPlane` and trading-orchestra backend. It must not imply live-money readiness or profitability. Paper/simulation state is distinct from live broker state. No mock success badges.

T1 backend additions consumed by TradingCenter (no mock data): sealed/versioned market datasets (`/api/market-sim/datasets`, `/api/market-sim/data/import`), run knowledge snapshots (`/api/market-sim/runs/{id}/knowledge-snapshot`), and causal `MarketView` / epistemic `as_of` boundaries on historical runs.

T2 backend: simulation rounds persist deterministic `MarketState` (regime/trend/volatility/features with provenance). UI continues to read live run events — no fabricated order-book capabilities.

**P4C:** SimulatiePage run builder is explicit; PaperTradingPage and capabilities come from the live API. G41/G42 PASS.

**Slice 16:** TradingCenter UI remains paper/sim-backed only. Live broker stays BLOCKED; A5 is impossible. No mock-success badges. Gate evidence: G41/G42/G48 PASS. Remaining advanced ops gates (G49–G60) stay honest NOT_STARTED.

---

# 14. Media Control UI

The Media Control family is routed from `App.tsx` and grouped under `pages/media/` plus shared `components/media/`.

Routes cover:

- overview;
- YouTube;
- TikTok;
- Instagram;
- Facebook;
- publication queue;
- Viral Radar;
- calendar;
- media analytics;
- library;
- personas.

`src/assets/media-control/` contains the visual asset/crop set used by these pages. Media UI capability must reflect the backend media/provider posture; UI presence is not proof that every external platform integration is configured.

---

# 15. Runtime / tools / MCP / workflows UI

- `pages/ToolsPage.tsx` — canonical capability/tool surface;
- `pages/McpPage.tsx` — MCP servers/sessions/tools;
- `pages/WorkflowsPage.tsx` — workflow controls;
- `pages/ModulesPage.tsx` — thin wrapper/runtime module page;
- `pages/PerformancePage.tsx` — thin wrapper/performance page;
- `pages/ConsolePage.tsx` — thin wrapper/console page.

Runtime-oriented supporting pages/components also live in page subdirectories (`pages/plugin/`, `pages/runtime/` where present). Route wiring in `App.tsx` is authoritative.

`src/lib/executionFabric.ts` contains shared execution-fabric UI helpers/contracts. `src/lib/jobStatus.ts` normalizes job status/presentation logic.

---

# 16. Settings UI

`pages/SettingsPage.tsx` is the settings control surface. `pages/settings/` contains:

- `SettingsNavigation.tsx` — settings subsection navigation;
- `SettingField.tsx` — typed setting editor;
- `RestartRequiredBadge.tsx` — apply-mode visibility;
- `settingsPage.test.ts` — UI contract test.

Navigation currently exposes settings sections for:

- General;
- LLM behavior;
- LLM Studio;
- Rights & Security;
- Model Benchmarks;
- MediaCenter;
- Storage;
- Python & Runtime;
- Console;
- Logs;
- Knowledge & RAG;
- Cognition & Neuro;
- Agents & Coding;
- Tools & MCP;
- Market Simulation;
- Data & Research.

Settings are backend-owned. The frontend should honor validation, enum/range constraints and HOT/restart-required semantics returned by the Settings Control Plane.

---

# 17. Analytics, command and operator surfaces

- `pages/CommandPage.tsx` — primary command/dashboard landing;
- `pages/AnalyticsPage.tsx` — LLM/system analytics;
- `pages/StatusPage.tsx` — status implementation file retained even though the current `/status` route redirects to Tasks;
- `pages/SectionPage.tsx` and `PlaceholderPage.tsx` — reusable/placeholder route surfaces.

Operator status should use real health/telemetry/job/model/system inventory APIs.

---

# 18. Assets and styling

## Assets

`src/assets/` contains static imagery such as:

- `hero.jpg`;
- `coding-hero.jpg`;
- `analytics-hero.jpg`;
- `architecture-bg.jpg`;
- `avatar.jpg`;
- `globe.jpg`;
- `earth-mini.jpg`;
- `media-control/` and its prepared crops/tiles.

Binary assets are intentionally described by directory/purpose here rather than duplicated as an image-by-image catalog.

## Styling

Global and page-specific styles live under `src/styles/`. Preserve the LEVIATHAN shell/layout classes and shared style conventions rather than introducing a second design system per page.

---

# 19. Mocks and truth boundaries

`src/mocks/` and explicitly named mock files may support development/tests. Production routes must prefer backend-backed state.

Frontend invariant:

```text
button exists != backend capability available
spinner != work completed
model prose != execution receipt
UI status != verified status unless backend-backed
mock fixture != production integration
```

Where a backend returns `UNAVAILABLE`, `UNMEASURED`, `NOT_CONFIGURED`, `WAITING_APPROVAL`, `PARTIAL` or similar states, the UI should render that state honestly instead of converting it to success.

---

# 20. Frontend tests

Current frontend scripts:

```bash
cd Data/frontend
npm test
npm run typecheck
npm run lint
npm run build
```

Tests exist beside system surfaces, including API client/streaming, shell status, Agents, Chat/Coding, datasets and Settings contracts. New pages/actions should add tests close to the relevant module.

---

# 21. Frontend file locator

Use this map when changing UI behavior:

| Need | Start here |
|---|---|
| Route/page wiring | `src/App.tsx` |
| App bootstrap | `src/main.tsx` |
| Main/sub navigation | `src/navigation/menu.ts` |
| Shell layout | `src/layouts/AppShell.tsx` |
| Header/sidebar/footer | `src/components/App*.tsx` |
| Backend API | `src/api/client.ts` |
| Live events | `src/hooks/useLiveEvents.ts` |
| Health/shell state | `src/hooks/useShellStatus.ts` |
| System telemetry | `src/hooks/useSystemTelemetry.ts` |
| Chat | `src/pages/ChatPage.tsx` |
| Cognition | `src/pages/CognitionPage.tsx` |
| Coding | `src/pages/CodingPage.tsx`, `src/pages/coding/` |
| Models | `src/pages/models/` |
| Agents | `src/pages/AgentsPage.tsx`, `src/pages/agents/` |
| Brain | `src/pages/BrainPage.tsx`, `src/pages/brain/` |
| Memory | `src/pages/GeheugenPage.tsx` |
| Knowledge | `src/pages/KnowledgeLibraryPage.tsx` |
| Evidence | `src/pages/EvidenceVaultPage.tsx` |
| Research | `src/pages/ResearchPage.tsx`, `src/config/research.ts` |
| Datasets | `src/pages/DatasetsPage.tsx`, `src/pages/datasets/` |
| Training | route in `App.tsx`, training/pixel page family |
| Trading | `src/pages/trading/` |
| Media | `src/pages/media/`, `src/components/media/` |
| Tools | `src/pages/ToolsPage.tsx` |
| MCP | `src/pages/McpPage.tsx` |
| Workflows | `src/pages/WorkflowsPage.tsx` |
| Settings | `src/pages/SettingsPage.tsx`, `src/pages/settings/` |
| Shared execution presentation | `src/lib/executionFabric.ts` |
| Job presentation | `src/lib/jobStatus.ts` |
| Toast state | `src/state/`, `src/hooks/useToast.ts` |
| Images | `src/assets/` |
| Styles | `src/styles/` |
| Shared TS types | `src/types/` |

---

# 22. Frontier Reasoning frontend program status

The master implementation program preserves the existing frontend and adds reasoning surfaces only after backend phases establish real data.

Current documentation snapshot:

- F0 baseline is present on `main`;
- F1–F16 are backend/intelligence phases to be implemented/verified sequentially;
- **F17** is the dedicated frontend/settings phase;
- F18 is final hardening.

Do not pre-render fake F17 values. Future reasoning UI must be driven by actual backend fields/events added by the earlier phases.

Machine reasoning gates remain at `Data/backend/tests/frontier_reasoning_gates.json`; UI gate R25 is not PASS until implementation/tests prove it.

---

# 23. Frontend architecture rules

1. Backend capability/status is authoritative.
2. Use the central API client instead of page-specific duplicate transports where possible.
3. Keep the common AppShell/navigation rather than building isolated micro-frontends.
4. Preserve real error/degraded/unmeasured states.
5. Keep mock/test data explicitly marked and out of production truth paths.
6. Do not expose private chain-of-thought; only public reasoning/activity metadata is eligible for UI.
7. Update this document when routes, pages, API ownership or major file organization changes.
8. Update the backend companion document when a UI change adds or changes an API contract.
