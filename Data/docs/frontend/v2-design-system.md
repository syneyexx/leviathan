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
