# LEGACY FEATURE PARITY MATRIX — Trading Center WAVE 0

Maps every supported operator feature on the **current 9 Trading Center routes** into the **4 new workspaces**.

Migration rule: **New ≥ Old + relevant production backend beyond UI**.

Status column (for migration tracking):

| Value | Meaning |
|---|---|
| `MAPPED` | Target workspace/surface decided (WAVE 0) |
| `PENDING` | Not yet implemented in new UI |
| `DONE` | Implemented + verified in new UI |
| `DROP_BOUNDARY` | Intentionally not a full page (e.g. broker becomes badge) |

---

## Route consolidation

| Legacy route | Legacy page | → Workspace | Notes |
|---|---|---|---|
| `/trading` | redirect → simulatie | → `/trading` → Command Hub | New default landing |
| `/trading/simulatie` | `SimulatiePage` | Strategy Lab | Historical run control; also linked from Market Data Replay |
| `/trading/strategieen` | `StrategieenPage` | Strategy Lab | Library + builder |
| `/trading/marktdata` | `MarktdataPage` | Market Data | Superset with feeds/cert/replay |
| `/trading/portefeuille` | `PortefeuillePage` | Trading Desk | Portfolio tab / panels |
| `/trading/paper` | `PaperTradingPage` | Trading Desk | Primary desk surface |
| `/trading/broker` | `BrokerTradingPage` | Trading Desk + Command Hub | **Boundary badge only** — no order UI |
| `/trading/onderzoek` | Research Command | Command Hub | Session composition PRIMARY |
| `/trading/lab` | Research Lab | Strategy Lab | Full lab tabs → progressive disclosure |
| `/trading/control-room` | Institutional Control Room | Command Hub | ADVANCED institutional drawer/section |

Agents page `TradeOrchestraSection` remains Agents-owned but Trading Desk embeds fleet controls via orchestra APIs.

---

## Feature rows

### A. Markt Simulatie (`/trading/simulatie`)

| Legacy feature | Type | → Workspace | → Surface | Status |
|---|---|---|---|---|
| Hero + status badges | View | Strategy Lab | PRIMARY | MAPPED |
| Equity chart + fill markers | View | Strategy Lab | PRIMARY | MAPPED |
| Paper portfolio KPIs on sim page | View | Strategy Lab (summary) + Trading Desk (detail) | SECONDARY | MAPPED |
| Source / strategy selects | Control | Strategy Lab | PRIMARY | MAPPED |
| Engine mode (strategy vs multi) | Control | Strategy Lab | PRIMARY | MAPPED |
| Capital / cadence / speed | Control | Strategy Lab | PRIMARY | MAPPED |
| Scan/seed · New run · Start/Pause/Step/Stop | Action | Strategy Lab | PRIMARY | MAPPED |
| Demo BTC | Action | Strategy Lab | ADVANCED | MAPPED |
| Agent roster | View | Strategy Lab + Trading Desk fleet | SECONDARY | MAPPED |
| Market-data list | View | Link → Market Data | SECONDARY | MAPPED |
| Runs list | View | Strategy Lab | PRIMARY | MAPPED |
| Observability tabs: activity / messages / fills / wallets / decisions | View | Strategy Lab ADVANCED + wallets → Trading Desk | ADVANCED | MAPPED |

### B. Strategieen (`/trading/strategieen`)

| Legacy feature | Type | → Workspace | → Surface | Status |
|---|---|---|---|---|
| Strategy library table | View | Strategy Lab | PRIMARY | MAPPED |
| Strategy builder (Visual / Code / Parameters) | Control | Strategy Lab | PRIMARY | MAPPED |
| Versions table | View | Strategy Lab | SECONDARY | MAPPED |
| KPI strip | View | Strategy Lab | PRIMARY | MAPPED |
| New strategy · Save version | Action | Strategy Lab | PRIMARY | MAPPED |
| Parameter presets (`ma_cross`, `mean_reversion`) | Control | Strategy Lab | PRIMARY | MAPPED |
| Fork / archive (API present) | Action | Strategy Lab | ADVANCED | MAPPED |

### C. Marktdata (`/trading/marktdata`)

