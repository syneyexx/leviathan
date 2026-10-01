# Trading Center 4→3 Migration Map (WAVE 0)

**BASE_MAIN_SHA:** `29188b186c5c3c5760718a0bee5a452bf4ee6a1b`  
**Date:** 2026-10-01  
**Scope:** Consolidate four native Trading Center workspaces into exactly three primary pages.

Screenshots (visual SoT): `Data/docs/ui_reference/trading-center-3page/`  
Backend SoT: MarketSim / TradingOrchestra / ResearchCommand / Portfolio / RiskGuard / existing MARKET DB.

Excluded trees: `Data/HADES/**`, `HADES/**`, `editor/**`, `EDITOR/**` — not inspected.

---

## A. Current four-workspace capability map

| Workspace | Implementation | Absorbed legacy | Operator job |
|---|---|---|---|
| Command Hub | `workspaces/commandHub/` | onderzoek, control-room | Oversight, RC composition, institutional attention |
| Strategy Lab | `workspaces/strategyLab/` | lab, strategieen, simulatie | Discovery → validation → qualification |
| Trading Desk | `workspaces/tradingDesk/` | paper, portefeuille, broker boundary | Paper execution, wallets, portfolios, risk |
| Market Data | `workspaces/marketData/` | marktdata | Datasets, feeds, cert, seal, replay |

Shared: `TradingContextBar`, `tradingStatusRows`, `useTradingContext`, V2 AppShell, `styles/trading-*.css`.

---

## B. Legacy parity → 3-page targets

| Legacy route | Previous 4-ws target | **New 3-page target** |
|---|---|---|
| `/trading/onderzoek` | Command Hub | Research Centrum `?section=research-command` (+ Agent Overzicht control-room drawer for institutional) |
| `/trading/control-room` | Command Hub | Agent Overzicht `?drawer=control-room` |
| `/trading/lab` | Strategy Lab | Research Centrum `?section=lab` |
| `/trading/strategieen` | Strategy Lab | Research Centrum `?section=strategies` |
| `/trading/simulatie` | Strategy Lab | Research Centrum `?section=backtest` (+ Live Agents offline replay) |
| `/trading/paper` | Trading Desk | Live Agents |
| `/trading/portefeuille` | Trading Desk | Agent Overzicht `?section=portfolio` |
| `/trading/broker` | Trading Desk | Live Agents `?section=broker-boundary` |
| `/trading/marktdata` | Market Data | Research Centrum `?section=market-data` |

---

## C. Four → three capability ownership

### Agent Overzicht (`/trading/agents`) — PAGE 1
From Command Hub: fleet summary, decisions, control room, live guard, institutional attention, architecture.  
From Trading Desk: wallets, capital allocation, portfolio history/config, past sessions, risk snapshot, orchestra structure.  
New/finish: agent registry primary, selected agent detail (Overzicht/Wallet/Sessies/Architectuur), **paper wallet funding mutation**.

### Live Agents (`/trading/live-agents`) — PAGE 2
From Trading Desk: paper deployment, positions/orders/fills, execution controls, broker health, shadow/autonomous/drift/calibration, kill switch.  
From Market Data: realtime feed selection, feed health, market snapshot, freshness/latency.  
From Strategy Lab/Simulatie: offline replay operator controls.  
New/finish: AI-generated scenario pipeline (MarketSim, if missing), LIVE DATA vs PAPER EXECUTION labeling.

### Research Centrum (`/trading/research`) — PAGE 3
From Strategy Lab: ALL lab/strategies/builder/qual/candidates/hypotheses/lineage/lessons/experiments/cost pack/WFA.  
From Market Data: historical datasets, import, provenance, certification, seal, PIT, quality, universe.  
From Command Hub: Research Command session composition, thesis/evidence.  
Shared feeds: research/sandbox feed config (same backend as Live Agents).

---

## D. Backend beyond-UI (must remain reachable)

| Capability | Target page | Surface | Notes |
|---|---|---|---|
| Candidate explainability | Research | ADVANCED | Already wired Wave 2 prior |
| Agent wallets + **funding** | Agent Overzicht | PRIMARY | Funding mutation = **GAP** to close in Wave 2 |
| Paper deployment lifecycle | Live Agents | PRIMARY + ADVANCED | |
| Qualification CRUD | Research | PRIMARY | |
| WFA fold inspector | Research | ADVANCED | |
| Dataset seal | Research | ADVANCED | |
| Feed runtime management | Live + Research | PRIMARY / ADVANCED | One authority |
| Strategy families | Research | SECONDARY | |
| Trading action matrix | Agent Overzicht | ADVANCED (control room) | |
| PIT / epistemic firewall | Research | ADVANCED | |
| Cross-session decisions | Agent Overzicht | SECONDARY | |
| Cost pack | Research | ADVANCED | |
| Gym episodes | Research | ADVANCED (assess) | |
| AI scenario generator | Live Agents | SECONDARY | **GAP** if none exists |

---

## E. Backend gaps required by screenshots

1. **Operator paper wallet funding** (create/assign/top-up/reduce/transfer) via WalletLedger + MARKET persistence + API — funding ≠ PnL.  
2. **AI-generated offline scenario** MarketSim capability (structured spec → deterministic bars) if absent.  
3. Sidebar status semantics: Trading Engine / Paper Broker / Market Data / Risk Engine / Strategy Store / Active Agents (measured).

---

## F. File deletion candidates (AFTER parity gate Wave 6/7)

**Four-workspace page impls** (move reusable pieces first):
- `workspaces/commandHub/**`
- `workspaces/strategyLab/**`
- `workspaces/tradingDesk/**`
- `workspaces/marketData/**`
- Thin re-exports: `CommandHubPage.tsx`, `StrategyLabWorkspacePage.tsx`, `TradingDeskPage.tsx`, `MarketDataWorkspacePage.tsx`

**Legacy page modules** (already redirected; delete after no imports):
- `SimulatiePage.tsx`, `StrategieenPage.tsx`, `MarktdataPage.tsx`, `PortefeuillePage.tsx`
- `PaperTradingPage.tsx`, `BrokerTradingPage.tsx`, `OnderzoekPage.tsx`, `ResearchLabPage.tsx`
- `InstitutionalControlRoomPage.tsx`, `paper/**`, `researchLab/**`, `researchCommand/**`, `controlRoom/**` (after extraction)

**CSS:** migrate useful rules into shared trading V2 namespaces; remove orphaned page CSS after import proof.

Do **not** delete backend MarketSim / orchestra / lab / portfolio code.

---

## G. Routes / deep links

| Route | Role |
|---|---|
| `/trading` | → `/trading/agents` |
| `/trading/agents` | Agent Overzicht (canonical) |
| `/trading/live-agents` | Live Agents |
| `/trading/research` | Research Centrum |
| `/trading/command-hub` | redirect → `/trading/agents` |
| `/trading/trading-desk` | redirect → `/trading/live-agents` |
| `/trading/strategy-lab` | redirect → `/trading/research` |
| `/trading/market-data` | redirect → `/trading/research?section=market-data` |
| Legacy 9 routes | redirect per section B |

Deep-link examples: `?agent=`, `?tab=wallet`, `?mode=realtime`, `?strategy=`, `?section=`, `?drawer=control-room`.

---

## H. Wave gate

WAVE 0 ACCEPTANCE:
- [x] Every current capability has owner page
- [x] Every current capability has target page
- [x] Deletion candidates enumerated
- [x] HADES/editor not read
- [x] Backend gaps listed

Next: WAVE 1 — contracts / three-page IA.
