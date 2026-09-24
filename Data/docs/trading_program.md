# LEVIATHAN — TRADING RESEARCH FACTORY & PAPER-TRADING PROGRAM (v2, source-verified)

> **How to use:** save as `Data/docs/trading_program.md` and reference it with `@` in Cursor Agent mode, or paste it as the first message. Then run **one phase at a time** using the kickoff lines in section 14. Never ask for everything in one go.
>
> **What changed vs. v1:** v1 was written from the docs only. v2 is written after reading the actual source of `Data/modules/market_sim/` (types, engine, multi_engine, execution, fill_model, accounting, portfolio, risk_guard, metrics, experiments, strategy_eval, service, store, ohlcv, data_store, worker, roles, deliberation, paper_broker, capabilities, live guard), `routes/market_sim.py`, `test_market_sim.py`, `agents/fleet.py` and the docs. **The module is much further along than the docs alone suggest — so this is an EXTEND-AND-HARDEN program, not a greenfield build — but the source also contains concrete correctness defects (section 3) that must be fixed before any new feature is trusted.**
>
> **Not read yet (Phase T0 must read them):** `providers/*`, `brain_hooks.py`, `commit_reveal.py`, `instruments.py`, `Data/modules/trading/stub.py`, `Data/backend/main.py`, `config.py`, `migrations.py` (tail), `execution/gateway.py` + `builtins.py`, `jobs/runtime.py`, `cognition/runtime.py`, `agents/runtime.py`, `security/secrets_broker.py`, `isolation/*`, `module_manager/*`, `training/promotion.py`, `evaluation/platform.py`, the Trading Center frontend pages, `test_trading_center.py`.

---

# 0. ROLE AND MISSION

You are a principal engineer with deep experience in quantitative research infrastructure (backtesting engines, execution simulators, statistical validation, risk systems) and in agentic AI platforms. You work inside `syneyexx/leviathan`, a Python-first, local-first AI control plane.

**Mission:** turn the existing Market Simulation into a **Strategy Research Factory + Paper-Trading System** that can:

1. Ingest years of historical data (e.g. 2015–2020 OHLCV, equities and crypto) as immutable, versioned, quality-checked datasets.
2. Replay it through a deterministic, strictly causal simulator with realistic costs, long/short, multiple instruments and proper accounting.
3. Let **LLM-driven agents** (through the existing Agent Fleet / Cognitive Runtime / Gateway) propose, implement, test, criticize, store, recall and evolve strategies — with all numbers coming from a run ledger, never from model text.
4. Validate strategies with statistically honest methods (rolling walk-forward, purged CV, global trial counting, deflated Sharpe, sealed holdout) so overfitted candidates are rejected cheaply and automatically.
5. Promote survivors through an evidence-gated lifecycle into **autonomous forward paper trading** on live data.
6. Provide a **live-execution-ready architecture** that stays **blocked by default** and only opens through explicit human-controlled gates.

**Honesty clause:** no strategy is guaranteed to make money; most candidates will fail out-of-sample. The system's value is how reliably it *rejects false discoveries* and *records what it learned* — not how many profitable backtests it shows. Never build anything whose effect is to make results look better without making them more truthful.

---

# 1. NON-NEGOTIABLE LEVIATHAN INVARIANTS

From `leviathan_system.md`, `cursor.md`, `buildplan.md`, `market_sim.md` and visible in the code's own `truth` blocks:

```
model output          != evidence          request              != authority
capability            != authority         dispatch             != completion
unmeasured            != passed            registered           != trained
neural / LLM signal   != authority         backtest             != proven strategy
paper profit          != live readiness    OHLCV                != order book
```

- **Python first.** No native code.
- **One infrastructure path.** Side effects go through `ExecutionGateway` + `CapabilityCatalog` + `ApprovalService`/`PolicyEngine`; long-running work through `JobRuntime`; secrets through `SecretsBroker`; agents through the existing `AgentFleetService`/`AgentRuntime`/`MultiAgentCoordinator`/Cognitive Runtime. **No second job queue, secret store, agent stack, DB or model client.**
- **One persistence architecture.** Central SQLite via `MigrationRunner` (contiguous versions) + `ArtifactStore` for large series. `main.py` stays a composition root.
- **Truthful failure.** `UNAVAILABLE` / `UNMEASURED` / HTTP 409/501, never fabricated fills, metrics or success.
- **Feature flags**, default OFF for anything risky; hierarchical validation in `config.py`.
- **Optional dependencies** (numpy, pyarrow, scipy, numba) live in a separate `requirements-trading.txt`, are capability-detected at runtime, and the stdlib path must stay **correct** (slower is fine). Ask before adding anything else.
- **Do not read, import from, or depend on `Data/HADES` or editor folders.** Do not depend on other repositories.
- Tests + docs are part of every phase: full `pytest Data/backend/tests` and frontend `typecheck / lint / test / build` green; newest entry on top of `buildplan.md`; update `cursor.md` ownership rows and `market_sim.md`.
- UI labels of the Trading Center stay **Dutch**; code, comments, identifiers and docs stay English. Existing API bodies use camelCase (`sourceId`, `feeBps`) — keep that convention.

---

# 2. GROUND TRUTH — WHAT EXISTS (verified in source)

