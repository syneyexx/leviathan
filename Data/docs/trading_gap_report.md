# LEVIATHAN Trading Gap Report — Phase T0 (Master Program v4)

**Date:** 2026-09-24  
**Branch:** `cursor/trading-program-t0-7fd3`  
**Scope:** Recon + characterization only. **No feature/fix code.**  
**Program:** [`trading_program.md`](./trading_program.md) (v4)  
**Operator note:** Market data is operator-supplied; this phase does not ingest or commit bulk OHLCV.

---

## Verdict

Defects **D1–D31** re-verified against current `origin/main` (commit `4758738`).  
**29 CONFIRMED · 2 PARTIAL (D19, D26) · 0 REFUTED · 0 ALREADY_FIXED.**

The Market Simulation module remains a capable research prototype (multi-engine, Decimal wallets, commit-reveal, paper brokers, experiments, capability matrix, live guard, reserved `market_sim.advance` job), but **correctness defects D1–D8/D10 must be fixed before new research features are trusted**. Statistical/architecture gaps D11–D31 remain as documented. Migration head drift (**D21**) worsened: real head is **41**, not 34.

**Characterization suite:** `Data/backend/tests/test_market_sim_characterization.py`  
**Result (this run):** `74` passed (current-behaviour evidence) + `31` expectedFailure (desired contracts for later phases).

**Stop for approval** before Phase T1A.

---

## Real migration head (D21)

| Source | Head |
|---|---|
| `Data/backend/migrations.py` `MIGRATIONS[-1]` | **41** (`inference_efficiency`) |
| Contiguous versions | `1 … 41` |
| Trading schema | **v16** (`market_sim`) + **v34** (`trading_center`) |
| `test_migrations.py` expectation | **32** (stale — **FAILS** today) |
| Prior gap report claim | 34 (now stale) |

Next free contiguous migration number: **42**.  
Extend v16/v34 tables; do not invent a second DB. Phase-owned schema only (Part C.4).

---

## Defect register

| ID | Status | Evidence (short) | Fix phase |
|---|---|---|---|
| **D1** Annualization | **CONFIRMED** | `compute_metrics` default `periods_per_year=252.0`; engines omit arg | T1A |
| **D2** Win rate / PF | **CONFIRMED** | `SimFill.public_dict()` has no `realized_delta` | T1A |
| **D3** orders/day | **CONFIRMED** | `RiskGuard.orders_today` never resets | T1B |
| **D4** Tiny sizing | **CONFIRMED** | `qty=None` → ~1% notional via `per_trade_risk_pct` | T1B |
| **D5** Dual fills / partials | **CONFIRMED** | `FillModel` vs `NextBarFillModel`; partial → remainder dropped | T1B |
| **D6** Resume / lease | **CONFIRMED** | Incomplete checkpoints; soft `worker_pid=1` no TTL | T1C |
| **D7** Data hash | **CONFIRMED** | `prepare()` loads path; no hash compare | T1C |
| **D8** Hot path | **CONFIRMED** | Per-write SQLite conn; O(n²) equity reload; full `list[Bar]` | T1C / T2A |
| **D9** Ingest | **CONFIRMED** | All-or-nothing INVALID; YYYYMMDD→1970; no quality report | T2A / T2B |
| **D10** Clock.bars | **CONFIRMED** | Public `bars`; string `assert_no_future` | T1D |
| **D11** Caller metrics | **CONFIRMED** | `complete_experiment` accepts arbitrary metrics | T5A |
| **D12** Key mismatch | **CONFIRMED** | Acceptance reads `*_pct` / `trade_count`; metrics emit fractions | T5A |
| **D13** WFA not executed | **CONFIRMED** | One chronological split stored; no per-window runs | T5B |
| **D14** Trial ledger | **CONFIRMED** | Rejected-only fingerprint; upsert drops `strategy_version` | T5A |
| **D15** Memory disconnect | **CONFIRMED** | Fresh empty `StrategyMemoryIndex` per run | T6A |
| **D16** Gateway bypass | **CONFIRMED** | Routes → service directly; `crypto_paper` both-branch AVAILABLE | T4A |
| **D17** Agents not agents | **CONFIRMED** | Deliberation = DSL; fleet → GENERIC; reconcile → INTERRUPTED | T7A |
| **D18** Paper fragile | **CONFIRMED** | Manual orders; no RiskGuard; shared wallet reset | T9A / T9B |
| **D19** Secrets/network | **PARTIAL** | Alpaca keys still `os.environ`; HTTP via provider_io when bound; Binance/Stooq still raw urllib | T4C / T2D |
| **D20** Product surface | **CONFIRMED** | No order_type/limit on intent; unrealized stub 0; options/futures/forex NOT_IMPLEMENTED | T3A+ |
| **D21** Migration drift | **CONFIRMED** | Real head **41**; `test_migrations` asserts **32** | first fix / T4D |
| **D22** Brain as_of | **CONFIRMED** | `BrainFacade.retrieve` has no `as_of` | T6B |
| **D23** Providers | **CONFIRMED** | Binance cap 1000, no pagination; urllib; CsvLocal first glob | T2D |
| **D24** Instruments unused | **CONFIRMED** | `InstrumentSpec` unused in fill/risk; unknown→EQUITY | T3B |
| **D25** Double-claim | **CONFIRMED** | SELECT then UPDATE without `BEGIN IMMEDIATE`; dual worker planes | T4B |
| **D26** JobRuntime | **PARTIAL** | Cap reserved + enqueue path exists when externalized; default still soft daemon | T4B |
| **D27** UI gaps | **CONFIRMED** | Hard-coded 4-agent create; oldest-N live + `.slice(-40)` | T10A |
| **D28** Weak tests | **CONFIRMED** | Short determinism window; demo accepts RUNNING; hand metrics | ongoing / T11 |
| **D29** Per-agent eval | **CONFIRMED** | Leaderboard lacks Sharpe/DD/CI | T1A / T8D |
| **D30** Commit-reveal | **CONFIRMED** | info_version = last 64 closes; poke `_open`; veto mutates commit | T1D |
| **D31** Cadence | **CONFIRMED** | Default agents injected; deliberation_every_n side-effect | T1D |

