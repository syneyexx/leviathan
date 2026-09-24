# Trading Center Frontend Action Matrix (T0)

**Status:** T0 inventory only; G57 not PASS.  
**Gate:** Master Program v4 **G57** remains `NOT_STARTED` until every row is verified functional, intentionally read-only with explained copy, or removed. Decorative controls cannot satisfy the gate.  
**Scope:** Visible buttons / menus / tabs / inputs / links on TradingCenter routes + trading submenu.  
**PASS column (T0):** `INVENTORIED` — inventory only; do not treat as G57 PASS.

Sources audited:

- `Data/frontend/src/pages/trading/SimulatiePage.tsx`
- `Data/frontend/src/pages/trading/StrategieenPage.tsx`
- `Data/frontend/src/pages/trading/MarktdataPage.tsx`
- `Data/frontend/src/pages/trading/PaperTradingPage.tsx`
- `Data/frontend/src/pages/trading/PortefeuillePage.tsx`
- `Data/frontend/src/pages/trading/BrokerTradingPage.tsx`
- `Data/frontend/src/pages/trading/shared.tsx`
- `Data/frontend/src/App.tsx` (trading routes only)
- `Data/frontend/src/navigation/menu.ts` (trading submenu)
- Shell chrome on trading pages: `AppHeader` search (via `AppShell`)

Side-effect classes: `READ` | `MUTATION` | `NAV` | `DECORATIVE` | `READONLY_EXPLAINED`

---

## Missing v4 pages (NOT_PRESENT)

| Page | Control | Type | Endpoint / capability | Side-effect class | Success/error/busy/disabled | Test | PASS |
|---|---|---|---|---|---|---|---|
| Onderzoek | — | page | No `/trading/onderzoek` route or submenu item | NOT_PRESENT | — | — | INVENTORIED |
| Validatie | — | page | No `/trading/validatie` route or submenu item | NOT_PRESENT | — | — | INVENTORIED |
| Bibliotheek | — | page | No `/trading/bibliotheek` route or submenu item | NOT_PRESENT | — | — | INVENTORIED |
| Training | — | page | No `/trading/training` route or submenu item | NOT_PRESENT | — | — | INVENTORIED |
| Risico | — | page | No `/trading/risico` route or submenu item | NOT_PRESENT | — | — | INVENTORIED |

---

## Navigation (`menu.ts` + `App.tsx`)

| Page | Control | Type | Endpoint / capability | Side-effect class | Success/error/busy/disabled | Test | PASS |
|---|---|---|---|---|---|---|---|
| Nav | TradingCenter (hoofdmenu) | link | `to=/trading/simulatie` | NAV | Always enabled | — | INVENTORIED |
| Nav | Simulatie (submenu) | link | `to=/trading/simulatie` | NAV | Always enabled | — | INVENTORIED |
| Nav | Strategieen (submenu) | link | `to=/trading/strategieen` | NAV | Always enabled | — | INVENTORIED |
| Nav | Marktdata (submenu) | link | `to=/trading/marktdata` | NAV | Always enabled | — | INVENTORIED |
| Nav | Portefeuille (submenu) | link | `to=/trading/portefeuille` | NAV | Always enabled | — | INVENTORIED |
| Nav | PAPER trading (submenu) | link | `to=/trading/paper` | NAV | Always enabled | — | INVENTORIED |
| Nav | BROKER trading (submenu) | link | `to=/trading/broker` | NAV | Always enabled | — | INVENTORIED |
| App | `/trading` redirect | route | `<Navigate to="/trading/simulatie" replace />` | NAV | Immediate redirect | — | INVENTORIED |
| App | Route `/trading/simulatie` | route | Renders `SimulatiePage` | NAV | — | — | INVENTORIED |
| App | Route `/trading/strategieen` | route | Renders `StrategieenPage` | NAV | — | — | INVENTORIED |
| App | Route `/trading/marktdata` | route | Renders `MarktdataPage` | NAV | — | — | INVENTORIED |
| App | Route `/trading/portefeuille` | route | Renders `PortefeuillePage` | NAV | — | — | INVENTORIED |
| App | Route `/trading/paper` | route | Renders `PaperTradingPage` | NAV | — | — | INVENTORIED |
| App | Route `/trading/broker` | route | Renders `BrokerTradingPage` | NAV | — | — | INVENTORIED |

---

## Shell chrome on trading pages (`AppHeader` via `AppShell`)