| Area | File(s) | What it really does today |
|---|---|---|
| Control plane | `service.py` `MarketSimControlPlane` | Data scan/register, strategy CRUD/versions/fork/archive, run lifecycle, provider import, paper sessions, experiments, demos. Gated by `LEVIATHAN_FEATURE_MARKET_SIM`. |
| Legacy engine | `engine.py` `SimulationEngine` + `portfolio.py` + `fill_model.py` | Single instrument, **long-only**, float accounting, next-bar-open fills, optional deliberation round. |
| Multi engine | `multi_engine.py` + `accounting.py` + `execution.py` + `risk_guard.py` + `commit_reveal.py` | Per-agent `Decimal` wallets, commit-then-reveal, `NextBarFillModel` (participation cap → partial fills), `RiskGuard`. Game modes: individual / shared / tournament. Also long-only, single instrument. |
| Clock | `causality.py` `SimulationClock` | Sole time authority; `observe()`/`window()` refuse look-ahead. |
| Strategy | `strategy_eval.py` | Structured DSL with **two** rule kinds: `ma_cross`, `mean_reversion`. `strategy_content_hash` over params/rules. No `eval`. |
| Strategy store | `store.py`, `types.py` | `market_strategies` + immutable `market_strategy_versions` (params, entry/exit/risk rules, hash, changelog). Status only `DRAFT/ACTIVE/ARCHIVED`. |
| Metrics | `metrics.py` | Total return, Sharpe, Sortino, max DD, turnover, fees, buy&hold, `MeasurementState`-style `MEASURED/UNMEASURED`. |
| Experiments | `experiments.py`, `service.propose/complete_experiment` | Hypothesis ledger (`ExperimentTrial`, fingerprint, retained rejects), one chronological design/validation/test split, acceptance criteria, causal `StrategyMemoryIndex`. |
| Data | `ohlcv.py`, `data_store.py`, `providers/` | CSV/Parquet(optional) → `list[Bar]`; file hash; symbol/timeframe inferred from filename; providers `csv_local`, `binance_public`, `stooq_public`. |
| Worker | `worker.py`, `scripts/market_sim_worker.py` | Daemon thread (or subprocess entrypoint); 50-bar slices; soft lease via `worker_pid`. |
| Paper | `paper_broker.py`, `service.paper_*` | `LocalPaperBroker` (in-memory `WalletLedger`), optional `AlpacaPaperBroker` (paper endpoint only), manual order placement, per-session kill switch. |
| Live guard | `trading_live_guard.py`, `Data/modules/trading/stub.py` | Real orders refused (501) always; env-based "unlock" reported but never enables anything. **Keep exactly this default.** |
| Roles | `roles.py` | Registers trading role specs into the Agent Fleet (analyst, researcher, critic, risk, PM, evaluator, orchestrator). |
| Deliberation | `deliberation.py` | **Deterministic** DSL evaluation per "agent" + vote + rule-based veto. No LLM in the trading loop. |
| API | `routes/market_sim.py` | `/api/market-sim/{status,health,data*,strategies*,runs*,providers*,capabilities,paper/*,experiments*,demos/run,live-trading}`. |
| Tests | `test_market_sim.py` | ~100-bar BTC fixture; causality unit tests; a 4-day determinism test comparing fills; no golden/property/statistical/sandbox tests. |

Docs' own honest limitations (keep them true): OHLCV ≠ order book · profitable backtest ≠ profitable live · deterministic DSL ≠ autonomous LLM strategy creation · daemon thread ≠ isolated process · local paper fills ≠ exchange-matched · live money not implemented.

---

# 3. VERIFIED DEFECTS & GAPS (fix/close these — each starts with a failing test)

Confidence: read directly from source at time of writing. **Re-verify each with a characterization test in Phase T0; if a claim turns out false, say so in the Gap Report and drop it.**

## 3.1 Correctness defects (Phase T1 — fix BEFORE building features)

- **D1 Sharpe/Sortino mis-annualized.** `metrics.compute_metrics(..., periods_per_year=252.0)` default is used by both engines' `_finalize_metrics` (neither passes `periods_per_year`). 1h crypto or 1m bars get the daily factor. Derive `periods_per_year` from timeframe + instrument calendar (crypto 24/7 vs equity sessions).
- **D2 Win rate / profit factor effectively always `UNMEASURED`.** `compute_metrics` needs `realized_delta` on fills, but `SimFill.public_dict()` (used in both `_finalize_metrics`) does not carry it (it exists only in the `fill` event payload of the legacy engine; the multi engine has none). Replace with a proper **round-trip trade ledger** (entry/exit, MAE/MFE, holding time, gross/net PnL, costs).
- **D3 `RiskGuard.orders_today` is never reset.** `multi_engine` increments it per fill and never rolls it over per simulated day, so `max_orders_per_day=50` is effectively a *lifetime* cap in multi-year runs. Add per-simulated-day rollover based on bar timestamps.
- **D4 Sizing defaults leave strategies almost uninvested.** With `qty=None`, `size_order`/`evaluate_intent` target `min(cap_qty, risk_qty)` where `risk_qty = equity × per_trade_risk_pct / price` — i.e. ~1% of equity in *notional*, capped by `risk_qty*5` (~5%). `per_trade_risk_pct` is treated as notional, not risk-to-stop. Introduce explicit sizing models (fixed fraction, vol-target, risk-to-stop, Kelly-capped) and make the run record which one was used.
- **D5 Two divergent fill models.** `fill_model.FillModel` (float, no participation cap, no partials; used by the legacy engine) vs `execution.NextBarFillModel` (Decimal, participation cap). Also: a partially filled intent is marked `filled` and the remainder silently dropped (no working-order continuation); fee/slippage are flat bps (no spread, no volatility scaling, no funding). Unify on one model.
- **D6 Resume is not restart-safe.** Worker caches `state` in memory (`_states`). On `prepare()` after restart: legacy engine restores cash/position/realized but not `avg_entry`, `peak_equity`, `pending_intents`, or the equity curve used for metrics; multi engine rebuilds `WalletBook` from initial cash (ignores wallet snapshot) and sets `clock.index = bar_index - 1`, so the last processed bar is processed again. Also `claim_next_runnable` sets `worker_pid=1` and only clears it at slice end — a hard crash leaves the run unclaimable forever (no lease expiry/heartbeat). Worker does **not** use `JobRuntime` (leases/heartbeats/resume exist there).
- **D7 Data hash not verified at run start.** `SimRun.data_hash` is stored, but `prepare()` loads the file by path without comparing sha256; the file is mutable on disk.
- **D8 Persistence hot path.** Every bar opens a new SQLite connection for `add_equity_point` (+ events/fills). Multi engine `_finalize_metrics` reloads up to 100 000 equity points **on every 50-bar slice** (O(n²)). `list_equity(limit=2000)` / `list_fills(limit=500)` in `run_live_state` silently truncate long runs. `load_ohlcv` returns a full `list[Bar]` and is called on scan-validation, `prepare`, and `propose_experiment` (3× memory for large files). 1-minute 2015–2020 crypto ≈ 2.6 M bars will not work as-is.
- **D9 Data ingestion is all-or-nothing and shallow.** One OHLC inconsistency or unsorted row marks the whole file `INVALID` (no quality report/repair); duplicate timestamps pass (`ts < prev` only); no gap/calendar/zero-price/zero-volume/outlier checks; naive timestamps assumed UTC (no exchange timezone/session/DST); no adjustment factors/splits/dividends; symbol+timeframe inferred from filename; one symbol per file; scan re-loads and re-hashes every file. `_normalize_ts` treats any all-digit string as epoch seconds/ms — an 8-digit `YYYYMMDD` would be mis-dated to 1970, and microsecond epochs (used by some exchange dumps) are not handled. **Verify with tests before assuming.**
- **D10 `SimulationClock.bars` is a public attribute.** Safe for the DSL, unsafe for future code strategies (future bars reachable by convention only). `assert_no_future` compares ISO strings lexicographically (only valid while all timestamps share one normalized format).