No claim was REFUTED. No ALREADY_FIXED.

### Notable nuances

- **D19:** Alpaca *HTTP* can go through provider_io workers; credential source and public providers remain defective.
- **D26:** Durable `market_sim.advance` path exists when workers externalized + `job_runtime` bound; soft-lease default path still present → PARTIAL.
- **D6 clock:** legacy prepare overwrites index after `bar_index-1` (skips re-process) but still fails to restore `avg_entry` / pending / peak; multi-engine off-by-one remains clear.
- **D9 µs epochs:** `_normalize_ts` of a 16-digit µs epoch raises `ValueError` after one `/1000` — mishandled, not silently wrong-dated.

---

## Ownership map (sole authorities — Part C.1)

| Concern | Sole authority (current / target) |
|---|---|
| Market clock / causality | `SimulationClock` → Kernel v2 |
| Orders / fills / positions / PnL | engines + accounting → Kernel v2 |
| Execution-cost truth | fill models → unified Kernel execution model |
| Trading risk decision | `RiskGuard` → Risk Engine v2 |
| External side-effect authority | **should be** ExecutionGateway (today: routes bypass) |
| Long-running work | JobRuntime / JobStore (`market_sim.advance` reserved) |
| Worker process ownership | Worker Supervisor / Registry (`pool_id=market_sim`) |
| Trading job pool | existing `market_sim` pool — **no second queue** |
| Model calls | Model Control Plane |
| Agent execution | AgentFleet / AgentRuntime / Cognitive Runtime |
| Secrets | SecretsBroker (today bypassed for Alpaca env) |
| User/system configuration | Settings Control Plane (`markt_sim`) |
| Metadata persistence | central SQLite + MigrationRunner |
| Large series/artifacts | ArtifactStore (not yet wired for equity/trades) |
| Knowledge/memory | Knowledge V2 / Memory (as_of missing) |
| Verified trading evidence | trial/validation ledgers (local/incomplete today) |
| Strategy promotion | not yet — Promotion state machine (T6C) |
| Frontend HTTP client | `Data/frontend/src/api/client.ts` |
| Frontend contracts | `Data/frontend/src/types/api.ts` |
| Navigation/routes | `App.tsx` + `navigation/menu.ts` |