Visible on Strategieen / Marktdata (and any trading page using default shell header).

| Page | Control | Type | Endpoint / capability | Side-effect class | Success/error/busy/disabled | Test | PASS |
|---|---|---|---|---|---|---|---|
| Shell | Header search | input | Focus only (Ctrl/⌘K); no query handler / no trading filter | READONLY_EXPLAINED | Placeholder copy only (e.g. “Search strategies…”, “Search symbols…”); no onChange/submit | — | INVENTORIED |
| Shell | Menu button | button | Opens shell sidebar (`onMenuClick`) | NAV | Always enabled | — | INVENTORIED |
| Shell | Status chips (system / agents / LLM) | display | `useShellStatus` reads | READ | Display-only; not clickable | — | INVENTORIED |

---

## Simulatie (`SimulatiePage.tsx`)

| Page | Control | Type | Endpoint / capability | Side-effect class | Success/error/busy/disabled | Test | PASS |
|---|---|---|---|---|---|---|---|
| Simulatie | Source | select | Local state → used by create run; options from `GET /api/market-sim/data` | READ | `disabled={!enabled}` when feature flag off | — | INVENTORIED |
| Simulatie | Strategy | select | Local state → optional `strategyId` on create; options from `GET /api/market-sim/strategies` | READ | `disabled={!enabled}` | — | INVENTORIED |
| Simulatie | New multi-agent run | button | `POST /api/market-sim/runs` then `POST …/runs/{id}/start` | MUTATION | Error banner; `busy`; `disabled={!enabled \|\| busy}`; errors if no source | — | INVENTORIED |
| Simulatie | Start | button | `POST /api/market-sim/runs/{id}/start` | MUTATION | Error banner; `busy`; `disabled={!selectedId \|\| busy}` | — | INVENTORIED |
| Simulatie | Pause | button | `POST /api/market-sim/runs/{id}/pause` | MUTATION | Error banner; `busy`; `disabled={!selectedId \|\| busy}` | — | INVENTORIED |
| Simulatie | Step | button | `POST /api/market-sim/runs/{id}/step` | MUTATION | Error banner; `busy`; `disabled={!selectedId \|\| busy}` | — | INVENTORIED |
| Simulatie | Stop | button | `POST /api/market-sim/runs/{id}/stop` | MUTATION | Error banner; `busy`; `disabled={!selectedId \|\| busy}` | — | INVENTORIED |
| Simulatie | Agents fleet | link | `to=/agents` | NAV | Always enabled | — | INVENTORIED |
| Simulatie | Marktdata | link | `to=/trading/marktdata` | NAV | Always enabled | — | INVENTORIED |
| Simulatie | Runs list item | button | Local `selectedId`; triggers poll `GET /api/market-sim/runs/{id}/live` | READ | Active class when selected | — | INVENTORIED |
| Simulatie | Console tab: messages | tab | Local `consoleTab` UI | READ | Active class | — | INVENTORIED |
| Simulatie | Console tab: fills | tab | Local `consoleTab` UI | READ | Active class | — | INVENTORIED |
| Simulatie | Console tab: wallets | tab | Local `consoleTab` UI | READ | Active class | — | INVENTORIED |
| Simulatie | Feature-flag banner | banner | Copy when `status.enabled` false | READONLY_EXPLAINED | UI copy: “Feature flag OFF — set LEVIATHAN_FEATURE_MARKET_SIM=true” | — | INVENTORIED |
| Simulatie | KPI row / equity chart / log lists | display | Render live/run data | DECORATIVE | Not clickable | — | INVENTORIED |

Auto-load (not user controls): `GET /api/market-sim/status`, `GET /api/market-sim/runs`, live poll every 1.5s.

---

## Strategieën (`StrategieenPage.tsx`)