## 3.2 Statistical/evidence gaps (Phase T4)

- **D11 Caller-supplied metrics = model output as evidence.** `POST /api/market-sim/experiments/{id}/complete` accepts an arbitrary `metrics` dict; `complete_experiment` judges it via `evaluate_acceptance`. Anything (including an LLM) can post fake numbers. Acceptance must be computed from **run IDs** by the platform.
- **D12 `evaluate_acceptance` is not wired to real metrics.** It reads `trade_count`, `total_return_pct`, `max_drawdown_pct`, `excess_return_pct`; `compute_metrics` emits `total_return`, `max_drawdown` (fractions, wrapped in status dicts) and no `trade_count`. Fed real run output it would report 0 trades and default drawdown 100 → reject everything.
- **D13 Walk-forward is planned but never executed.** `walk_forward_splits` produces one design/validation/test split that is stored on the trial but no runs are executed per window. No rolling/anchored WFA, no purge/embargo, no CPCV/PBO/DSR, no bootstrap CIs, no robustness suite, no sealed-holdout access log or single-use enforcement.
- **D14 Trial ledger is local, not global.** Fingerprint blocks only an identical *rejected* trial; there is no count of all trials per strategy family/dataset for multiple-testing correction; `market_experiments` rows are upsert-able (not append-only) and `strategy_version` set on completion is not persisted by the upsert.
- **D15 Strategy memory is disconnected.** `MultiEngineState.memory` is a fresh empty `StrategyMemoryIndex` per run and never hydrated from `market_strategy_memories`, so in-engine recall is always empty; DB memories are not linked to Knowledge V2 / Memory / `VerifiedExperience`; regime features are crude thresholds.

## 3.3 Architecture/platform gaps

- **D16 Trading ops bypass the Gateway.** Routes call the service directly. `roles.py` "capabilities" (`market_sim.observe`, …) are labels, not `CapabilityCatalog` entries. No approvals/effect ledger/receipts for paper orders. `capabilities.build_market_capabilities` is a status matrix (and `crypto_paper` returns `"AVAILABLE"` in both branches of its conditional).
- **D17 Agents are not agents.** `deliberation.py`/`multi_engine.py` "agents" are the same DSL with parameter tweaks; risk veto = "BUY with confidence < 0.55 → HOLD" where confidence constants come from `strategy_eval`. Fleet `launch_mission` runs `AgentRuntime.execute` with `GENERIC` kind; missions execute synchronously and `reconcile()` marks active missions `INTERRUPTED` after restart (no resume). There is no LLM strategy authoring, no research campaign runner, no orchestrator loop for trading.
- **D18 Paper trading is manual and fragile.** Orders only via `POST …/paper/sessions/{id}/orders`; no strategy→order loop; no `RiskGuard` pre-trade check in `paper_place_order` (only kill-switch flag + quote presence); `_paper_brokers[broker_id]` is one in-memory wallet shared by all sessions of that broker and `start_paper_session` **resets its cash** (starting a second session resets the first); wallet lost on restart; kill switch is per session (no global); no reconciliation and no paper-vs-backtest drift monitoring.
- **D19 Secrets/network bypass.** `AlpacaPaperBroker` reads `LEVIATHAN_ALPACA_PAPER_*` from `os.environ` and calls `urllib` directly; `LiveTradingGuard`/`capabilities` read env directly. Move to `SecretsBroker` leases + Settings Control Plane + network policy (verify `providers/*` do the same).
- **D20 Product surface.** Instruments: only equity + crypto spot; options/futures/forex `NOT_IMPLEMENTED`. `OrderType.LIMIT` exists but `OrderIntent` has no order type/limit price. `run_market_demo` copies fixtures out of the tests directory at runtime. `Portfolio.unrealized_pnl` property is a stub returning 0.
- **D21 Migration numbering drift.** `test_migrations.py` asserts head version 32, while `store.py` comments/`trading-center-architecture.md` refer to migration v34. Determine the real head from `migrations.py`; the test is either stale or failing. Use the next free contiguous number.

---

# 4. TARGET ARCHITECTURE (delta on what exists)

