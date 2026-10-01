# Trading Center 4→3 Parity Ledger (Wave 6 working copy)

Status values: `NOT_STARTED` | `IN_PROGRESS` | `VERIFIED`

Do **not** mark VERIFIED from rendering alone — requires page + component + API + authority + test evidence.

## Navigation / IA

| Feature | Target | Component | API / authority | Test | Status |
|---|---|---|---|---|---|
| Exactly 3 menu items | MAIN_MENU | `menu.ts` | n/a | `menu.test.ts` | VERIFIED |
| `/trading` → agents | App routes | `App.tsx` | n/a | workspaceConfig/redirect tests | VERIFIED |
| Former 4-ws redirects | TradingLegacyRedirect | `workspaceConfig.ts` | n/a | `TradingLegacyRedirect.test.ts` | VERIFIED |
| Legacy 9 redirects | same | same | n/a | same | VERIFIED |

## Agent Overzicht

| Feature | Target | Component | API / authority | Test | Status |
|---|---|---|---|---|---|
| Agent registry | `/trading/agents` | `AgentOverviewView` | orchestras + members | typecheck | IN_PROGRESS |
| Wallet funding | Wallet tab | `fundSelectedWallet` | `POST .../funding` / PortfolioService | `test_wallet_funding_w2.py` | VERIFIED |
| Funding ≠ PnL | same | same | WalletLedger/PortfolioBook | same | VERIFIED |
| Portfolio advanced | drawer | TradingDesk AdvancedDrawer | portfolios* | prior desk tests | IN_PROGRESS |
| Control Room | drawer | ControlRoomDrawer | institutional control-room | prior | IN_PROGRESS |
| Architecture panel | bottom | AgentOverviewView | derived counts | — | IN_PROGRESS |
| Risk snapshot | bottom | AgentOverviewView | portfolio/deploy flags; VaR UNMEASURED | — | IN_PROGRESS |

## Live Agents

| Feature | Target | Component | API / authority | Test | Status |
|---|---|---|---|---|---|
| Agent grid | `/trading/live-agents` | LiveAgentsView | orchestras/members | typecheck | IN_PROGRESS |
| Offline scenario gen | control panel | generateScenario | `POST /scenarios` / scenario_generator | `test_scenario_generator_w3.py` | VERIFIED |
| Offline replay start | control panel | startReplay | runs create/start | typecheck | IN_PROGRESS |
| Kill switch | control panel | killAll | deployment/portfolio kill | prior kill suites | IN_PROGRESS |
| Orders stream | bottom | LiveAgentsView | listPortfolioOrders | — | IN_PROGRESS |
| Risk limit edits | control | honesty: Requested≠Effective | Advanced drawer for real apply | hostile fix | IN_PROGRESS |

## Research Centrum

| Feature | Target | Component | API / authority | Test | Status |
|---|---|---|---|---|---|
| Strategy inventory | `/trading/research` | ResearchCenterView | lab/strategies | typecheck | IN_PROGRESS |
| Lab advanced | drawer | StrategyLabDrawers | lab lifecycle | prior lab tests | IN_PROGRESS |
| Market data section | `?section=market-data` | MarketDataView | data/feeds/cert | prior md tests | IN_PROGRESS |
| Autonomous discovery create | CreateLabRunDrawer | lab create | prior | IN_PROGRESS |
| Assign to agent | link/CTA | needs real assignment path | orchestra/deploy | NOT_STARTED |

## Deletion gate

Old four-workspace **routes** removed from primary nav (VERIFIED).  
Old four-workspace **implementations** still present as shared libraries for drawers/hooks — delete only after VERIFIED extraction (Wave 7 NOT_STARTED).
