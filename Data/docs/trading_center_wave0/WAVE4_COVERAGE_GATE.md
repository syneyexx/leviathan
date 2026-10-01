# Trading Center WAVE 4 — Coverage gate (pre-deletion)

**Depends on:** WAVE 0–3  
**Purpose:** Freeze honest status before any legacy Trading Center page **module** deletion.

Legacy **routes** already redirect (WAVE 1). Legacy **modules** remain as embedded surfaces — deletion is only safe when the gate below is green.

## Gate checklist (4F)

| Requirement | Status | Evidence |
|---|---|---|
| 100% relevant old UI functions migrated / reachable | **PARTIAL → REACHABLE** | WAVE 1 redirects + embedded surfaces; densify incomplete vs screenshots |
| All production-capable trading backend functions assessed | **DONE** | WAVE 0 `BACKEND_CAPABILITY_MATRIX` |
| Operator-relevant COMPLETE capabilities reachable | **MOSTLY** | Explain, wallets, shadow/promote wired (W2–W3); remaining: see open items |
| Relevant PARTIAL finished or reported as blockers | **REPORTED** | See open PARTIAL blockers |
| STUB/UNAVAILABLE not shown as operational | **PASS** | Live BLOCKED badge; HMM/regime UNMEASURED; no fake Bullish/High |
| No fifth workspace | **PASS** | Nav has exactly 4 |
| No backend capability lost by consolidation | **PASS (reachable)** | All 9 legacy surfaces embedded or redirected |

## Open COMPLETE items still thin in UI

| Capability | Workspace | Note |
|---|---|---|
| Qualification run write CRUD | Strategy Lab / Command Hub | Client exists; Control Room projects; dedicated create/cancel UI still thin |
| Dataset seal dialog | Market Data ADVANCED | Documented; write dialog not yet operator-confirmed |
| WFA fold inspector | Strategy Lab ADVANCED | Gate evidence only |
| PIT fabric evidence panel | Market Data ADVANCED | Bound into paths; no dedicated panel |
| Execution calibration viewer | Trading Desk ADVANCED | Client method present |
| Institutional authority approve | Command Hub ADVANCED | API only |

## Open PARTIAL blockers (do not fake COMPLETE)

- Q05 statistical multiplicity (needs performance matrix)
- Q07 adversarial (no standalone API)
- Q09 capacity defaults UNMEASURED
- Q11 portfolio compatibility often UNMEASURED
- Institutional recon/exceptions/audit gaps
- Futures/FX paper UNAVAILABLE; options/FI UNAVAILABLE
- Drift review UI needs measured metrics payload

## Deletion policy

Do **not** delete `SimulatiePage`, `StrategieenPage`, `MarktdataPage`, `PortefeuillePage`, `paper/*`, `researchLab/*`, `researchCommand/*`, `InstitutionalControlRoomPage`, `BrokerTradingPage` until:

1. PRIMARY chrome for each workspace matches screenshot density **or** product accepts embedded legacy as permanent advanced
2. Open COMPLETE thin items above are either wired or explicitly deferred with owners
3. E2E smoke covers all four workspaces + legacy redirects

## Wave stack

| Wave | PR | Role |
|---|---|---|
| 0 | #261 | Discovery matrices |
| 1 | #262 | Four-workspace scaffold |
| 2 | #263 | Command Hub + wallets + explain |
| 3 | #264 | Lab/Market Data chrome + paper advanced |
| 4 | this | Coverage gate freeze |
