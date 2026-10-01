# Trading Center WAVE 1 — Workspace scaffold

**Depends on:** WAVE 0 matrices (`Data/docs/trading_center_wave0/`)  
**Status:** Implementation

## Goal

Scaffold the **four absolute Trading Center workspaces** with shared chrome, without deleting legacy capability.

```
New nav (4) + shared Trading Context Bar
  +
Legacy surfaces embedded via PRIMARY / SECONDARY / ADVANCED tabs
  =
Functional supersets of the old 9-route UI
```

## Deliverables

1. Routes
   - `/trading/command-hub`
   - `/trading/strategy-lab`
   - `/trading/trading-desk`
   - `/trading/market-data`
   - `/trading` → Command Hub
2. Nav: Trading Center submenu = exactly those 4 items
3. Shared `TradingContextBar` (mode / market / TF / dataset / regime / PAPER ONLY)
4. Shared `TradingWorkspaceShell` (header, context bar, surface tabs, status strip)
5. Legacy routes **redirect** into the correct workspace + surface (no capability loss)
6. Legacy page components accept `embedded` to render without a second AppShell

## Non-goals (later waves)

- Pixel-exact screenshot rebuild of every panel
- Deleting legacy page modules
- Finishing all PARTIAL backend capabilities
- Beyond-legacy advanced drawers that need new API wiring (WAVE 2+)

## Surface map (query `?surface=`)

| Workspace | Surfaces |
|---|---|
| Command Hub | `overview` (default), `research-command`, `control-room` |
| Strategy Lab | `lab` (default), `strategies`, `simulation` |
| Trading Desk | `paper` (default), `portfolio`, `broker` |
| Market Data | `library` (default) |

## Next wave

WAVE 2 — densify PRIMARY chrome to match screenshot hierarchy while keeping embedded legacy as fallback/advanced.