```
 Operator UI /trading/*  (existing pages: Marktdata, Simulatie, Strategieën, Paper, Portefeuille, Broker)
        │ typed client (src/api/client.ts)                                   [EXTEND]
 /api/market-sim/*  (keep)   +  new groups (validation, campaigns, library, promotion, risk)
        │
 MarketSimControlPlane  ── side effects via ExecutionGateway (capabilities registered)  [NEW: D16]
   ├─ ingest/        Data platform v2: streaming import, quality report, calendars, adjustments, splits  [NEW, replaces D9 parts of ohlcv/data_store]
   ├─ kernel/        Kernel v2: one causal engine, multi-asset, long/short, order types, unified fills  [NEW; legacy engines kept until parity]
   ├─ strategies/    Spec v2 (superset of current DSL), indicators, sizing, code-strategy sandbox      [EXTEND strategy_eval/store]
   ├─ validation/    Metrics v2, trial ledger, WFA, purged CV/CPCV, PBO/DSR, robustness, sealed eval   [NEW; replaces experiments.py acceptance]
   ├─ library/       Persistent strategy memory ↔ Knowledge V2 / Memory / VerifiedExperience           [EXTEND experiments memory]
   ├─ factory/       Campaigns + LLM agent executors on Agent Fleet / Cognition DAG                    [NEW]
   ├─ promotion/     Evidence-gated lifecycle (reuse flywheel/evaluation gate patterns)                [NEW]
   ├─ live_paper/    Autonomous paper runner, reconciliation, drift monitor                            [NEW]
   ├─ risk/          Risk engine v2 + global kill switch + autonomy levels                             [EXTEND risk_guard]
   └─ brokers/       BrokerAdapter protocol: PaperBroker(persistent), ReplayBroker, Alpaca-paper, LiveBroker(UNSUPPORTED stub)
        │
 JobRuntime (leases/heartbeats/resume) replaces the soft-lease worker                                  [D6]
 Central SQLite (+ ArtifactStore for equity/trade series) · Evidence · Verification · Approvals · Observability
```

Keep as-is (do not rewrite): `SimulationClock` semantics, `commit_reveal.py` + `multi_engine` for **multi-agent competition games**, `LiveTradingGuard` + `TradingStub` refusal, `RiskGuard` override-key sanitizer, `providers` registry shape, the `truth` blocks convention.

---

# 5. PHASED PLAN

Each phase = separate PR-sized unit. Stop and report after each: files changed, migration(s), flags/capabilities/endpoints, **real** test pass counts, measured throughput, known limitations, EXTERNAL-FIRST review, "Explicitly NOT claimed".

## Phase T0 — Recon + characterization tests + Gap Report (no feature code)
1. Read everything listed at the top as "not read yet", plus all `market_sim/*`, frontend Trading pages, `test_trading_center.py`.
2. Write characterization tests that **prove or refute D1–D21** (each as a test that currently fails or documents current behavior). Commit them as `test_market_sim_characterization.py` marked with the defect ID.
3. Output `Data/docs/trading_gap_report.md`: per defect PRESENT/ABSENT/UNKNOWN + evidence; reuse points; conflict risks (second registry/DB/gateway/agent stack); real migration head; proposed file-level plan; risk register. **Stop for approval.**

## Phase T1 — Correctness Fix Wave (D1–D8, D10, D19-part)
- Timeframe-aware annualization (D1); round-trip trade ledger and derived win rate/PF/expectancy/holding time (D2); simulated-day rollover for order caps (D3); explicit sizing models (D4); unify fill model — one Decimal-based model with spread + volatility-scaled slippage + participation cap + working-order continuation for partials (D5); restart-safe checkpoint/resume including wallets/pending intents/peak equity/RNG, and fix the off-by-one clock resume (D6); verify dataset sha256 at run start and refuse on mismatch (D7); batched/transactional persistence (one connection per slice, `executemany`), incremental metrics (no full reload per slice), paginated series with downsampling instead of silent truncation, streaming bar iteration instead of full lists (D8); make future bars unreachable for code strategies by giving them a bounded `MarketView` rather than the clock (D10).
- Keep `engine: legacy` selectable until Kernel v2 parity is proven (T3).
- **Exit:** all characterization tests for these defects now pass; determinism test extended (kill/resume ⇒ byte-identical trade log); no behavior claims without a test.

## Phase T2 — Data Platform v2 (D9, D7, D8)
- Streaming ingest (resumable, content-addressed; reuse `datasets/shards.py`, `common/atomic.py`, `hashing.py` patterns). Column-mapping API for arbitrary CSV/Parquet; multi-symbol files; symbol/timeframe/timezone/exchange/currency/asset class stored explicitly (not inferred from filename).
- **Robust timestamp parsing** (ISO, epoch s/ms/µs, `YYYYMMDD`, exchange-local with tz) with explicit `bar_open_time` vs `bar_close_time` convention (information available at close).
- **Quality report** per dataset (persisted, `PASSED/WARN/FAILED/UNMEASURED` per check): duplicates, ordering, gaps vs calendar, OHLC consistency (repair-or-quarantine policy, never silent), non-positive prices, zero-volume runs, outlier returns (robust z), stale runs, split-like jumps, DST/timezone anomalies, weekend bars in equity data.
- Corporate actions: store raw + adjustment factors separately, point-in-time adjustment; missing data ⇒ `ADJUSTMENT: UNMEASURED` and the dataset cannot reach promotion-grade.
- `universe_type: POINT_IN_TIME | SURVIVOR_BIASED | UNKNOWN` (caps promotion, see T6).
- Deterministic resampling (no future leak); regime labels v2 (volatility/trend/drawdown/stress) persisted with rules; **2015–2020 sample:** the system must report per-regime and per-year results (2015–16 selloff, 2018 Q4, Mar 2020).
- Immutable **split manifests** `TRAIN / VALIDATION / SEALED_TEST` with **purge + embargo**; sealed range is write-once and each evaluation is logged (`market_sealed_access_log`).
- `MarketDataFeed` protocol so historical replay and live paper consume the same bar-event interface.
- **Exit:** 5-year 1m crypto and 5-year daily equity sample import within a memory budget (measure, record); quality report shown; no full-file `list[Bar]` on the hot path.

