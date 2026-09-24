# LEVIATHAN Trading Gap Report — Phase T0

**Date:** 2026-09-24  
**Branch:** `cursor/trading-phase-t0-6512`  
**Scope:** Recon + characterization only. **No feature/fix code.**  
**Program:** [`trading_program.md`](./trading_program.md) (v2, source-verified)  
**Operator note:** Market data is operator-supplied; this phase does not ingest or commit bulk OHLCV.

---

## Verdict

All defects **D1–D21 are PRESENT** (re-verified against current `origin/main` source). The Market Simulation module is substantially further along than early docs alone suggested (multi-engine, Decimal wallets, commit-reveal, paper brokers, experiments, capability matrix, live guard), but **correctness defects D1–D8/D10 must be fixed before new research features are trusted**. Statistical/architecture gaps D11–D21 remain as documented.

**Characterization suite:** `Data/backend/tests/test_market_sim_characterization.py`  
**Result (this run):** `66` tests — `45` pass (current-behaviour evidence) + `21` expectedFailure (desired contracts for T1+).

**Stop for approval** before Phase T1.

---

## Real migration head (D21)

| Source | Head |
|---|---|
| `Data/backend/migrations.py` `MIGRATIONS[-1]` | **34** (`trading_center`) |
| Contiguous versions | `1 … 34` |
| `test_migrations.py` expectation | **32** (stale — **FAILS** today) |

Next free contiguous migration number: **35**.

Existing trading-related schema: **v16** (`market_sim`) + **v34** (`trading_center` — paper sessions, experiments, strategy memories, source ALTERs). Extend these; do not invent a second DB.

---

## Defect register (PRESENT / ABSENT / UNKNOWN)

| ID | Status | Evidence (short) | Fix phase |
|---|---|---|---|
| **D1** Annualization | **PRESENT** | `compute_metrics(..., periods_per_year=252.0)`; both `_finalize_metrics` omit the arg | T1 |
| **D2** Win rate / PF | **PRESENT** | `SimFill.public_dict()` has no `realized_delta`; metrics stay UNMEASURED | T1 |
| **D3** orders/day | **PRESENT** | `RiskGuard.orders_today` incremented in multi fill path; never rolled | T1 |
| **D4** Tiny sizing | **PRESENT** | `qty=None` → ~1% notional via `per_trade_risk_pct` | T1 |
| **D5** Dual fills / partials | **PRESENT** | `FillModel` vs `NextBarFillModel`; partial → `intent.status="filled"`, remainder dropped | T1 |
| **D6** Resume / lease | **PRESENT** | Multi `prepare` rewinds clock (`bar_index-1`), rebuilds wallets from initial cash; `worker_pid=1` no TTL; not JobRuntime | T1 / T5 |
| **D7** Data hash | **PRESENT** | `prepare()` loads path; no sha256 vs `run.data_hash` | T1 |
| **D8** Hot path | **PRESENT** | New SQLite conn per write; multi reloads equity every slice; `list_equity` truncates; `load_ohlcv` → full `list[Bar]` | T1 / T2 |
| **D9** Ingest | **PRESENT** | All-or-nothing INVALID; duplicates OK; `YYYYMMDD` → 1970 epoch; µs epoch overflow; no quality report | T2 |
| **D10** Clock.bars | **PRESENT** | Public `bars` bypasses `observe()`; `assert_no_future` is string `>` | T1 |
| **D11** Caller metrics | **PRESENT** | `complete_experiment` accepts arbitrary `metrics` → `evaluate_acceptance` | T4 |
| **D12** Key mismatch | **PRESENT** | Acceptance reads `*_pct` / `trade_count`; `compute_metrics` emits fractions / no trade_count | T4 |
| **D13** WFA not executed | **PRESENT** | One chronological split stored; no per-window runs; no CPCV/PBO/DSR | T4 |
| **D14** Trial ledger | **PRESENT** | Fingerprint blocks rejected-only; upsert omits `strategy_version` on UPDATE | T4 |
| **D15** Memory disconnect | **PRESENT** | `MultiEngineState.memory` empty; `prepare` never calls `list_strategy_memories` | T7 |
| **D16** Gateway bypass | **PRESENT** | Routes → service directly; role “capabilities” are labels; `crypto_paper = AVAILABLE if … else AVAILABLE` | T5 |
| **D17** Agents not agents | **PRESENT** | Deliberation = DSL; fleet → `GENERIC`; `reconcile` → `INTERRUPTED` | T8 |
| **D18** Paper fragile | **PRESENT** | Manual orders only; no RiskGuard; `start_paper_session` resets shared `broker.wallet.cash` | T9 |
| **D19** Secrets/network | **PRESENT** | Alpaca/env + urllib; LiveTradingGuard env; providers urllib; no SecretsBroker | T5 |
| **D20** Product surface | **PRESENT** | options/futures/forex `NOT_IMPLEMENTED`; `OrderIntent` lacks order_type/limit; `Portfolio.unrealized_pnl` stub 0; demo copies test fixtures | T3 / later |
| **D21** Migration drift | **PRESENT** | Real head 34; `test_migrations` asserts 32 (**fails**) | T0 follow-up / first fix PR |

