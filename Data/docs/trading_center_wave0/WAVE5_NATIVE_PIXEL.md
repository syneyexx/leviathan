# Trading Center WAVE 5/6 — Native pixel rebuild

**Status:** Four workspaces are full native pages. Legacy Research Lab / Paper / Marktdata / etc. are **not** embedded.

## Pages

| Workspace | Implementation | Absorbs |
|---|---|---|
| Command Hub | `workspaces/commandHub/` | Research Command composition, Control Room drawer, oversight KPIs |
| Strategy Lab | `workspaces/strategyLab/` | Research Lab + Strategies + Simulation (+ explain/advanced drawer) |
| Trading Desk | `workspaces/tradingDesk/` | Paper + Portefeuille + Broker boundary + wallets + orchestra |
| Market Data | `workspaces/marketData/` | Marktdata library + feeds + cert + replay |

## Working actions (must remain green)

- Lab run create/start/pause/resume/cancel + candidate explain
- Strategy create/version; sim run create/start/pause/step/stop
- Portfolio lifecycle, orders, close, flatten, kill-switch, rebalance, export
- Paper deploy, shadow observe, promote A2–A4
- Market data scan/register, provider import, certify evaluate, replay start
- Research Command start (modal) from Command Hub
- Live trading always BLOCKED / PAPER ONLY

## Screenshots

Reference: `Data/docs/ui_reference/trading-center/`