## Phase T3 — Kernel v2 + Strategy Spec v2
- **Kernel v2** (`kernel/`): event-driven, single causal clock, multi-instrument portfolio, **long/short**, MARKET/LIMIT/STOP/STOP_LIMIT + TIF + bracket/OCO as first-class objects (add order type/limit price to intent), margin/leverage/liquidation (config-gated, default off), fees/spread/slippage/funding (crypto perps)/borrow costs; intra-bar ambiguity policy recorded per run (`PESSIMISTIC` default, `OPTIMISTIC`, `OHLC_PATH`, `LOWER_TIMEFRAME`); liquidity cap + partial fills; execution delay ≥ 1 bar default (0 only as labeled close-auction mode). `Decimal`/scaled-int accounting with per-step invariants (`equity == cash + Σ pos×mark`, realized+unrealized reconcile, fees ≥ 0, no negative cash unless margin).
- **Run fingerprint** = hash(dataset_version, split, strategy_version_hash, params, cost model, fill policy, sizing model, timing, kernel_version, seed). Same fingerprint ⇒ byte-identical trade log/equity, including after kill/resume.
- Throughput measured and recorded per run (bars/sec). Optional vectorized screening path only if an equivalence test against the reference path exists.
- **Parity:** Kernel v2 reproduces legacy engine results on the existing fixtures within stated tolerance (or documents each deliberate difference); only then mark legacy `engine: legacy` as deprecated (do not delete without approval).
- **Strategy Spec v2**: strictly backward-compatible superset of the current DSL (`ma_cross`, `mean_reversion` keep working) adding: feature/indicator library (returns, rolling stats, ATR, RSI, MACD, Bollinger, Donchian, ADX, VWAP, realized-vol estimators, z-scores, rank/cross-sectional, funding/carry, calendar, regime) each with declared lookback and a no-look-ahead unit test; entry/exit rule trees; stops/targets/trailing; position sizing (fixed fraction, vol-target, risk-to-stop, capped fractional Kelly, risk parity, caps); rebalancing schedules; universe; required `hypothesis` text (a strategy without a written economic rationale cannot pass `SCREENED`).
- **Code strategies** (Python) only inside a sandbox: AST allow-list, subprocess via Module Manager/Isolation with CPU/memory/wall limits, no network/FS, honest *requested vs effective isolation*; receives only a bounded read-only `MarketView`. Sandbox-escape tests are mandatory.
- **Lineage:** `parent_version_id`, proposer (human/agent role/mutation operator), change rationale; append-only.
- **Exit:** golden fills/PnL hand-verified per order type and cost model; property-based accounting invariants; poison-future test passes for every built-in strategy and feature.

## Phase T4 — Evaluation & Statistical Honesty (D11–D14)
- **Metrics v2** from the ledger only: CAGR, vol, Sharpe/Sortino/Calmar, max/avg DD, time under water, ulcer index, profit factor, expectancy, payoff, exposure, turnover, holding time, cost drag (gross vs net), tail metrics (VaR/CVaR/skew/kurtosis), per-year and per-regime breakdown, benchmarks (buy&hold and cost-aware naive baseline), beta/alpha, capacity estimate. Min-sample thresholds ⇒ `UNMEASURED` (not a number).
- **Uncertainty:** block/stationary bootstrap CIs; Probabilistic Sharpe Ratio; **Deflated Sharpe Ratio**.
- **Global Trial Ledger** (append-only; DB triggers or store-level no-update API): *every* backtest — screens, sweeps, agent explorations, failures — is recorded by the kernel entry point itself, so bypass is impossible; feeds DSR and multiple-testing correction. Extend `market_experiments`/`ExperimentTrial` rather than a second table family where reasonable; fix the non-persisted `strategy_version` (D14).
- **Executed** rolling + anchored **walk-forward** (fit on in-sample, evaluate next OOS window, stitch OOS equity, parameter stability, WF efficiency); **purged K-fold + embargo** and **CPCV** with **PBO** across the parameter/strategy family.
- **Robustness suite** as named persisted tests: parameter-plateau, cost stress (×1.5/×2/×3), execution-delay stress, data perturbation, start-date/time-shift, regime/subperiod, cross-asset generalization, trade-level Monte Carlo (drawdown distribution/risk of ruin), **random-entry baseline** (same exits/sizing/exposure), causality guard.
- **Sealed holdout** evaluated at most once per (strategy_version, dataset_version); failure retires the family from further tuning on that dataset version (human override is explicit and logged).
- **Acceptance is computed by the platform from run IDs**; remove/replace the caller-supplied `metrics` path of `complete_experiment` (keep endpoint shape for compatibility but reject metrics not derived from a referenced run ledger; mark such trials `UNVERIFIED`). Thresholds live in the Settings Control Plane (versioned, recorded on every verdict), never hard-coded in prompts.
- Verdicts stored as Evidence and confirmed by the Verification engine.

