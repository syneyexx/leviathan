# Trading Center WAVE 0 — Capability Discovery

**Status:** WAVE 0 discovery complete (matrices frozen for migration planning)  
**Date:** 2026-09-30  
**Branch intent:** Inventarise backend + legacy UI before consolidating into **exactly four** workspaces.

## Goal

The new Trading Center is a **functional SUPERSET** of:

1. All supported legacy Trading Center UI capabilities (9 routes), **and**
2. Production-capable MarketSim/Trading backend capabilities that previously had weak or no UI.

Screenshots define **layout / density / design language**.  
The repository defines **functional scope**.

## Four-workspace architecture (absolute)

| Workspace | Operator job | Absorbs legacy routes |
|---|---|---|
| **Command Hub** | Cross-system oversight, session composition, qualification/promotion attention, institutional truth | `/trading/onderzoek`, `/trading/control-room`, overview pieces of simulatie/paper |
| **Strategy Lab** | Discovery → validation → qualification ladder | `/trading/lab`, `/trading/strategieen`, `/trading/simulatie` |
| **Trading Desk** | Paper execution, portfolios, wallets, risk, fleet | `/trading/paper`, `/trading/portefeuille`, `/trading/broker` (boundary only) |
| **Market Data** | Offline datasets, live feeds, certification, quality, replay sampling | `/trading/marktdata` (+ feed/replay APIs) |

No fifth Trading Center page.

## Artifacts in this folder

| File | Purpose |
|---|---|
| [`BACKEND_CAPABILITY_MATRIX.md`](./BACKEND_CAPABILITY_MATRIX.md) | Per-capability inventory (authority → API → status → workspace) |
| [`backend_capability_matrix.json`](./backend_capability_matrix.json) | Machine-readable matrix for coverage gates |
| [`LEGACY_FEATURE_PARITY_MATRIX.md`](./LEGACY_FEATURE_PARITY_MATRIX.md) | Old UI feature → new workspace/surface mapping |
| [`PROGRESSIVE_DISCLOSURE.md`](./PROGRESSIVE_DISCLOSURE.md) | PRIMARY / SECONDARY / ADVANCED surface plan |
| [`BEYOND_LEGACY_UI.md`](./BEYOND_LEGACY_UI.md) | Backend capabilities discovered beyond legacy UI |

## Classification rules (4C)

A capability is only **COMPLETE** when this chain traces:

```
UI/action → API contract → canonical authority → execution path → durable state/result → error semantics
```

| Class | Meaning |
|---|---|
| **COMPLETE** | Full chain; safe to expose as operational |
| **PARTIAL** | Real authority + API, but evidence/UI/family gaps remain; expose honestly or finish in-migration |
| **STUB** | Boundary/refuse-only code — do **not** present as working |
| **BLOCKED** | Explicitly prevented (e.g. live money) — show as blocked truth |
| **UNAVAILABLE** | NOT_IMPLEMENTED / FEATURE_GATED with no production path |

**Non-capabilities:** test fixtures, TODOs, dead code, manifest-only declarations, `AVAILABLE` without READY execution.

## Coverage gate (4F) — pre-deletion checklist

- [ ] 100% of relevant legacy UI functions migrated (see LEGACY matrix `Migrated` column)
- [ ] All production-capable trading backend functions assessed (BACKEND matrix)
- [ ] All operator-relevant COMPLETE capabilities reachable in one of the 4 workspaces
- [ ] Relevant PARTIAL capabilities finished **or** reported as concrete blockers
- [ ] STUB/UNAVAILABLE not shown as operational
- [ ] No hidden fifth workspace
- [ ] No backend capability lost by consolidation

## Canonical code anchors

| Concern | Path |
|---|---|
| Control plane | `Data/modules/market_sim/service.py` (`MarketSimControlPlane`) |
| Capabilities | `Data/modules/market_sim/capabilities.py` |
| Action matrix | `Data/modules/market_sim/trading_action_matrix.py` |
| Institutional gaps | `Data/modules/market_sim/institutional_core/gap_ledger.py` |
| HTTP | `Data/backend/routes/market_sim.py`, `trading_orchestra.py`, `research_command.py` |
| Legacy UI | `Data/frontend/src/pages/trading/` (9 routes) |
| Workers | `Data/modules/workers/entrypoints/market_sim.py` |

## Live-money invariant

`LIVE_TRADING_AVAILABLE = BLOCKED` always. Broker UI is a **boundary surface**, never an enablement path. All new workspaces must preserve this truth.
