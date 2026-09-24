# Trading Program State — Master Program v4

**Active phase:** T0 (complete — awaiting approval for T1A)  
**Branch:** `cursor/trading-program-t0-7fd3`  
**Program:** [`trading_program.md`](./trading_program.md)  
**Gap report:** [`trading_gap_report.md`](./trading_gap_report.md)  
**Gates manifest:** `Data/backend/tests/trading_gates.json`  
**Verifier:** `scripts/verify_trading_100.py`

Status values: `NOT_STARTED` | `IN_PROGRESS` | `PASS` | `FAIL` | `NOT_TESTED` | `NOT_TESTED_IN_CI`

Never mark `PASS` without evidence actually run.

---

## Gate table (G01–G60)

| Gate | Status | Evidence | Notes |
|---|---|---|---|
| G01 | NOT_STARTED | — | Streaming ingest / memory |
| G02 | NOT_STARTED | — | Timestamp parser |
| G03 | NOT_STARTED | — | Quality report |
| G04 | NOT_STARTED | — | Corporate actions |
| G05 | NOT_STARTED | — | Immutable datasets |
| G06 | NOT_STARTED | — | Split manifests |
| G07 | NOT_STARTED | — | Providers v2 |
| G08 | NOT_STARTED | — | Kernel golden |
| G09 | NOT_STARTED | — | Accounting invariants |
| G10 | NOT_STARTED | — | Instrument rules |
| G11 | NOT_STARTED | — | Determinism |
| G12 | NOT_STARTED | — | Causality |
| G13 | NOT_STARTED | — | Throughput / OOM |
| G14 | NOT_STARTED | — | Legacy parity |
| G15 | NOT_STARTED | — | Strategy Spec v2 |
| G16 | NOT_STARTED | — | Sandbox |
| G17 | NOT_STARTED | — | Strategy lineage |
| G18 | NOT_STARTED | — | Metrics v2 |
| G19 | NOT_STARTED | — | Trial Ledger |
| G20 | NOT_STARTED | — | WFA / CPCV / robustness |
| G21 | NOT_STARTED | — | Acceptance / sealed |
| G22 | NOT_STARTED | — | Strategy Library |
| G23 | NOT_STARTED | — | Brain as_of |
| G24 | NOT_STARTED | — | Role executors |
| G25 | NOT_STARTED | — | ResearchCampaign |
| G26 | NOT_STARTED | — | TradingGym |
| G27 | NOT_STARTED | — | Scorecards |
| G28 | NOT_STARTED | — | Readiness A0–A4 |
| G29 | NOT_STARTED | — | Trajectory export |
| G30 | NOT_STARTED | — | Sim-to-real gap |
| G31 | NOT_STARTED | — | Promotion SM |
| G32 | NOT_STARTED | — | PaperForwardRunner |
| G33 | NOT_STARTED | — | Reconciliation |
| G34 | NOT_STARTED | — | Risk Engine v2 |
| G35 | NOT_STARTED | — | Brokers |
| G36 | NOT_STARTED | — | Audit chain |
| G37 | NOT_STARTED | — | Gateway |
| G38 | NOT_STARTED | — | JobStore leases |
| G39 | NOT_STARTED | — | Persistence / migrations |
| G40 | NOT_STARTED | — | Settings / secrets |
| G41 | NOT_STARTED | — | Frontend real data |
| G42 | NOT_STARTED | — | Run config UI |
| G43 | NOT_STARTED | — | CI / verify / docs |
| G44 | NOT_STARTED | — | Completion report |
| G45 | NOT_STARTED | — | Characterization → regression |
| G46 | NOT_STARTED | — | FDR / power calibration |
| G47 | NOT_STARTED | — | Windows |
| G48 | NOT_STARTED | — | Security posture |
| G49 | NOT_STARTED | — | Observability |
| G50 | NOT_STARTED | — | Backup/restore |
| G51 | NOT_STARTED | — | Interactive priority |
| G52 | NOT_STARTED | — | Idempotency |
| G53 | NOT_STARTED | — | Provenance fingerprint |
| G54 | NOT_STARTED | — | DR temp-target |
| G55 | NOT_STARTED | — | Licensing provenance |
| G56 | NOT_STARTED | — | Time semantics |
| G57 | NOT_STARTED | — | Action matrix |
| G58 | NOT_STARTED | — | Operational telemetry |
| G59 | NOT_STARTED | — | Typed contracts |
| G60 | NOT_STARTED | — | Migration posture |

**Live integrations (never PASS offline):** live LLM trading calls, live market feed, live broker — track as `NOT_TESTED_IN_CI` when exercised outside CI.

---

## Defect register snapshot (T0)

See gap report for full evidence. Summary: **29 CONFIRMED, 2 PARTIAL (D19, D26), 0 REFUTED, 0 ALREADY_FIXED.**

---

## T0 deliverables checklist

| Artifact | Status |
|---|---|
| `Data/docs/trading_program.md` (v4) | DONE |
| `Data/docs/trading_program_state.md` | DONE |
| `Data/docs/trading_gap_report.md` | DONE |
| `Data/docs/trading_reference_hardware.json` | DONE (frozen) |
| `Data/docs/trading_performance_budget.json` | DONE (frozen) |
| `Data/docs/trading_frontend_action_matrix.md` | DONE (inventory; G57 NOT_STARTED) |
| `Data/backend/tests/trading_gates.json` | DONE (G01–G60) |
| `scripts/verify_trading_100.py` | DONE (skeleton; exits 1 until 100%) |
| Characterization D1–D31 | DONE (`74 passed / 31 xfailed`) |
| Ownership / worker / API maps | DONE (in gap report) |
| Migration head truth | **41** (`inference_efficiency`) |

---

## Session log (append-only)

### 2026-09-24 — T0 recon + characterization

- Read Master Program v4; overwrote `trading_program.md`.
- Re-verified D1–D31 against current source (head advanced to migration **41**).
- Extended `test_market_sim_characterization.py` for D22–D31; fixed D19/D21 drift.
- Command: `python3 -m pytest Data/backend/tests/test_market_sim_characterization.py -q`
- Result: **74 passed, 31 xfailed**.
- Froze reference hardware + performance budgets.
- Created gate manifest + verifier skeleton.
- Baseline suites: see entries below after runs.
- **No feature/fix code.** Stop for approval before T1A.

### Baseline suite results (fill after run)

| Command | Exit | Notes |
|---|---|---|
| `pytest …/test_market_sim_characterization.py -q` | 0 | 74 passed, 31 xfailed |
| `pytest …/test_market_sim.py …/test_trading_center.py -q` | 0 | 26 passed |
| `pytest …/test_migrations.py -q` | 1 | `test_applies_baseline_once` asserts head 32 vs real 41 (D21) |
| `python3 scripts/verify_trading_100.py` | 1 | 60× NOT_STARTED; anti-shortcut ok |
| Frontend `npm run typecheck` / `npm test` / `lint` / `build` | 0 | typecheck OK; 131 vitest passed; lint warnings only (pre-existing, non-trading); build OK |