No claim was refuted (ABSENT). No UNKNOWN after recon.

### Notable nuances (not ABSENT)

- **D6 clock:** legacy `SimulationEngine.prepare` sets `bar_index-1` then overwrites to `bar_index` (skips re-process) but still fails to restore `avg_entry` / pending intents / peak equity. Multi-engine off-by-one is clear.
- **D9 µs epochs:** `_normalize_ts("1704067200000000")` raises `ValueError: year … out of range` after a single `/1000` — mishandled, not silently wrong-dated.
- **D10:** `assert_no_future` is defined but unused in production call sites; public `bars` remains the real look-ahead hazard for future code strategies.

---

## Reuse map (do not invent parallel stacks)

| Need | Reuse | Avoid |
|---|---|---|
| Side effects / approvals | `ExecutionGateway` + `CapabilityCatalog` (`execution/`) | Direct route→broker side effects; second catalog |
| Long work / leases | `JobRuntime` + JobStore leases/heartbeats | Soft `worker_pid` forever-lease; second queue |
| Secrets | `SecretsBroker.issue` / `resolve_lease` | `os.environ` for Alpaca; secrets in prompts |
| Agents / missions | `AgentFleetService` + `AgentRuntime` + Cognition DAG | Second fleet/mission store; LLM in per-bar loop |
| Promotion pattern | `training/promotion.py` + `evaluation/platform.py` gates | Silent strategy “prod” swap |
| Isolation / sandbox | `isolation/*` + Module Manager honesty | Claiming OS isolation without measured probes |
| Persistence | Central SQLite via `MigrationRunner` + `ArtifactStore` for series | Second trading DB |
| Live refusal | `LiveTradingGuard` + `TradingStub` (501) | Third refuse path with different semantics |
| Multi-agent games | Keep `commit_reveal` + `multi_engine` | Rewriting competition protocol for research kernel |
| UI | Existing `/trading/*` Dutch pages + `/api/market-sim/*` | Reskin or second Trading API |
| Data root | Operator markets root / `LEVIATHAN_MARKETS_ROOT` | Committing bulk OHLCV to git |

---

## Conflict risks

1. **Two “capability” languages** — `build_market_capabilities` status matrix vs Gateway `CapabilityCatalog`. T5 must register real caps without deleting the honesty matrix.
2. **Two workers** — `MarketSimWorker` daemon vs `JobRuntime`. Dual claim of the same run would corrupt leases; migrate ownership cleanly.
3. **Two order surfaces** — `/api/trading/order` (stub 501) vs `/api/market-sim/paper/*`. Keep stub as live-refuse only.
4. **In-sim “agents” vs Fleet agents** — roles in deliberation are DSL participants; Fleet is durable registry. Do not conflate mission state with sim rounds.
5. **ProviderRegistry vs future NETWORK caps** — public Binance/Stooq urllib bypasses network policy today.
6. **HADES / editor** — do not import from `Data/HADES` or editor folders (invariant).

---

## Frontend surface (recon)

