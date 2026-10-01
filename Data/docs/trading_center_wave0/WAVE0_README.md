# Trading Center WAVE 0 — Capability Discovery

**Status:** WAVE 0 discovery complete; **4→3 consolidation in progress** (see [`WAVE0_4TO3_MIGRATION_MAP.md`](./WAVE0_4TO3_MIGRATION_MAP.md)).  
**Date:** 2026-09-30 (four-workspace freeze); 2026-10-01 (three-page target)  
**Branch intent:** Inventarise backend + legacy UI before consolidating into **exactly three** primary pages (Agent Overzicht, Live Agents, Research Centrum).

## Goal

The new Trading Center is a **functional SUPERSET** of:

1. All supported legacy Trading Center UI capabilities, **and**
2. The four native workspaces (Command Hub / Strategy Lab / Trading Desk / Market Data), **and**
3. Production-capable MarketSim/Trading backend capabilities that previously had weak or no UI.

Screenshots define **layout / density / design language** (`Data/docs/ui_reference/trading-center-3page/`).  
The repository defines **functional scope**.

## Three-page architecture (absolute — current target)

| Page | Route | Operator job |
|---|---|---|
| **Agent Overzicht** | `/trading/agents` | Inventory, wallets/funding, portfolios, sessions, risk, orchestra, control room |
| **Live Agents** | `/trading/live-agents` | Realtime/offline paper execution console |
| **Research Centrum** | `/trading/research` | Discovery, lab, qualification, datasets |

No fourth primary Trading Center page.

## Artifacts in this folder

| File | Purpose |
|---|---|
| [`WAVE0_4TO3_MIGRATION_MAP.md`](./WAVE0_4TO3_MIGRATION_MAP.md) | **Current** 4→3 ownership / deletion / gap map |
| [`BACKEND_CAPABILITY_MATRIX.md`](./BACKEND_CAPABILITY_MATRIX.md) | Per-capability inventory |
| [`backend_capability_matrix.json`](./backend_capability_matrix.json) | Machine-readable matrix |
| [`LEGACY_FEATURE_PARITY_MATRIX.md`](./LEGACY_FEATURE_PARITY_MATRIX.md) | Old UI feature mapping (retarget to 3 pages during migration) |
| [`PROGRESSIVE_DISCLOSURE.md`](./PROGRESSIVE_DISCLOSURE.md) | PRIMARY / SECONDARY / ADVANCED plan |
| [`BEYOND_LEGACY_UI.md`](./BEYOND_LEGACY_UI.md) | Backend beyond legacy UI |

## Live-money invariant

`LIVE_TRADING_AVAILABLE = BLOCKED` always. Broker UI is a **boundary surface**, never an enablement path. All new pages must preserve this truth.