## Phase T5 — Gateway, Jobs, Secrets integration (D6, D16, D19)
- Register real `CapabilityCatalog` entries (schemas, side-effect classes, tags/aliases so Cognition's shortlist finds them): `market.data.{import,validate,inspect,split}`, `strategy.{register,version,validate_static,causality_guard}`, `sim.run`, `sim.validate.*`, `library.*`, `promotion.{propose,promote,demote}`, `paper.{start,stop,pause}`, `risk.{set_limit,kill_switch}`, `trading.order.submit`. Side-effecting routes call through the Gateway (approvals/observations/receipts).
- Replace the soft-lease worker with `JobRuntime` jobs (leases, heartbeats, expiry, idempotency keys, `ResourceBudgetEnvelope`, resume). Keep `scripts/market_sim_worker.py` as an EXTERNAL-FIRST subprocess worker under the same job protocol.
- Alpaca-paper credentials via `SecretsBroker` leases + Settings; outbound access via network policy; no direct `os.environ`/`urllib` in adapters.

## Phase T6 — Promotion State Machine
Extend `StrategyStatus` beyond `DRAFT/ACTIVE/ARCHIVED` (compat-preserving) with lifecycle stored separately:

```
DRAFT → SCREENED → BACKTESTED → VALIDATED → SEALED_PASSED → PAPER_FORWARD → LIVE_ELIGIBLE      (RETIRED/ARCHIVED from any state)
```

Forward only, one step at a time; each transition needs recorded, verified evidence and an **explicit promote** (never a side effect of a run finishing); one-action demotion. `UNMEASURED` blocks. Survivor-biased/UNKNOWN universes cap at `VALIDATED`. Risk Manager veto is binding (only a logged human decision overrides). **Only a human can enter `LIVE_ELIGIBLE`.** Decay monitor (CUSUM/SPRT/rolling z vs backtest expectation) auto-*suspends*, never deletes. Champion/challenger in shadow using the flywheel pattern (`training/promotion.py`, `evaluation/platform.py` gates — read them first). Append-only transition audit.

## Phase T7 — Strategy Library & Learning (D15)
- Hydrate `StrategyMemoryIndex` from `market_strategy_memories` at run start (respect `available_at ≤ decision time`); make it optional and deterministic (memory content hash goes into the run fingerprint if used).
- Store hypotheses, versions, validation reports, trial-ledger context, per-regime results, **negative results**, post-mortems (`trust=agent_proposed` until verified against evidence — `Memory` rejects `trust=model_output`; every claim cites run/evidence IDs).
- Retrieval via existing `HybridRetriever`/Knowledge V2 + structured filters (asset class, timeframe, regime, DSR, drawdown, state, family); similarity by return-stream correlation (duplicates are not diversification). Admission through `VerifiedExperience` (no unverified learning, no auto-promote). Curator dedupes/archives append-only. Portfolio view: OOS correlation matrix and marginal contribution.
- Capabilities: `library.search|similar|lineage|lessons`.

## Phase T8 — Agent Factory (D17)
Build on **`AgentFleetService` + `AgentRuntime` + `MultiAgentCoordinator.run_dag` + `AgentBlackboard` + Cognitive Runtime** (no second stack). The fleet's `launch_mission` currently maps everything to `GENERIC`; add a **trading executor** so roles in `roles.py` do real work:
- Each role = structured LLM call (via the Model Control Plane/`cognition.model_adapter`) with **schema-validated JSON I/O**, bounded prompts (local LM Studio models are slow/non-deterministic), retries with repair, prompts/outputs stored as artifacts. LLM proposes hypotheses, drafts specs, critiques, explains — it never computes fills/PnL/statistics and is never in the per-bar loop.
- Roles: Orchestrator, Data Steward, Hypothesis Researcher (queries Library first), Strategy Engineer (static validation + causality guard), Backtester (kernel via jobs), Risk Manager (binding veto), Skeptic/Validator (adversarial: robustness, random-entry baseline, leak hunting; its FAIL findings are evidence and cannot be deleted), Portfolio Constructor (OOS streams only), Paper Trader, Post-mortem Analyst, Curator.
- **`ResearchCampaign`** (durable, resumable, cancelable): goal, universe, dataset_version, split manifest, `ResearchBudget` (max trials, compute-seconds, LLM tokens, wall-clock), constraints. Search operators beyond LLM whim: grid/random/Bayesian sweeps and mutation/crossover on specs — every candidate recorded in the trial ledger and creates a new immutable version with lineage.
- Restart-safe (idempotency keys via Gateway; fix that fleet reconcile marks active missions `INTERRUPTED` — campaigns need their own resumable state, not synchronous missions).
- Reports: every numeric claim carries a run/evidence ID or is flagged `UNVERIFIED`.
- Neuro/Brain stays advisory (`brain_hooks` retrieval must not change decisions except through explicit, ledgered features).

## Phase T9 — Autonomous Paper Trading + Risk Engine v2 + Broker abstraction (D18)
- `PaperForwardRunner` (job): consumes `MarketDataFeed` (live provider or accelerated replay), runs the *same kernel/fill model*, submits intents through `BrokerAdapter`. Persistent paper wallets **per session** (fix shared/reset bug), idempotent client order ids, checkpoint/resume, reconciliation vs an independently recomputed shadow ledger (mismatch ⇒ halt), data-quality watchdog (stale/gap/spike ⇒ pause), drift dashboard (forward vs backtest bands; fill-realism vs quote data).
- **Risk Engine v2** (Core-owned; agents cannot bypass): pre-trade checks on **every** order path including manual paper orders (max position/notional/gross/net/leverage/concentration, % of volume, fat-finger price sanity, order-rate, duplicates, sessions, restricted list); continuous breakers (daily loss, DD from high-water mark, consecutive losses, vol spike, stale data, connectivity); **global + per-strategy kill switch** with human reset; loosening limits is approval-gated; limits in Settings with audit.
- **Autonomy levels** per strategy (default L0): L0 research · L1 paper, human starts/stops · L2 paper autonomous · L3 live, per-order human approval · L4 live within hard risk envelope + daily human review · L5 not implemented. **Build L0–L2 for real; L3–L4 as tested contracts only** (adapter interface, approval flow, envelope, kill switch) with `LiveBroker` still `UNSUPPORTED`.
- Live stays blocked: keep `LiveTradingGuard`/`TradingStub` behavior and 501 default. Enabling any live adapter would additionally require: child flag `LEVIATHAN_FEATURE_TRADING_LIVE` (default false, validated), a venue adapter, `LIVE_ELIGIBLE` strategy with human sign-off, configured envelope, passing live-readiness release gate (Security auditor posture, loopback, secret handling), tamper-evident (hash-chained) audit ledger of intent → risk decision → broker call → fill → reconciliation. None of that is switched on in this program.

## Phase T10 — Frontend
Extend existing pages (`MarktdataPage`, `SimulatiePage`, `StrategieenPage`, `PaperTradingPage`, `PortefeuillePage`, `BrokerTradingPage`, `shared.tsx`, `menu.ts`, `tradingAssets.ts`, `trading*.css`) — do not re-skin. Add tabs/pages for Onderzoek (campaigns, DAG timeline, budget burn, **trial counter + DSR haircut visible**), Validatie (WFA/CPCV/PBO/robustness matrix/sealed status), Bibliotheek, Risico (limits editor, breakers, big kill switch), data quality + split editor (purge/embargo timeline). All numbers show their `MeasurementState`; `UNMEASURED` renders as such, never `0`. Server-side downsampling for large series. Ask before adding a chart library. Types in `types/api.ts`, calls via `api/client.ts`.

## Phase T11 — Exit gate, release gates, docs
`Data/backend/tests/test_wave10_trading_research.py` (style of existing wave gates); release-gate additions (live-readiness checklist; UNMEASURED never promotes); Settings catalog entries + `.env.example`; version bump; docs (`buildplan.md` top entry, `cursor.md`, `market_sim.md`, `trading-center-architecture.md`, `leviathan_system.md`); honest **Explicitly NOT claimed**.

---

# 6. KEY SPECIFICATIONS (reference for the phases)

**Causality.** Strategies see only history ≤ now via a bounded read-only `MarketView`. Default: signal on bar *t* close → earliest fill bar *t+1* open. **Causality Guard** harness: run each strategy on real data and on data where all bars after `now` are replaced by adversarial garbage at every step; decisions must be byte-identical. Mandatory before leaving `DRAFT` and as a CI property test.

**Costs are never zero by accident.** A run with all costs 0 is labeled `COST_MODEL: NONE` and is never promotion-eligible. Record commission, spread (from bid/ask if present else configurable half-spread), volume-participation slippage, borrow/financing, funding, fees.

**Determinism.** No wall-clock, unseeded RNG, dict-order or thread-race effects in the kernel. Every run stores its fingerprint; kill/resume is byte-identical.

**Anti-overfitting.** Trial ledger is global and unbypassable; DSR uses effective independent trials; sealed holdout is single-use; parameters are judged on plateaus, not spikes; random-entry baseline must be beaten with significance.

**Data honesty.** OHLCV ≠ order book: no intra-bar microstructure claims; ambiguous same-bar stop/target resolved pessimistically unless finer data exists (then `AMBIGUOUS` flag); equity data without corporate actions cannot be promotion-grade; survivor-biased universes are capped.

**LLM boundary.** Deterministic core, LLM at the edges. Model output is never evidence. Numeric claims must be reproducible from run/evidence IDs.

---

# 7. PERSISTENCE

One or more **additive** migrations after the *real* head (verify — D21). Extend existing v16/v34 tables where sensible instead of duplicating. Suggested new tables (adapt to conventions after the Gap Report): `market_datasets`, `market_dataset_versions`, `market_quality_reports`, `market_split_manifests`, `market_sealed_access_log`, `market_regime_labels`, `market_corporate_actions`, `market_strategy_lineage`, `market_feature_registry`, `market_run_fingerprints`/run extensions, `market_run_checkpoints`, `market_trades` (round-trip ledger), `market_trial_ledger` (append-only), `market_validation_reports`/`_tests`, `market_promotion_transitions`, `market_campaigns`/`_steps`, `market_library_entries`/`_postmortems`/`_lessons`, `paper_wallets`, `paper_fills`, `paper_reconciliations`, `paper_drift_stats`, `risk_limits`/`risk_events`/`risk_kill_switch_log`, `trading_audit_chain`. Large series → `ArtifactStore` (hash-verified). Append-only tables enforced by triggers or store API; indexes on (strategy_version, dataset_version, run_fingerprint). Migration tests: fresh + upgrade.

---

# 8. API, FLAGS, SETTINGS

- Keep every existing `/api/market-sim/*` route working (compat). Add groups: `/datasets*`, `/quality`, `/splits`, `/validation*`, `/trial-ledger`, `/campaigns*`, `/library/*`, `/promotion/*`, `/risk/*`, `/audit`, `/paper/sessions/{id}/{start,stop,pause,reconcile,drift}`. Do not create a second overlapping trading API.
- Flags under `LEVIATHAN_FEATURE_MARKET_SIM`: `..._TRADING_DATA_PLATFORM`, `..._TRADING_KERNEL_V2`, `..._TRADING_VALIDATION`, `..._TRADING_FACTORY`, `..._TRADING_LIBRARY`, `..._TRADING_PAPER_FORWARD`, `..._TRADING_RISK_V2`, `..._TRADING_LIVE` (default false; refuses to enable without risk v2 + paper forward + explicit acknowledgement setting). Move `LEVIATHAN_LIVE_TRADING_UNLOCK`/`LEVIATHAN_LIVE_BROKER_ADAPTER`/Alpaca env reads into Settings + SecretsBroker (D19).
- Settings Control Plane entries for min trades, min OOS length, DSR/PBO cutoffs, robustness criteria, cost defaults, risk limits, autonomy defaults, campaign budgets (secret redaction, hot vs restart-required, audit).
- Extend `/status` with real trading posture: dataset quality, active campaigns, trial-ledger size, paper sessions, risk/kill-switch state, live flag state.

---

# 9. TEST STRATEGY

`test_wave10_trading_research.py` + per-subsystem suites. Minimum:

- **Characterization:** one test per D-item (T0), turned green by the fixing phase.
- **Kernel correctness:** hand-computed golden fills/PnL for every order type + cost model; property-based accounting invariants; margin/liquidation; partial fills/TIF; same-bar stop/target policy; corporate-action adjustment; timezone/DST/session; long/short round-trips.
- **Causality:** poison-future test for every built-in strategy and feature; feature lookback tests; split purge/embargo leakage tests.
- **Determinism:** same fingerprint ⇒ byte-identical; kill/resume ⇒ identical; job retry ⇒ no duplicate fills.
- **Statistics:** known-answer tests for Sharpe/Sortino/PSR/DSR/PBO against reference values; seeded bootstrap sanity; **ledger-bypass impossibility** (monkeypatch all run entry points and assert a ledger row exists).
- **Sandbox/security:** escape attempts (imports, file/network, dunder, infinite loop, memory bomb, frame inspection, future-data access) fail closed; secrets never in `public_dict`/logs/prompts.
- **Promotion:** cannot skip states; missing evidence blocks; agents cannot reach `LIVE_ELIGIBLE`; sealed single-use; rollback; Risk veto binding; caller-supplied metrics rejected (D11).
- **Library/learning:** evidence-linked retrieval; `trust=model_output` rejected as truth; append-only archive; negative results retrievable; memory hydration respects `available_at`.
- **Agents:** end-to-end campaign with a fake deterministic LLM queue (hypothesis → version → screen → validate → verdict → library); restart mid-campaign resumes without duplicate side effects; budgets enforced; no un-ledgered trials.
- **Paper/risk:** reconciliation mismatch halts; stale feed pauses; every limit triggers; global kill switch under injected failure (Chaos helpers exist, default OFF); per-session wallet isolation (D18); autonomy policy enforcement; live adapter refuses and `TradingStub` still returns 501; flag validation for `TRADING_LIVE`.
- **Ingest:** duplicates, gaps, `YYYYMMDD`, epoch s/ms/µs, tz/DST, malformed rows, multi-symbol files, hash mismatch at run start.
- **Migrations:** fresh + upgrade; append-only enforcement; fix/replace stale `test_migrations` expectation (D21).
- **Performance benchmarks** recorded (bars/sec, memory) — not asserted tightly.
- **Frontend:** typecheck/lint/vitest/build + API-client contract tests.

Live LLM, live market feed, live broker paths are **NOT TESTED** in CI and must be documented as such.

---

# 10. QUALITY BAR & ANTI-PATTERNS

Reject: zero-cost or same-close-fill demos · optimizing on the whole dataset then reporting it · touching the sealed set more than once · LLM-computed metrics · any run path that skips the trial ledger · silent defaults that flatter results · survivor-biased data labeled validated · a second registry/DB/gateway/job-queue/agent stack · fake fills/progress/equity/mock UI numbers · live trading enabled by default, by an agent, or without human sign-off · undeclared dependencies · bulk market data committed to git (belongs under `LEVIATHAN_MARKETS_ROOT`) · claiming anything that wasn't run (`NOT TESTED` is an acceptable honest status).

**Explicitly NOT claimed by this program** (repeat and adjust in `buildplan.md`): profitability of any strategy; production-grade live execution or any live venue integration; L5 autonomy; microstructure realism without L2/L3 data; options/futures/forex support unless separately built and proven; tax/legal compliance; investment advice.

---

# 11. DEFINITION OF DONE (per phase)

Documented contract → implementation integrated into the real runtime → focused tests (incl. the characterization tests for its D-items) → truthful failure states → updated docs → full suites green with pasted real counts → honest limitations list.

---

# 12. IMPORTANT WORKING RULES FOR CURSOR

1. Read `buildplan.md` (top), `leviathan_system.md`, `cursor.md`, `market_sim.md`, `trading-center-architecture.md`, then the owning code, before editing.
2. Extend existing modules; prefer small compat-preserving changes; never delete legacy engines/routes without explicit approval.
3. Write the failing test first for every defect; show it failing; then fix.
4. Commit per logical step; keep PRs reviewable.
5. Ask before adding dependencies, chart libraries, or new top-level packages.
6. Never weaken `LiveTradingGuard`, `RiskGuard` override-key blocking, or any `truth` flag.

---

# 13. QUICK REFERENCE — IDs

D1 annualization · D2 win-rate/PF UNMEASURED · D3 orders/day never reset · D4 tiny default sizing · D5 dual fill models/partials · D6 restart-unsafe + soft lease · D7 data hash unchecked · D8 persistence/memory hot path · D9 ingestion shallow · D10 clock.bars public · D11 caller-supplied metrics · D12 acceptance/metric key mismatch · D13 WFA never executed · D14 trial ledger not global · D15 memory disconnected · D16 Gateway bypass · D17 agents not LLM/campaign-less · D18 paper manual/shared wallet reset · D19 secrets/network bypass · D20 instrument/order-type/demo gaps · D21 migration head drift.

---

# 14. KICKOFF LINES

**Start:**
> Read `Data/docs/trading_program.md` fully. Execute **Phase T0 only**: read all files listed as "not read yet", write characterization tests proving or refuting D1–D21, and produce `Data/docs/trading_gap_report.md`. No feature code. Summarize the report and wait for my approval.

**Per phase:**
> Execute **Phase T{n}** from `Data/docs/trading_program.md`. Re-read sections 1, 3 (relevant D-items), 10 and the phase text first. Extend existing modules — no parallel stacks. Failing tests first. Ship migrations, tests, docs and the `buildplan.md` entry. Run the full backend and frontend suites and paste real results. Report known limitations honestly, then stop.

**Skeptic pass (after T1, T4, T8, T9):**
> Act as the Skeptic. Try to break Phase T{n}: look-ahead paths, trial-ledger bypasses, sandbox escapes, promotion shortcuts, cost-free defaults, nondeterminism, restart/resume divergence, places where model text could be treated as evidence, and any order path that skips the Risk Engine. Write failing tests first, then fix.

*End of prompt.*


---

**Operator note (this workspace):** Market data files are operator-supplied under `LEVIATHAN_MARKETS_ROOT` / markets root. Agents must not commit bulk OHLCV into git.