Pages under `Data/frontend/src/pages/trading/`: Marktdata, Simulatie, Strategieën, Paper, Portefeuille, Broker + `shared.tsx`. Menu: TradingCenter. Styles: `trading.css` / `trading-pages.css`. API via existing client patterns to `/api/market-sim/*`. Broker page is honesty/blocked. **Do not re-skin in T0–T9**; T10 extends tabs only.

`test_trading_center.py` covers next-bar fills, commit-reveal, risk override block, kill-switch, memory as-of causality, capabilities NI, TradingStub refuse, demos, paper idempotency, hand-crafted acceptance — **not** Gateway wiring, metric-key honesty, walk-forward execution, or migration head.

---

## Proposed file-level plan (post-approval)

### Phase T1 (correctness) — extend in place
- `metrics.py` — timeframe→`periods_per_year`; round-trip trade metrics
- `types.py` / engines — `realized_delta` / trade ledger on fills
- `risk_guard.py` + `multi_engine.py` — day rollover; sizing models recorded on run
- Unify on Decimal fill path (`execution.py`); deprecate dual use of `fill_model.py` for new runs (keep selectable until Kernel v2)
- `engine.py` / `multi_engine.py` / `worker.py` / `store.py` — checkpoint resume, hash check, batched persistence, lease expiry
- `causality.py` — add bounded `MarketView` (keep `SimulationClock` semantics)
- Fix **D21** in `test_migrations.py` → expect head **34** (or 35 if T1 ships a migration)
- Characterization expectedFailures for D1–D8, D10 → remove markers as fixed

### Phase T2 — `ingest/` / data platform (streaming, quality, calendars, splits)
### Phase T3 — `kernel/` + strategy spec v2 (parity before deprecating legacy)
### Phase T4 — validation / trial ledger / acceptance from run IDs
### Phase T5 — Gateway caps, JobRuntime worker, SecretsBroker for Alpaca
### Phase T6–T11 — as in `trading_program.md`

Suggested first migration (when T1 needs schema): **v35** — run checkpoints, trade ledger table, lease/heartbeat columns on `market_sim_runs` (adapt after T1 design). Prefer ALTER/extend over duplicate table families.

---

## Risk register

| Risk | Impact | Mitigation |
|---|---|---|
| Fixing metrics changes historical run numbers | Confusion / false “regressions” | Version metrics; record `periods_per_year` + kernel/metrics version on run |
| Unifying fill models changes equity curves | Breaks golden comparisons | Keep `engine: legacy` selectable until Kernel v2 parity (program §T1/T3) |
| JobRuntime migration orphans in-flight runs | Stuck runs | Lease expiry reclaim + one-shot reconcile tool |
| Sealed holdout discipline not yet enforced | Future overfitting | Do not expand experiment acceptance until T4 |
| Large 1m crypto files | OOM on `list[Bar]` | No full-list hot path after T2; operator data stays out of git |
| Enabling live accidentally | Capital risk | Keep LiveTradingGuard + TradingStub; `TRADING_LIVE` default false forever in this program |
| LLM treated as evidence | False discoveries | Numeric claims only from run/evidence IDs (T4/T8) |

---

## Characterization test map

File: `Data/backend/tests/test_market_sim_characterization.py`

| Pattern | Meaning |
|---|---|
| `test_dN_current_*` | Documents broken/current behaviour — **passes now** |
| `test_dN_desired_*` + `@expectedFailure` | Desired contract — **xfail until fixing phase** |

**This run:** `Ran 66 tests in ~1.3s — OK (expected failures=21)`.

Also confirmed separately: `test_migrations.MigrationRunnerTests` **FAILS** on head expectation 32 vs real 34 (D21 evidence).

---

## Explicitly NOT claimed (T0)

- No correctness fixes applied  
- No new features, flags, routes, or migrations  
- No profitability of any strategy  
- No live trading path  
- No bulk market data supplied or committed (operator-owned)  
- Full backend/frontend suites not re-run end-to-end in T0 beyond characterization + migration probe  
- Live LLM / live feed / live broker **NOT TESTED**

---

## Approval gate

Please approve **Phase T1 — Correctness Fix Wave (D1–D8, D10, D19-part, D21 test alignment)** before any feature work. Recommended first commit in T1: turn D21 green by aligning `test_migrations.py` to head 34, then failing→fix loops per defect with characterization markers removed as they pass.