| Legacy feature | Type | → Workspace | → Surface | Status |
|---|---|---|---|---|
| InstitutionalStrip | View | Market Data + shared context bar | PRIMARY | MAPPED |
| Health ticker | View | Market Data | PRIMARY | MAPPED |
| Indexed sources table | View | Market Data | PRIMARY | MAPPED |
| Validation errors | View | Market Data | SECONDARY | MAPPED |
| Providers & limits | View | Market Data | SECONDARY | MAPPED |
| Scan · Register path | Action | Market Data | PRIMARY | MAPPED |
| Search/filter sources | Control | Market Data | PRIMARY | MAPPED |
| READY/INVALID + quality verdicts | View | Market Data | PRIMARY | MAPPED |

### D. Portefeuille (`/trading/portefeuille`)

| Legacy feature | Type | → Workspace | → Surface | Status |
|---|---|---|---|---|
| Portfolio select · Create | Control | Trading Desk | PRIMARY | MAPPED |
| Start / Pause / Resume / Stop | Action | Trading Desk | PRIMARY | MAPPED |
| Create portfolio modal | Action | Trading Desk | PRIMARY | MAPPED |
| Analysis modal | View | Trading Desk | ADVANCED | MAPPED |
| Equity chart (range tabs) | View | Trading Desk | PRIMARY | MAPPED |
| Allocation (Asset/Sector/Geography) | View | Trading Desk | SECONDARY | MAPPED |
| Open positions + search/filter | View | Trading Desk | PRIMARY | MAPPED |
| Close selected / Close | Action | Trading Desk | PRIMARY | MAPPED |
| Risk & Health | View | Trading Desk | PRIMARY | MAPPED |
| AI insights | View | Trading Desk | SECONDARY | MAPPED |
| Rebalancing recommendations | View/Action | Trading Desk | ADVANCED | MAPPED |
| Execute recommendation / all | Action | Trading Desk | ADVANCED | MAPPED |
| Export CSV | Action | Trading Desk | ADVANCED | MAPPED |
| Save allocation | Action | Trading Desk | SECONDARY | MAPPED |

### E. PAPER Trading (`/trading/paper`)

| Legacy feature | Type | → Workspace | → Surface | Status |
|---|---|---|---|---|
| Hero | View | Trading Desk | PRIMARY | MAPPED |
| Symbol tabs · add symbol · timeframes | Control | Trading Desk | PRIMARY | MAPPED |
| Indicators menu · draw tools · save layout | Control | Trading Desk | SECONDARY | MAPPED |
| Chart | View | Trading Desk | PRIMARY | MAPPED |
| Orchestrator modes (autonomous/assisted/manual) | Control | Trading Desk | PRIMARY | MAPPED |
| Capital / sizing / risk fields | Control | Trading Desk | PRIMARY | MAPPED |
| Deploy · Pause · Flatten | Action | Trading Desk | PRIMARY | MAPPED |
| Fleet table start/pause | Action | Trading Desk | ADVANCED | MAPPED |
| Positions · Orders · Activity | View | Trading Desk | PRIMARY | MAPPED |
| Close position | Action | Trading Desk | PRIMARY | MAPPED |
| Analytics range tabs | View | Trading Desk | SECONDARY | MAPPED |
| Risk allocation | View | Trading Desk | PRIMARY | MAPPED |

### F. BROKER Trading (`/trading/broker`)

| Legacy feature | Type | → Workspace | → Surface | Status |
|---|---|---|---|---|
| Live status `LIVE_TRADING_AVAILABLE=BLOCKED` | View | Command Hub + Trading Desk | PRIMARY badge | MAPPED / DROP_BOUNDARY |
| Guard flags | View | Command Hub | ADVANCED | MAPPED |
| Links to paper/simulatie | Nav | Trading Desk / Strategy Lab | PRIMARY | MAPPED |
| Order placement | — | — | — | **Never** (BLOCKED) |

### G. Research Command / Onderzoek (`/trading/onderzoek`)