| Page | Control | Type | Endpoint / capability | Side-effect class | Success/error/busy/disabled | Test | PASS |
|---|---|---|---|---|---|---|---|
| Strategieen | Strategy Library filter | input | Looks like name filter | READONLY_EXPLAINED | `readOnly value=""`; placeholder “Filter by name…” — no filtering | — | INVENTORIED |
| Strategieen | Strategy Library row | row click | Local `selected`; loads `GET /api/market-sim/strategies/{id}` | READ | Outline when selected; cursor pointer | — | INVENTORIED |
| Strategieen | Save Strategy | button | `POST /api/market-sim/strategies` | MUTATION | Toast success/error; `disabled={busy}` | — | INVENTORIED |
| Strategieen | Visual Builder | tab | Local `builderTab` | READ | Chip `is-active` | — | INVENTORIED |
| Strategieen | Code View | tab | Local `builderTab` | READ | Chip `is-active` | — | INVENTORIED |
| Strategieen | Parameters | tab | Local `builderTab` | READ | Chip `is-active` (default) | — | INVENTORIED |
| Strategieen | Visual Builder node graph | display | Illustrative pipeline nodes | READONLY_EXPLAINED | UI copy: “Visual graph is illustrative — execution uses the sandboxed DSL parameters below.” | — | INVENTORIED |
| Strategieen | Name | input | Local form state for create | READ | Editable | — | INVENTORIED |
| Strategieen | Description | input | Local form state for create | READ | Editable | — | INVENTORIED |
| Strategieen | Rule kind | select | Local `kind` (`ma_cross` / `mean_reversion`) | READ | Editable | — | INVENTORIED |
| Strategieen | Fast MA Period | range | Local `fastMa` (3–50) | READ | Editable | — | INVENTORIED |
| Strategieen | Slow MA Period | range | Local `slowMa` (10–200) | READ | Editable | — | INVENTORIED |
| Strategieen | KPI strip / Versions table | display | Counts / version list | DECORATIVE | Versions not clickable | — | INVENTORIED |

Auto-load: `GET /api/market-sim/strategies` on mount.

---

## Marktdata (`MarktdataPage.tsx`)

| Page | Control | Type | Endpoint / capability | Side-effect class | Success/error/busy/disabled | Test | PASS |
|---|---|---|---|---|---|---|---|
| Marktdata | Scan folder | button | `POST /api/market-sim/data/scan` | MUTATION | Toast; `disabled={busy}` | — | INVENTORIED |
| Marktdata | Validate & register | button | `POST /api/market-sim/data/register` body `{ path }` | MUTATION | Toast; `disabled={busy}` | — | INVENTORIED |
| Marktdata | Relative path | input | Local `path` for register | READ | Editable; placeholder “Relative path under markets root” | — | INVENTORIED |
| Marktdata | Filter symbol or path | input | Client-side filter of indexed sources | READ | Editable search | — | INVENTORIED |
| Marktdata | Health ticker strip | display | Status from `GET /api/market-sim/status` | DECORATIVE | Not clickable | — | INVENTORIED |
| Marktdata | Indexed sources table | display | Source metadata rows | DECORATIVE | No row actions | — | INVENTORIED |
| Marktdata | Validation errors list | display | Paths with `validation_error` | DECORATIVE | Not clickable | — | INVENTORIED |
| Marktdata | Providers & limits list | display | Capability claims | READONLY_EXPLAINED | UI: L2 “NOT CLAIMED” / “candles only”; Live broker “BLOCKED” / “TradingStub / live guard” | — | INVENTORIED |
| Marktdata | Feature-off error panel | banner | When flag off | READONLY_EXPLAINED | UI copy: “LEVIATHAN_FEATURE_MARKET_SIM is OFF” | — | INVENTORIED |

Auto-load: `GET /api/market-sim/status`; if enabled `GET /api/market-sim/data`.

---

## Paper Trading (`PaperTradingPage.tsx`)