### Worker / job / capability map

| Item | Location | Value |
|---|---|---|
| Pool | `workers/pools.py` | `pool_id="market_sim"`, entrypoint `Data.modules.workers.entrypoints.market_sim`, `CPU_HEAVY` |
| External caps | `jobs/runtime.py` | `market_sim.advance`, `provider.market.fetch`, `provider.alpaca.paper` |
| Catalog caps | `execution/builtins.py` | same IDs registered for fabric workers |
| Compat script | `scripts/market_sim_worker.py` | soft daemon via `from_settings` — competing plane today |
| Gateway mutations | routes | **bypass** — direct `MarketSimControlPlane` calls |

### API route map

All under `/api/market-sim/*` (see `routes/market_sim.py`): status, health, data*, strategies*, runs*, providers*, capabilities, paper/*, experiments*, demos/run, live-trading. Adjacent: `POST /api/trading/order` → TradingStub 501.

### Frontend routes (preserve)

`/trading/simulatie`, `/strategieen`, `/marktdata`, `/portefeuille`, `/paper`, `/broker` — menu owned by `navigation/menu.ts`. Missing v4 pages (Onderzoek, Validatie, Bibliotheek, Training, Risico) wait for backend capability (T10B).

---

## Reuse map (do not invent parallel stacks)

| Need | Reuse | Avoid |
|---|---|---|
| Side effects / approvals | ExecutionGateway + CapabilityCatalog | Direct route→broker; second catalog |
| Long work / leases | JobRuntime + JobStore | Soft forever-lease; second queue |
| Secrets | SecretsBroker | `os.environ` for Alpaca in prompts/logs |
| Agents / missions | AgentFleet + AgentRuntime + Cognition | Second fleet; LLM in per-bar loop |
| Promotion pattern | `training/promotion.py` + evaluation gates | Silent “prod” swap |
| Isolation | `isolation/*` + honest effectiveIsolation | Claiming OS isolation without probes |
| Persistence | MigrationRunner + ArtifactStore | Second trading DB |
| Live refusal | LiveTradingGuard + TradingStub | Third refuse path |
| Multi-agent games | Keep commit_reveal + multi_engine | Rewriting competition for research kernel |
| UI | Existing `/trading/*` + `/api/market-sim/*` | Second Trading shell/API |
| Data root | `LEVIATHAN_MARKETS_ROOT` | Committing bulk OHLCV to git |

---

## Conflict risks

1. Two “capability” languages — status matrix vs Gateway catalog (T4A).
2. Two workers — soft daemon vs JobRuntime (T4B); dual claim corrupts runs.
3. Two order surfaces — `/api/trading/order` stub vs paper routes.
4. In-sim “agents” vs Fleet agents — do not conflate.
5. Provider urllib vs network policy.
6. HADES / editor — do not import.

---

## Baseline suite honesty (T0)

| Suite | Result | Notes |
|---|---|---|
| `test_market_sim_characterization.py` | **74 passed, 31 xfailed** | T0 deliverable |
| `test_market_sim.py` | run in baseline | — |
| `test_trading_center.py` | run in baseline | uses hand-typed metrics (D11/D28) |
| `test_migrations.py` | **expected FAIL** (asserts head 32 vs 41) | D21 evidence |
| Full `Data/backend/tests` | recorded in state log | pre-existing failures allowed if unrelated |
| Frontend typecheck/lint/test/build | recorded in state log | — |
| `scripts/verify_trading_100.py` | exits **1** (gates NOT_STARTED) | expected until 100% |

---

## Performance budget freeze

- [`trading_reference_hardware.json`](./trading_reference_hardware.json) — Linux Cloud Agent VM (Windows target documented).
- [`trading_performance_budget.json`](./trading_performance_budget.json) — hard memory/OOM + complexity invariants; throughput reportable.

---

## Explicitly NOT claimed (unchanged)

Profitability; gym→real transfer; production live execution; L5 autonomy; microstructure without L2/L3; options/futures/forex unless proven; tax/legal; investment advice.