| Legacy feature | Type | → Workspace | → Surface | Status |
|---|---|---|---|---|
| Active research session card | View | Command Hub | PRIMARY | MAPPED |
| Standard agent team | View | Command Hub + Trading Desk fleet | SECONDARY | MAPPED |
| Wallet & portfolio card | View | Command Hub summary → Desk detail | SECONDARY | MAPPED |
| What they're watching | View | Command Hub | PRIMARY | MAPPED |
| Live thinking stream | View | Command Hub | SECONDARY | MAPPED |
| Thesis & Why | View | Command Hub | SECONDARY | MAPPED |
| Positioning & Intent | View | Command Hub | SECONDARY | MAPPED |
| Open/closed positions & PnL | View | Command Hub summary → Desk | SECONDARY | MAPPED |
| Strategy evolution | View/Action | Command Hub → Strategy Lab | SECONDARY | MAPPED |
| Execution guardrails | View | Command Hub | PRIMARY | MAPPED |
| Orchestra / portfolio / lab / mission selects | Control | Command Hub | PRIMARY | MAPPED |
| Launch · Create orchestra | Action | Command Hub | PRIMARY | MAPPED |
| Watch tabs + manage feeds | Control | Command Hub + Market Data | SECONDARY | MAPPED |
| Start / Pause / Flatten PAPER / Kill switch | Action | Command Hub | PRIMARY | MAPPED |
| Review Evidence drawer | View | Command Hub | ADVANCED | MAPPED |
| Open Paper Mode link | Nav | Trading Desk | PRIMARY | MAPPED |

### H. Research Lab (`/trading/lab`)

| Legacy feature | Type | → Workspace | → Surface | Status |
|---|---|---|---|---|
| Run rail + create run | Control | Strategy Lab | PRIMARY | MAPPED |
| Lifecycle Start/Pause/Resume/Cancel | Action | Strategy Lab | PRIMARY | MAPPED |
| Overview tab | View | Strategy Lab | PRIMARY | MAPPED |
| Hypotheses / Perception / Generations / Population / Lineage / Lessons | View | Strategy Lab | ADVANCED | MAPPED |
| Validation tab | View | Strategy Lab | PRIMARY | MAPPED |
| Paper tab | View | Strategy Lab → Desk | SECONDARY | MAPPED |
| Analytics / Logs | View | Strategy Lab | ADVANCED | MAPPED |
| Create modal (objective, data, autonomy, budgets, feed-health) | Action | Strategy Lab | PRIMARY | MAPPED |
| Edit metadata / Clone / Export (disabled stubs) | — | — | — | **Do not present as working** |

### I. Institutional Control Room (`/trading/control-room`)

| Legacy feature | Type | → Workspace | → Surface | Status |
|---|---|---|---|---|
| Live Trading Guard | View | Command Hub | PRIMARY | MAPPED |
| Capability Gap Matrix | View | Command Hub | ADVANCED | MAPPED |
| Multi-Asset Readiness | View | Command Hub | ADVANCED | MAPPED |
| Data Plane Certification | View | Command Hub → Market Data | SECONDARY | MAPPED |
| Qualification pipeline / state / experiments | View | Command Hub + Strategy Lab | SECONDARY / ADVANCED | MAPPED |
| Research KPIs | View | Command Hub | PRIMARY | MAPPED |
| Reconciliation breaks · Exceptions · Audit | View | Command Hub | ADVANCED | MAPPED |
| Operator Attention · Timeline | View | Command Hub | PRIMARY / SECONDARY | MAPPED |
| API & Event Fabric | View | Command Hub | ADVANCED | MAPPED |
| Refresh | Action | Command Hub | PRIMARY | MAPPED |
| Link to Research Lab | Nav | Strategy Lab | PRIMARY | MAPPED |
| View Pipeline / Add Note (disabled) | — | — | — | **Do not present as working** until API exists |

---

## Shared chrome (all legacy pages)

| Feature | → New |
|---|---|
| Trading nav group (9 items) | Collapse to 4 workspace items under Trading Center |
| Wide `lv-app--trading` shell | Preserve |
| Theme / refresh / clock patterns | Shared Trading Center header |
| Capability-truth badges | Shared **Trading Context Bar** (Mode / Market / TF / Dataset / Regime / PAPER ONLY) |

---

## Parity gate summary

| Metric | WAVE 0 | WAVE 1 |
|---|---|---|
| Legacy routes inventoried | 9/9 | 9/9 |
| Features mapped to a workspace | 100% of supported features | Embedded via workspace surfaces |
| Features intentionally dropped | Only disabled stubs + live order placement | unchanged |
| Features needing **new** UI beyond legacy | See `BEYOND_LEGACY_UI.md` | Still pending densify (WAVE 2+) |
| Migrated implementation (`DONE`) | 0% (WAVE 0 docs only) | Scaffold: 4 routes + redirects + embedded legacy = reachable |