| Page | Control | Type | Endpoint / capability | Side-effect class | Success/error/busy/disabled | Test | PASS |
|---|---|---|---|---|---|---|---|
| Paper | Symbol | input | Local state for create session | READ | Editable | — | INVENTORIED |
| Paper | Provider | select | Local `providerId` (`binance_public` / `csv_local` / `stooq_public`) | READ | Editable | — | INVENTORIED |
| Paper | Start paper session | button | `POST /api/market-sim/paper/sessions` | MUTATION | Error banner; `disabled={busy}` | — | INVENTORIED |
| Paper | Arm kill switch | button | `POST /api/market-sim/paper/sessions/{id}/kill-switch?armed=true` | MUTATION | `disabled={!session \|\| busy}` | — | INVENTORIED |
| Paper | Disarm | button | `POST …/kill-switch?armed=false` | MUTATION | `disabled={!session \|\| busy}` | — | INVENTORIED |
| Paper | Session list item | button | Local select session; refresh via `GET …/sessions/{id}` | READ | Always clickable when listed | — | INVENTORIED |
| Paper | Side | select | Local `BUY` / `SELL` for order | READ | Editable | — | INVENTORIED |
| Paper | Qty | input | Local qty for order | READ | Editable | — | INVENTORIED |
| Paper | Submit paper order | button | `POST /api/market-sim/paper/sessions/{id}/orders` | MUTATION | Error banner; `disabled={!session \|\| busy}`; refuses without quote (server) | — | INVENTORIED |
| Paper | Historical simulation | link | `to=/trading/simulatie` | NAV | Always enabled | — | INVENTORIED |
| Paper | Live trading (blocked) | link | `to=/trading/broker` | NAV | Always enabled (label implies blocked destination) | — | INVENTORIED |
| Paper | Agents | link | `to=/agents` | NAV | Always enabled | — | INVENTORIED |
| Paper | KPI grid / orders list / capabilities JSON | display | Session wallet + `GET /api/market-sim/capabilities` | DECORATIVE | Not clickable | — | INVENTORIED |
| Paper | Lede copy | display | Mode disclaimer | READONLY_EXPLAINED | UI: “Not real money. Live broker orders remain blocked.” | — | INVENTORIED |

Auto-poll every 4s: list sessions + capabilities (+ get session when selected).

---

## Portefeuille (`PortefeuillePage.tsx`)

| Page | Control | Type | Endpoint / capability | Side-effect class | Success/error/busy/disabled | Test | PASS |
|---|---|---|---|---|---|---|---|
| Portefeuille | Open simulation | link | `to=/trading/simulatie` | NAV | Always enabled | — | INVENTORIED |
| Portefeuille | Open paper trading | link | `to=/trading/paper` | NAV | Always enabled | — | INVENTORIED |
| Portefeuille | Broker status | link | `to=/trading/broker` | NAV | Always enabled | — | INVENTORIED |
| Portefeuille | Historical / paper / broker book lists | display | `GET /api/market-sim/runs`, `GET …/paper/sessions`, `GET …/live-trading` | DECORATIVE | No row actions | — | INVENTORIED |
| Portefeuille | Lede copy | display | Book separation disclaimer | READONLY_EXPLAINED | UI: “Live broker remains blocked. Figures below are from the control plane — not fabricated.” | — | INVENTORIED |

---

## Broker / Live (`BrokerTradingPage.tsx`)

| Page | Control | Type | Endpoint / capability | Side-effect class | Success/error/busy/disabled | Test | PASS |
|---|---|---|---|---|---|---|---|
| Broker | Live trading status panel | display | `GET /api/market-sim/live-trading` | READONLY_EXPLAINED | UI: live blocked; “Real broker credentials and order placement are intentionally unavailable… TradingStub refuses POST /api/trading/order.” | — | INVENTORIED |
| Broker | Paper trading | link | `to=/trading/paper` | NAV | Always enabled | — | INVENTORIED |
| Broker | Simulation | link | `to=/trading/simulatie` | NAV | Always enabled | — | INVENTORIED |

No place-order / enable-live controls on this page (by design for T0).

---

## Shared (`shared.tsx`)

| Page | Control | Type | Endpoint / capability | Side-effect class | Success/error/busy/disabled | Test | PASS |
|---|---|---|---|---|---|---|---|
| shared | `TradingHero` | display | Hero image / optional title overlay (`imageOnly` default true) | DECORATIVE | No handlers | — | INVENTORIED |
| shared | `Panel` | layout | Container; optional `action` slot (controls owned by pages) | DECORATIVE | Not actionable itself | — | INVENTORIED |
| shared | `Spark` / `CandleChart` / `LineSeries` / `AreaSpark` / `RingGauge` / `Donut` | display | SVG visuals; `aria-hidden` | DECORATIVE | No handlers; `MOCK_CANDLES` present but unused by live pages audited | — | INVENTORIED |

---

## Inventory summary

| Category | Rows |
|---|---|
| Missing v4 pages (NOT_PRESENT) | 5 |
| Navigation + routes | 14 |
| Shell chrome | 3 |
| Simulatie | 15 |
| Strategieen | 13 |
| Marktdata | 9 |
| Paper | 14 |
| Portefeuille | 5 |
| Broker | 3 |
| shared | 3 |
| **Total matrix rows** | **84** |

**G57:** `NOT_STARTED` — this file is T0 inventory only; no control marked PASS for the gate.
