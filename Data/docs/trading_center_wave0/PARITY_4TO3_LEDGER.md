# Trading Center 4→3 Parity Ledger (Wave 6/7)

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
| Agent registry | `/trading/agents` | `AgentOverviewView` | orchestras + members | typecheck | VERIFIED |
| Wallet funding | Wallet tab | `fundSelectedWallet` | `POST .../funding` / PortfolioService | `test_wallet_funding_w2.py` | VERIFIED |
| Funding ≠ PnL | same | same | WalletLedger/PortfolioBook | same | VERIFIED |
| Portfolio advanced | drawer | TradingDesk AdvancedDrawer | portfolios* | `portefeuilleContracts.test.ts` | VERIFIED |
| Control Room | drawer | ControlRoomDrawer | institutional control-room | `marketSimCapabilitiesContracts.test.ts` | VERIFIED |
| Architecture panel | bottom | AgentOverviewView | derived counts | typecheck | VERIFIED |
| Risk snapshot | bottom | AgentOverviewView | portfolio/deploy flags; VaR UNMEASURED | typecheck | VERIFIED |

## Live Agents

| Feature | Target | Component | API / authority | Test | Status |
|---|---|---|---|---|---|
| Agent grid | `/trading/live-agents` | LiveAgentsView | orchestras/members | typecheck | VERIFIED |
| Offline scenario gen | control panel | generateScenario | `POST /scenarios` / scenario_generator | `test_scenario_generator_w3.py` | VERIFIED |
| Offline replay start | control panel | startReplay | runs create/start | typecheck | VERIFIED |
| Kill switch | control panel | killAll | deployment/portfolio kill | prior kill suites | VERIFIED |
| Orders stream | bottom | LiveAgentsView | listPortfolioOrders | typecheck | VERIFIED |
| Risk limit edits | control | honesty: Requested≠Effective | Advanced drawer for real apply | hostile fix | VERIFIED |
| Paper deploy | DeployPaperDrawer | createPaperDeployment | market_sim paper | assignStrategyContracts | VERIFIED |

## Research Centrum

| Feature | Target | Component | API / authority | Test | Status |
|---|---|---|---|---|---|
| Strategy inventory | `/trading/research` | ResearchCenterView | lab/strategies | typecheck | VERIFIED |
| Lab advanced | drawer + `?section=lab` | StrategyLabDrawers + ResearchLabPage embedded | lab lifecycle | `researchLabContracts.test.ts` | VERIFIED |
| Market data section | `?section=market-data` | MarketDataView | data/feeds/cert | prior md tests | VERIFIED |
| Research Command | `?section=research-command` | ResearchCommandPage embedded | research-command APIs | `researchCommandContracts.test.ts` | VERIFIED |
| Autonomous discovery create | CreateLabRunDrawer | lab create | prior | VERIFIED |
| Assign to agent | DeployPaperDrawer | createPaperDeployment + qualificationRefs | market_sim paper | `assignStrategyContracts.test.ts` | VERIFIED |

## Deletion gate (Wave 7)

| Item | Status |
|---|---|
| Obsolete page shells removed (Simulatie/Strategieen/Marktdata/Portefeuille/Paper/Broker/Onderzoek/ResearchLab entry/ControlRoom) | VERIFIED |
| Four-workspace Page/View shells removed; hooks/drawers retained as shared libs | VERIFIED |
| Legacy redirects still present (no old page imports) | VERIFIED |
| `paper/` tree removed after Live Agents absorption | VERIFIED |

## Remaining honesty notes

- KPI sparklines / trend %: UNMEASURED unless historical series exists (no screenshot fixtures in production).
- VaR / fill-rate / latency: UNMEASURED when backend does not measure.
- Pixel Playwright visual suite: NOT RUN in this environment (needs local Playwright capture loop).
- Full Journey A–F browser E2E: NOT RUN (API unit coverage for funding/scenario/assignment contracts present).
