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

## Models migration

- `/models` uses `AppShell variant="v2"` with shared `AppSidebarV2` / `AppTopbarV2` (title "LM / Models").
- LM is a new expandable nav group, derived from `MAIN_MENU` via `v2ChildrenFromMainMenu("llm")`. Its `match` claims only `/models` — `/agents`, `/training`, `/dataset-management`, `/offline-datasets`, and `/analytics` stay owned by their existing dedicated top-level Dashboard/Training items (route-ownership pattern, same as the Hades AI / Research groups).
- `ModelsPage.tsx` composes four card rows (Runtime Provider / Hardware / VRAM; Model list / Load Config / Multi-GPU / Advanced; wide Optimalisatie; Resource Estimate / Performance / Actions) plus a manage-links footer that opens drawers for the existing `ProviderManager`, `ModelGatewayPanel`, `ModelRouterPanel`, and `ModelResidencyPanel` panels — those advanced surfaces are reused unchanged, not rebuilt.
- All page composition lives in `src/components/models/*` (11 focused card components + `useModelsWorkspace` for data/mutation orchestration). No page-local CSS file; layout, form controls (select/range/toggle rows, tables, meters) live in `leviathan-v2.css` under `.lv-v2-page--models` / `.lv-v2-models-*`.
- Capability-gating truth discipline: LM Studio control-plane fields the active provider/version doesn't support render disabled with a visible "Niet ondersteund door LM Studio …" note (`ws.capNote()` / `ws.capSupport()`), instead of silently hiding the control. A small hardcoded set (`seed`, `cpuThreads`, `prefixCache`) is always disabled because LM Studio has no control surface for them at all today.
- No fake hardcoded hardware/metrics in the production path — `useModelsWorkspace` only calls the real Model Control Plane APIs (`Data/backend/routes/models.py`, `Data/modules/models/*`, including the LM Studio control (`lm_studio_control.py`) and optimizer (`optimizer.py`) modules). Only the dedicated visual-fixture module below may contain deterministic mock data, gated behind `window.__LV_V2_VISUAL_FIXTURE__`.
- Visual fixture: `src/mocks/modelsV2VisualFixture.ts` + helper `e2e/helpers/modelsV2Visual.ts` + `e2e/models-v2.visual.spec.ts` (reference: `docs/ui_reference/models-v2-reference.png`), covering load, nav-ownership, and interaction flows (select model, search, edit context/offload/GPU-split, estimate, optimize, load/unload).

