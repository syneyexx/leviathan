LEVIATHAN TRADING CENTER → 100%  (Master Program v4, expanded + current-system integrated)

Save this file as `Data/docs/trading_program.md` and reference it with `@` in Cursor. This v4 supersedes earlier trading prompts where they conflict. Execute one named phase/subphase per session using Part K. Do not compress multiple subphases into one session merely to finish faster.

**Scope:** take `Data/modules/market_sim` (Trading Center) from "impressive research prototype" to a complete, verifiable, end-state product: a deterministic market simulator + strategy research factory + agent training gym + evidence-gated promotion + autonomous paper trading + a live-ready-but-blocked execution architecture.

**Audience:** Cursor (Agent mode), working in `syneyexx/leviathan` on Windows (`installer.bat` / `run_leviathan.bat` exist — no fork-based multiprocessing, no POSIX-only resource limits without a fallback).

**Basis:** this prompt is written after reading the actual source of `market_sim/*` (types, engine, multi_engine, execution, fill_model, accounting, portfolio, risk_guard, metrics, experiments, strategy_eval, service, store, ohlcv, data_store, worker, roles, deliberation, commit_reveal, brain_hooks, instruments, capabilities, paper_broker, providers, live guard), `trading/stub.py`, `routes/market_sim.py`, `agents/fleet.py`, `jobs/runtime.py`, `execution/types.py`, `scripts/market_sim_worker.py`, `SimulatiePage.tsx`, `PaperTradingPage.tsx`, `test_market_sim.py`, `test_trading_center.py`, `test_migrations.py`, and the docs. Where code and docs disagree, code and tests win.

# PART A — HOW THIS PROGRAM RUNS (read first, obey always)

## A1. What "100%" means here (and what it does not)

"100%" = every gate in Part B passes on a clean checkout, verified by a script, with real evidence — not "the agent says it's done". It does not mean "profitable": no strategy is guaranteed to make money and most candidates fail out-of-sample. The deliverable is a machine that:

- (a) simulates honestly
- (b) rejects false discoveries reliably
- (c) lets agents train and be measured under realistic conditions
- (d) records everything
- (e) promotes only on evidence
- (f) refuses to touch real money without human-controlled gates

## A2. Program Runner protocol (this is how you avoid half work)

1. **State file.** Create/maintain `Data/docs/trading_program_state.md`: table of all gates (G01…G50 and G51…G60) with `NOT_STARTED | IN_PROGRESS | PASS | FAIL | NOT_TESTED`, evidence (test node ids / command / date), plus an append-only session log. Read it first in every session. Never mark PASS without evidence you actually ran.

2. **Verification harness.** Create `scripts/verify_trading_100.py` + `Data/backend/tests/trading_gates.json` (gate → verification commands/test node ids/checks; JSON, no new deps). Running it prints a gate table, writes `Data/docs/trading_completion_report.json`, and exits non-zero unless every gate is PASS (a gate that requires an external live service is not allowed — every gate must be verifiable offline; live LLM/feed/broker paths are listed separately as `NOT_TESTED_IN_CI`, never as PASS).

3. **Loop per implementation phase:** read → convert the relevant passing characterization into the desired failing regression → prove it fails → implement → run targeted tests → run impacted/full suites → Skeptic pass (try to break it; add a failing regression before fixing) → docs → commit → update state file → stop and report. T0 itself leaves the tree green: T0 characterization tests PASS while documenting the current defective behavior; the fixing phase later inverts/replaces the assertion before implementation.

4. **No shortcuts**, enforced by grep-able rules (the harness checks these only in trading-owned files and shared files changed by this program, not unrelated legacy debt elsewhere):

- no unresolved TODO/FIXME/pass-only bodies/NotImplementedError in delivered trading code except explicitly documented UNSUPPORTED live adapters/protocol abstractions
- no @skip/xfail without written gate justification
- no mocks of the kernel in kernel correctness tests
- no hard-coded metric/fill/progress values
- no production mock UI data
- no fixture files >2 MB committed (generate synthetic data deterministically instead)

5. **Never claim what you did not run.** `NOT_TESTED` is an honest status; a false PASS is a failed task.

6. **Session size discipline.** One phase per session (phases are sized for that). If a phase can't finish, leave the state file accurate and green tests — never a half-migrated tree.

7. **Compatibility.** Existing routes, tables and UI keep working. Legacy engines stay selectable (`engine: legacy`) until Kernel v2 parity is proven; deleting anything requires explicit approval.

## A3. Completion Report

At the end, produce `Data/docs/trading_completion_report.md` (generated from the JSON): per gate → status, evidence, known limitations; a section Explicitly NOT claimed; and the measured numbers (throughput, memory, test counts). A gate table with any non-PASS means the program is not complete.

# PART A.5 — V4 CURRENT-SYSTEM DELTA (verify again before editing)

This v4 adds several current-repository integration constraints on top of the original source audit. Re-read the files; current code always wins.

## Current TradingCenter frontend

`Data/frontend/src/App.tsx` currently exposes these real routes:

- `/trading/simulatie`
- `/trading/strategieen`
- `/trading/marktdata`
- `/trading/portefeuille`
- `/trading/paper`
- `/trading/broker`

`Data/frontend/src/navigation/menu.ts` already owns the TradingCenter navigation. Extend this navigation; do not create another Trading shell/router/menu.

## Current frontend reality to preserve and then complete

- **SimulatiePage.tsx** already talks to real APIs, but its new-run action currently constructs a hard-coded multi-agent run (fixed agents, seed/cadence/game metadata) and the visualization/configuration surface is far below the target kernel capability.
- **StrategieenPage.tsx** persists real strategies but currently supports only the existing two DSL kinds; its visual builder explicitly says it is illustrative. Any final "visual builder" must either compile/round-trip to Strategy Spec v2 or remain clearly read-only.
- **MarktdataPage.tsx** scans/registers actual files but needs the full versioned quality/quarantine/splits/provider-job platform; heavy scanning/import must become a durable external job rather than long API work.
- **PaperTradingPage.tsx** currently provides manual BUY/SELL tickets and polling. It must evolve into the persistent autonomous PaperForwardRunner console; the manual ticket remains but goes through the same Risk Engine.
- **PortefeuillePage.tsx** and **BrokerTradingPage.tsx** stay in the same TradingCenter and must bind only to canonical backend truth.

## Current worker plane

The canonical worker catalog already contains:

- `pool_id="market_sim"`
- entrypoint `Data.modules.workers.entrypoints.market_sim`
- job ownership prefix `market_sim.`
- resource class `CPU_HEAVY`

It also already contains provider I/O, dataset, source-ingestion, research, agents, knowledge, embedding, rerank, evaluation, training, backup and maintenance pools.

Therefore this program MUST NOT invent a second trading queue, second lease model or second worker supervisor. If `scripts/market_sim_worker.py` remains, make it a compatibility launcher/shim into the canonical Worker Supervisor/JobRuntime path rather than a competing worker implementation.

## Current backend route shape

`Data/backend/routes/market_sim.py` currently exposes real data/strategy/run/provider/paper/experiment routes and directly calls `MarketSimControlPlane` for many mutations. Preserve compatible route semantics, but route side effects through the canonical Gateway/Job authority path as the relevant phases land.

## Harmony requirement

Trading must integrate with the wider LEVIATHAN system rather than become a product inside the product:

- long trading work → existing Jobs/Workers and, where supported, Tasks projection
- trading role execution → existing Agent Fleet/Cognition
- training trajectories → existing Datasets/Training
- verified results → existing Evidence infrastructure
- strategy lessons/knowledge → existing Knowledge/Memory with point-in-time rules
- schedules → existing Schedules
- orchestration → existing Workflows
- configuration → existing Settings Control Plane
- secrets → existing SecretsBroker
- side effects → existing ExecutionGateway/Approval/Policy
- large time series/artifacts → existing ArtifactStore
- operational metrics → existing Observability/Status/Analytics patterns

# PART B — DEFINITION OF 100%: THE GATES

Each gate is binary and offline-verifiable.

## Data & providers

- **G01** Streaming ingest of a synthetic 5-year × 1-minute crypto series (~2.6 M bars) and a 6-year daily multi-symbol equity set completes within a documented memory budget; peak memory measured and recorded; no full-file `list[Bar]` on the hot path.
- **G02** Timestamp parser: ISO with/without tz, epoch s/ms/µs, YYYYMMDD, exchange-local time with DST — each covered by tests; malformed rows are quarantined with reasons (never silently dropped, never fatal for the whole file).
- **G03** Quality report (persisted, per dataset): duplicates, ordering, gaps vs calendar, OHLC consistency, non-positive prices, zero-volume runs, outlier returns, stale runs, split-like jumps, DST/timezone anomalies → `PASSED`/`WARN`/`FAILED`/`UNMEASURED`; `FAILED` blocks promotion-grade use.
- **G04** Corporate actions (splits, dividends, delistings) stored separately; point-in-time adjustment; missing data ⇒ `ADJUSTMENT: UNMEASURED` and dataset capped below promotion-grade.
- **G05** Datasets/versions immutable (content-addressed). A run refuses to start if the dataset hash differs; provider imports create a new version instead of overwriting a file.
- **G06** Split manifests (`TRAIN`/`VALIDATION`/`SEALED_TEST`) with purge + embargo; sealed range is write-once; every sealed evaluation logged; second evaluation of the same `(strategy_version, dataset_version)` is refused.
- **G07** Providers: paginated historical fetch beyond 1 000 bars, rate-limit/backoff/retry, outbound calls through network policy (no raw urllib in adapters), adjustment status of each provider labeled, no file overwrite.

## Kernel

- **G08** Kernel v2 golden suite: hand-computed fills/PnL for `MARKET`/`LIMIT`/`STOP`/`STOP_LIMIT`, TIF, bracket/OCO, gaps through stops, partial fills, long and short, fees/spread/slippage/borrow/funding.
- **G09** Accounting invariants (property-based, many random order streams): equity == cash + Σ position×mark; realized+unrealized reconcile; fees ≥ 0; no negative cash unless margin enabled and within limits.
- **G10** Instrument rules enforced: tick/lot rounding, min-notional, fractional-share flag, shortability, currency; unknown instrument class ⇒ refusal, not "equity by default".
- **G11** Determinism: same run fingerprint ⇒ byte-identical trade log + equity; kill/resume mid-run ⇒ identical; identical across two OS processes.
- **G12** Causality: bounded MarketView (no path to future bars); poison-future test passes for every built-in strategy, feature and the kernel.
- **G13** Measured throughput (bars/sec) and memory recorded per run; the 5-year 1m single-symbol run finishes without OOM on the reference budget.
- **G14** Parity report: Kernel v2 reproduces legacy engine results on the repo fixtures within stated tolerance, or each difference is documented and tested.

## Strategy system

- **G15** Strategy Spec v2: superset of the current DSL (old strategies still run identically), indicator/feature library with declared lookbacks (each with a no-look-ahead test), stops/targets/trailing, sizing models, rebalancing, universe.
- **G16** Code strategies only in a sandbox (AST allow-list + subprocess + limits); escape suite (imports, file/network, dunder tricks, infinite loop, memory bomb, frame inspection, future-data access) fails closed; requested vs effective isolation reported truthfully on Windows.
- **G17** Immutable strategy versions with lineage (parent, proposer, rationale); a written hypothesis is required to leave `DRAFT`.

## Validation & statistics

- **G18** Metrics v2 computed only from the run ledger; known-answer tests; per-year and per-regime breakdown; bootstrap CIs; min-sample ⇒ `UNMEASURED`.
- **G19** Global append-only Trial Ledger written by the kernel entry point (bypass impossible — proven by a test that patches every run path); PSR/DSR/PBO known-answer tests.
- **G20** Platform executes rolling+anchored walk-forward, purged K-fold, CPCV, and the robustness suite (parameter plateau, cost ×1.5/×2/×3, execution-delay, data perturbation, start-shift, regime split, cross-asset, trade Monte Carlo, random-entry baseline).
- **G21** Acceptance verdicts are derived by the platform from run IDs; caller-supplied metrics are rejected/flagged `UNVERIFIED`; sealed holdout single-use enforced.
- **G46** False-discovery calibration: on N pure-noise synthetic datasets the whole pipeline (screen → validate → sealed) promotes ≤ the configured false-discovery rate; on datasets with a planted momentum/mean-reversion edge it finds and promotes it with power ≥ configured threshold. Seeds fixed; thresholds in Settings.

## Library & learning

- **G22** Strategy Library: persist/recall/similar/lineage/lessons with evidence links; negative results retrievable; in-engine memory hydrated from DB with `available_at` causality; post-mortems stored `trust=agent_proposed` until verified.
- **G23** Brain/Knowledge/Memory retrieval inside backtests is either time-filtered (`as_of`) or excluded by default and labeled; doc claim and code behavior match (test).

## Agents, orchestration & training gym

- **G24** Every trading role has a real executor on the Agent Fleet (schema-validated JSON I/O, bounded prompts, retry-with-repair, artifacts of prompts/outputs); an end-to-end research campaign runs with a deterministic fake-LLM queue.
- **G25** ResearchCampaign durable, resumable, cancelable, budgeted (trials/compute/tokens/wall-clock); restart mid-campaign resumes without duplicate side effects.
- **G26** TradingGym: deterministic, causal reset/step environment with curriculum stages, domain randomization (costs/latency/spread), episode ledger; cannot read SEALED windows.
- **G27** Agent scorecards per agent-version × regime × year with CIs, violation counts (risk rejections, override attempts, causality attempts), token/latency cost; leaderboard with multiple-testing penalty.
- **G28** Agent readiness ladder A0…A4 enforced by policy (gym → validation → sealed once → shadow paper → autonomous paper); A5 (live) blocked.
- **G29** Trajectory export → preference pairs / SFT datasets through the existing Datasets/Training pipeline; verified outcomes only; contamination scan against sealed windows.
- **G30** Sim-to-real gap report (paper-forward vs simulator: fill price, missed fills, slippage, latency); cost-model calibration uses data disjoint from evaluation data.

## Promotion

- **G31** Promotion state machine enforced; `UNMEASURED` blocks; only a human can enter `LIVE_ELIGIBLE`; demotion; decay monitor auto-suspends; champion/challenger shadow.

## Paper / risk / broker

- **G32** PaperForwardRunner: autonomous strategy→orders loop; persistent per-session wallets; restart/resume; idempotent client order ids.
- **G33** Reconciliation vs an independent shadow ledger; drift-vs-backtest bands; data-quality watchdog pauses/halts.
- **G34** Risk Engine v2 on every order path (incl. manual); continuous breakers; global + per-strategy kill switch with human reset; loosening limits approval-gated.
- **G35** BrokerAdapter protocol; persistent PaperBroker; ReplayBroker; Alpaca-paper via SecretsBroker; LiveBroker = honest `UNSUPPORTED`; TradingStub/LiveTradingGuard still refuse (501) by default; autonomy L0–L2 real, L3–L4 contract-tested.
- **G36** Hash-chained audit ledger (intent → risk decision → broker call → fill → reconciliation); tamper test detects modification.

## Infrastructure

- **G37** Trading operations are registered CapabilityCatalog capabilities and executed through the Gateway (approvals/receipts/effect ledger); routes no longer call side-effecting service methods directly.
- **G38** Runs execute as durable jobs (`market_sim.advance` on the JobStore lease path) with heartbeat/expiry/recovery; two workers can never double-claim (tested); a hard-crashed run is recovered.
- **G39** Persistence hot path: batched transactional writes, O(n) metrics, paginated + downsampled series; migrations fresh + upgrade; ledger tables append-only.
- **G40** Settings Control Plane + feature flags + `.env.example`; secrets/env reads only via SecretsBroker; nothing sensitive in logs/prompts/`public_dict`.

## Frontend

- **G41** All Trading Center pages bind to real backend data (no mock numbers); `UNMEASURED` renders as such; "latest N" and downsampling are correct (no stale/truncated live views); typecheck/lint/test/build green.
- **G42** Run configuration UI exposes every kernel option (dates, capital, costs, sizing, fill policy, delay, instruments, engine); run comparison view; trades/equity/drawdown/exposure charts with axes.

## Ops & docs

- **G43** `test_wave10_trading_research.py` + `scripts/verify_trading_100.py` exit 0; CI workflow + release gates updated; version bumped; all docs updated (`buildplan.md` top entry, `cursor.md`, `market_sim.md`, `trading-center-architecture.md`, `leviathan_system.md`).
- **G44** Completion Report generated with evidence per gate and an honest Explicitly NOT claimed.
- **G45** Every characterization test written in T0 (defects D1–D31) is converted into a passing regression test.
- **G47** Windows: workers, sandbox and job paths tested/documented for Windows (spawn semantics, path handling, no POSIX-only assumptions).
- **G48** Security posture: live flag off by default, `TRADING_LIVE` validation rules, Security auditor posture check includes trading, no secret in repo.
- **G49** Observability: run/campaign/paper/risk events emitted to Observability with `category=trading`; `/api/status` shows real trading posture.
- **G50** Backup/restore covers trading tables + artifacts (round-trip test).

## V4 additional gates — G51…G60

These are required in addition to G01…G50.

- **G51** Interactive-priority isolation: while a large import, simulation, research campaign, validation batch, gym batch or evaluation job is running externally, normal LEVIATHAN API/chat remains responsive within a documented operational envelope. Background resource admission cannot silently starve interactive model inference.
- **G52** Mutation idempotency: retry-prone trading mutations (run start, campaign start, validation launch, paper runner start, paper order submit, promotion) use idempotency keys or a durable natural identity. Double-click/retry cannot create unintended duplicate jobs/orders/transitions.
- **G53** Full provenance fingerprint: every promotion-grade result links dataset version + split manifest + strategy version + kernel version + configuration hash + cost model + seed + code/version fingerprint + agent/model version when applicable. Incomplete provenance ⇒ not promotion-grade.
- **G54** Disaster recovery: backup/restore into a clean temporary environment reproduces strategy/run/promotion/library/campaign/gym/paper/risk metadata and verifies referenced artifacts without relying on the original machine's absolute paths.
- **G55** Data provenance/licensing state: every dataset/provider version records source/provider, import time, known/unknown licensing/terms metadata, adjustment state and operator provenance. Unknown remains `UNKNOWN`; never invent licence or survivorship quality.
- **G56** Unified time semantics: canonical UTC persistence, explicit exchange timezone, explicit bar-open/bar-close convention, DST/session semantics and explicit frontend display timezone. No silent reinterpretation.
- **G57** Frontend action matrix: every visible TradingCenter button/menu/tab/input is functional, intentionally read-only with an explanation, or removed. A checked action matrix is required; decorative controls cannot satisfy this gate.
- **G58** Operational telemetry: queue wait, worker heartbeat age, run-advance latency, provider latency, bars/sec, paper-loop lag, feed staleness, DB latency and reconciliation lag are measured or explicitly `UNMEASURED`; no fake SLO PASS.
- **G59** Typed frontend contracts: stable trading API objects are strongly typed in `types/api.ts`; production pages do not use broad `Record<string, unknown>` where a real backend schema exists. Client contract tests detect drift.
- **G60** Compatibility/migration posture: every schema/API phase proves fresh migration + upgrade migration; current public routes remain compatible or fail explicitly with a documented migration. Irreversible data-shape changes document rollback/recovery strategy.

# PART C — NON-NEGOTIABLE LEVIATHAN INVARIANTS

```
model output != evidence         request != authority          capability != authority
dispatch != completion           unmeasured != passed          registered != trained
neural / LLM signal != authority backtest != proven strategy   paper profit != live readiness
OHLCV != order book              training reward != skill       gym score != real-world edge
```

- **Python first.** One infrastructure path: side effects through ExecutionGateway + CapabilityCatalog (`CapabilityDefinition`: id, name, description, side_effects, provider_kind, provider_ref, input/output schema, required_permissions, metadata) + ApprovalService/PolicyEngine; long work through JobRuntime/JobStore leases; secrets through SecretsBroker; agents through AgentFleetService/AgentRuntime/MultiAgentCoordinator/Cognitive Runtime; models through the Model Control Plane. No second job queue, secret store, agent stack, DB, model client.
- **One SQLite** via MigrationRunner (contiguous versions) + ArtifactStore for large series. `main.py` stays a composition root.
- **Truthful failure:** `UNAVAILABLE`/`UNMEASURED`/HTTP 409/501; never fabricated fills, metrics or success. Keep every existing truth block honest.
- **Feature flags** hierarchical, risky ones default OFF. Optional deps (numpy, pyarrow, scipy, numba, exchange_calendars) only in `requirements-trading.txt`, capability-detected; the stdlib path must stay correct. Ask before adding anything else.
- Do not read/import/depend on `Data/HADES` or editor folders.
- UI labels Dutch; code/comments/identifiers/docs English; API bodies camelCase (existing convention).
- Tests + docs are part of every phase; full backend suite and frontend typecheck/lint/test/build green at the end of every phase.

## C.1 Sole-ownership matrix

No phase may introduce a second authoritative owner for these concerns:


| Concern | Sole authority |
|---|---|
| Market clock / causality | Trading Kernel |
| Orders / fills / positions / PnL | Trading Kernel |
| Execution-cost truth | Kernel execution model |
| Trading risk decision | Risk Engine v2 |
| External side-effect authority | ExecutionGateway + Policy/Approvals |
| Long-running work | JobRuntime / JobStore |
| Worker process ownership | existing Worker Supervisor/Registry |
| Trading job pool | existing market_sim worker pool |
| Model calls | Model Control Plane |
| Agent execution | AgentFleet / AgentRuntime / Cognitive Runtime |
| Secrets | SecretsBroker |
| User/system configuration | Settings Control Plane |
| Metadata persistence | central SQLite + MigrationRunner |
| Large series/artifacts | ArtifactStore |
| Knowledge/memory | existing Knowledge/Memory systems |
| Verified trading evidence | trial/validation ledgers + Evidence infrastructure |
| Strategy promotion | Promotion state machine + human gates |
| Scheduling | existing Schedules |
| Orchestration | existing Workflows |
| Frontend HTTP client | `Data/frontend/src/api/client.ts` |
| Frontend contracts | `Data/frontend/src/types/api.ts` |
| Navigation/routes | existing `App.tsx` + `navigation/menu.ts` |

If a proposed class/service duplicates one of these owners, integrate instead.

## C.2 Performance-budget freeze

T0 creates and freezes before optimization:

- `Data/docs/trading_reference_hardware.json`
- `Data/docs/trading_performance_budget.json`

Record OS, Python, CPU/logical cores, RAM, GPU/VRAM if available, storage class where measurable, SQLite version and optional dependency availability.

Freeze benchmark sizes and hard memory/OOM/algorithmic budgets before feature optimization. The operator may change a budget later, but the state log must record it and affected performance gates reset to `NOT_TESTED`. Cursor may not loosen a threshold after seeing a failure simply to declare PASS.

Wall-clock throughput is measured/reportable and should not be overly brittle in CI. Memory/OOM, bounded-materialization and complexity invariants can be hard gates.

## C.3 Sandbox honesty

A Python subprocess + AST allow-list is not automatically a hard security sandbox.

Expose and persist:

- `requestedIsolation`
- `effectiveIsolation` = `HARD` | `RESTRICTED` | `DEGRADED` | `UNAVAILABLE`
- `untrustedCodeAllowed`

Windows Job Objects/resource controls may provide process/resource boundaries but do not alone prove filesystem/network isolation. Escape-suite PASS is evidence, not proof. Arbitrary untrusted Python is refused whenever the configured required isolation cannot actually be enforced.

## C.4 Phase-owned schema only

Part G is a logical target model. Do not create every listed table in one migration wave. A table is introduced only in the first phase that owns a real persistent invariant, with fresh + upgrade migration tests and immediately-used store/service code.

# PART D — VERIFIED ANALYSIS OF THE CURRENT SIMULATOR

## D.1 What exists (verified in source)

| Area | Where | Reality today |
|---|---|---|
| Control plane | `service.py` MarketSimControlPlane | Data scan/register, strategy CRUD/versions/fork/archive, run lifecycle, provider import, paper sessions, experiments, demos. Flag `LEVIATHAN_FEATURE_MARKET_SIM`. |
| Legacy engine | `engine.py`, `portfolio.py`, `fill_model.py` | Single instrument, long-only, float accounting, next-bar-open fills, optional deliberation round. Fill model: flat bps + participation-scaled slippage; no partials, no volume cap. |
| Multi engine | `multi_engine.py`, `accounting.py`, `execution.py`, `risk_guard.py`, `commit_reveal.py` | Per-agent Decimal wallets, commit-then-reveal, NextBarFillModel (participation cap → partial fills, remainder dropped), RiskGuard. Long-only, one instrument. |
| Clock | `causality.py` | SimulationClock: `observe()`/`window()`/`closes()` refuse look-ahead; `bars` is a public attribute. |
| Strategy | `strategy_eval.py` | DSL with exactly two kinds: `ma_cross`, `mean_reversion`. Content hash over params/rules. |
| Strategy store | `store.py`, `types.py` | `market_strategies` + immutable `market_strategy_versions`; status only `DRAFT`/`ACTIVE`/`ARCHIVED`; no lineage columns. |
| Metrics | `metrics.py` | total return, Sharpe, Sortino, max DD, turnover, fees, buy&hold, `MEASURED`/`UNMEASURED`. |
| Experiments | `experiments.py` + `service.propose`/`complete_experiment` | Hypothesis ledger (fingerprint, retained rejects), one chronological split, acceptance helper, causal StrategyMemoryIndex. |
| Data | `ohlcv.py`, `data_store.py`, `providers/` | CSV/Parquet(optional) → full `list[Bar]`; whole-file validation; symbol/timeframe from filename. Providers: `csv_local`, `binance_public`, `stooq_public` (raw urllib). |
| Instruments | `instruments.py` | InstrumentSpec (tick, lot, min_notional, timezone, supports_short) exists — not used by any fill/accounting/risk code. |
| Worker | `worker.py`, `scripts/market_sim_worker.py` | Daemon thread or subprocess; 50-bar slices; soft lease `worker_pid=1`. Not on JobRuntime. |
| Paper | `paper_broker.py`, `service.paper_*` | LocalPaperBroker (in-memory WalletLedger), AlpacaPaperBroker (paper endpoint), manual orders only, per-session kill switch. |
| Live guard | `trading_live_guard.py`, `trading/stub.py` | Real orders always refused (501). Keep. |
| Roles / agents | `roles.py`, `deliberation.py`, `agents/fleet.py` | Role specs registered in the Fleet; "agents" in the sim are the same DSL with tweaks; risk veto is rule-based; Fleet missions run synchronously and are marked INTERRUPTED after restart. No LLM anywhere in the trading loop. |
| API | `routes/market_sim.py` | `/api/market-sim/{status,health,data*,strategies*,runs*,providers*,capabilities,paper/*,experiments*,demos/run,live-trading}`; routes call the service directly. |
| Jobs | `jobs/runtime.py` | Durable jobs with leases/heartbeats/retry; `EXTERNAL_WORKER_CAPABILITIES` already reserves `market_sim.advance`, `provider.market.fetch`, `provider.alpaca.paper` for external workers — the intended integration path. |
| Frontend | SimulatiePage, PaperTradingPage, MarktdataPage, StrategieenPage, PortefeuillePage, BrokerTradingPage | Wired to real APIs (good), but see D27. |
| Tests | `test_market_sim.py`, `test_trading_center.py` | Small fixtures; see D28. |

## D.2 Verified defects and gaps

Confidence: read directly in source. Phase T0 must prove or refute each with a characterization test; refuted items are dropped from the Gap Report. IDs are referenced by gates and phases.

### Correctness (fix first)

- **D1 Sharpe/Sortino mis-annualized.** `compute_metrics(..., periods_per_year=252.0)` default is used by both engines' `_finalize_metrics` (neither passes it). Hourly/minute bars get the daily factor. Derive from timeframe + instrument calendar (crypto 24/7 ≠ equity sessions).
- **D2 Win rate / profit factor effectively always UNMEASURED.** `compute_metrics` needs `realized_delta` on fills, but `SimFill.public_dict()` has none (only the legacy fill event payload has it; multi engine has none). No round-trip trade ledger exists.
- **D3 RiskGuard.orders_today never resets.** Multi engine increments it per fill; `max_orders_per_day=50` becomes a lifetime cap in multi-year runs.
- **D4 Sizing leaves strategies nearly uninvested.** With `qty=None`, both `RiskEngine.size_order` and `RiskGuard.evaluate_intent` target `min(cap_qty, risk_qty)` where `risk_qty = equity×per_trade_risk_pct/price` (~1% of equity notional, ≤5% via `risk_qty*5`). `per_trade_risk_pct` is notional, not risk-to-stop.
- **D5 Two divergent fill models.** `fill_model.FillModel` (float, no participation cap) vs `execution.NextBarFillModel` (Decimal, cap). A partially filled intent is marked filled and the remainder silently dropped; costs are flat bps (no spread, volatility scaling, funding, borrow).
- **D6 Resume is not restart-safe.** `_states` cached in memory. On `prepare()` after restart: legacy restores cash/position/realized but not `avg_entry`, `peak_equity`, `pending_intents`, or the equity curve used for metrics; multi engine rebuilds WalletBook from initial cash and sets `clock.index = bar_index-1` (last bar re-processed). A hard crash leaves `worker_pid=1` → run unclaimable forever (no expiry).
- **D7 Data hash not verified at run start.** `SimRun.data_hash` is stored; `prepare()` loads by path without comparing. Provider import overwrites `SYMBOL_TF.csv` in place, so older runs' hashes silently stop matching.
- **D8 Persistence hot path.** A new SQLite connection per bar for equity/fill/event writes; multi engine `_finalize_metrics` reloads up to 100 000 equity rows on every 50-bar slice (O(n²)); `load_ohlcv` builds a full `list[Bar]` (called on scan, prepare, propose_experiment). A 5-year 1-minute series (~2.6 M bars) cannot run.
- **D10 SimulationClock.bars public.** Safe for the DSL; unsafe for future code strategies. `assert_no_future` compares ISO strings lexicographically.
- **D24 InstrumentSpec unused.** No tick/lot rounding, min-notional, shortability, timezone; quantities quantized at 8 decimals (fractional equities); `infer_family` defaults every unknown symbol to equity (forex etc. misclassified).
- **D25 Worker double-claim race.** `claim_next_runnable` does SELECT then UPDATE without `BEGIN IMMEDIATE`; the API daemon thread and `scripts/market_sim_worker.py` can both run. The subprocess plane is built with `from_settings(settings)` without Knowledge/Memory/Neuro, so results/telemetry differ by worker mode.
- **D30 Commit-reveal is weaker than claimed.** `info_version` hashes only the last 64 closes (not the observation set, memories or portfolio); multi_engine pokes `protocol._open = None` privately; risk-agent veto mutates already-committed intents (`d.intent.side = HOLD`) — acceptable only if the original commit is preserved and the override is a separate recorded event.

### Data & providers

- **D9 Ingestion is all-or-nothing and shallow.** One OHLC inconsistency or unsorted row marks the whole file `INVALID` (no quarantine/report); duplicate timestamps pass (only `ts < prev` is checked); no gap/calendar/zero-price/zero-volume/outlier checks; naive timestamps assumed UTC; no adjustments; symbol+timeframe inferred from filename; one symbol per file; every scan reloads and rehashes every file. `_normalize_ts` treats any all-digit string as epoch: an 8-digit YYYYMMDD is mis-dated to 1970, and microsecond epochs are unhandled (verify by test).
- **D23 Providers.** Raw urllib (no network policy); Binance fetch capped at 1 000 bars, no pagination (cannot import multi-year history); no rate limiting/backoff/retry; `fetch_quote` returns last price only (no bid/ask); Stooq adjustment status unknown and unlabeled; CsvLocalProvider takes the first glob match.

### Evidence & statistics

- **D11 Caller-supplied metrics = model output as evidence.** `POST /experiments/{id}/complete` takes arbitrary metrics; `test_trading_center` itself completes an experiment with hand-typed numbers.
- **D12 evaluate_acceptance not wired to real metrics.** It reads `trade_count`, `total_return_pct`, `max_drawdown_pct`, `excess_return_pct`; `compute_metrics` emits `total_return`, `max_drawdown` (fractions, wrapped) and no `trade_count` → real output ⇒ 0 trades, drawdown default 100 ⇒ everything rejected.
- **D13 Walk-forward planned, never executed.** `walk_forward_splits` yields one design/validation/test split that is stored; no runs per window; no rolling/anchored WFA, purge/embargo, CPCV/PBO/DSR, bootstrap CIs, robustness suite, sealed access log.
- **D14 Trial ledger local, not global.** Fingerprint blocks only an identical rejected trial; no global trial count for multiple-testing correction; `market_experiments` is upsert-able (not append-only); `strategy_version` set on completion is not persisted by the upsert.
- **D15 Strategy memory disconnected.** `MultiEngineState.memory` is a fresh empty StrategyMemoryIndex per run, never hydrated from `market_strategy_memories`; not linked to Knowledge V2 / Memory / VerifiedExperience.
- **D22 Brain retrieval is not time-filtered.** Docs claim retrieval is filtered by `available_at ≤ decision time`; `BrainFacade.retrieve` has no `as_of` (only StrategyMemoryIndex filters). Knowledge/Memory content is "now" ⇒ potential leakage into agent context; also one retrieval per agent per round (slow).
- **D29 No per-agent evaluation.** Run-level equity/metrics aggregate wallets; only a leaderboard (equity, realized PnL, fees, trade count) exists — no per-agent Sharpe/drawdown/regime/CI.

### Platform

- **D16 Trading ops bypass the Gateway.** Routes call the service directly; `roles.py` "capabilities" (`market_sim.observe`, …) are labels; `capabilities.build_market_capabilities` is a status matrix (and `crypto_paper` is "AVAILABLE" in both branches of its conditional). No approvals/effect ledger for paper orders.
- **D17 Agents are not agents.** Deliberation/commit "agents" are the same DSL with parameter tweaks; risk veto = BUY & confidence<0.55 → HOLD with constant confidences; Fleet `launch_mission` maps to GENERIC, executes synchronously, and `reconcile()` marks active missions INTERRUPTED after restart. No LLM authoring, no campaign runner.
- **D18 Paper trading is manual and fragile.** Orders only via `POST …/orders`; no strategy→order loop; no RiskGuard in `paper_place_order`; `_paper_brokers[broker_id]` is one in-memory wallet shared by all sessions of that broker and `start_paper_session` resets its cash; wallet lost on restart; kill switch per session only; no reconciliation or drift monitoring; GET session triggers an external quote fetch and a DB upsert on every poll.
- **D19 Secrets/network bypass.** AlpacaPaperBroker reads `LEVIATHAN_ALPACA_PAPER_*` from `os.environ` and calls urllib; guard/capabilities read env directly.
- **D20 Product gaps.** Only equity + crypto spot; `OrderType.LIMIT` exists but `OrderIntent` has no order type/limit price; `run_market_demo` copies fixtures out of the tests dir at runtime; `Portfolio.unrealized_pnl` property is a stub returning 0.
- **D21 Migration head drift.** `test_migrations.py` asserts head 32; `store.py`/docs reference migration v34. Determine the truth from `migrations.py`.
- **D26 Job integration missing.** Runs don't use JobRuntime/JobStore leases although `market_sim.advance` is reserved in `EXTERNAL_WORKER_CAPABILITIES` (verify registration in `execution/builtins.py`).

### Frontend & tests

- **D27 UI gaps.** SimulatiePage only creates one hard-coded 4-agent multi-wallet run (cash/fees/dates/sizing/engine not configurable; the chosen strategy only supplies `strategyId` while agents carry hard-coded parameters). `run_live_state` returns the oldest 100 fills/messages and the first 2 000 equity points (`ORDER BY … ASC LIMIT`), the page then shows `.slice(-40)` of that ⇒ long runs look stale/truncated. Chart has no axes/drawdown/trade markers; KPI "Win rate" is effectively always UNMEASURED (D2). Paper page: manual ticket only.
- **D28 Weak tests.** Determinism test compares fills over 4 days of a ~100-bar fixture; demo tests accept RUNNING as success; experiments completed with hand-typed metrics; no golden fills, accounting invariants, statistics, sandbox, restart/resume, cost-math or multi-process tests.
- **D31 Decision-cadence quirks.** Service defaults create agents (trend/mean-reversion/risk), so "default" runs go through deliberation. In the legacy engine the decision procedure alternates by bar index (every `deliberation_every_n`-th bar (default 5) the multi-agent vote decides, on other bars the raw strategy signal decides); in the multi engine agents decide only every N-th bar and nothing is decided in between. The run's single strategy hash is applied to all agents. Cadence must be an explicit, recorded run parameter, not a side effect.

# PART E — TARGET ARCHITECTURE

```
 Operator UI /trading/*  (Marktdata · Simulatie · Strategieën · Onderzoek · Validatie · Bibliotheek · Training · Paper · Risico · Portefeuille · Broker)
        │ typed client (src/api/client.ts, src/types/api.ts)
 /api/market-sim/* (kept)  +  /datasets /quality /splits /validation /trial-ledger /campaigns /library /promotion /gym /agents /risk /audit
        │
 MarketSimControlPlane ─ every side effect via ExecutionGateway (registered capabilities, approvals, receipts)
   ├─ ingest/       Data platform v2: streaming import, quality, calendars, corporate actions, versions, splits, providers v2
   ├─ kernel/       Kernel v2: one causal engine, multi-asset, long/short, order types, unified fills, instrument rules, checkpoints
   ├─ strategies/   Spec v2 (superset of DSL), features, sizing, sandboxed code strategies, lineage
   ├─ validation/   Metrics v2, trial ledger, WFA, purged CV/CPCV, PSR/DSR/PBO, robustness, sealed evaluator, calibration harness
   ├─ library/      Persistent strategy memory ↔ Knowledge V2 / Memory / VerifiedExperience, similarity, lessons
   ├─ factory/      Campaigns + trading agent executors on Agent Fleet / Cognition DAG
   ├─ gym/          TradingGym (reset/step), curriculum, domain randomization, episode ledger, scorecards, readiness ladder, trajectory export
   ├─ promotion/    Evidence-gated lifecycle (flywheel pattern), decay monitor
   ├─ live_paper/   Autonomous paper runner, reconciliation, drift, sim-to-real gap
   ├─ risk/         Risk Engine v2, breakers, global kill switch, autonomy levels
   └─ brokers/      BrokerAdapter protocol: PaperBroker(persistent) · ReplayBroker · AlpacaPaper · LiveBroker(UNSUPPORTED)
        │
 JobStore leases (`market_sim.advance`, external worker) · SecretsBroker · Settings Control Plane · Observability · Backup
 Central SQLite + ArtifactStore (equity/trade/episode series, hash-verified)
```

**Keep (do not rewrite):** SimulationClock semantics, LiveTradingGuard + TradingStub refusal, RiskGuard override-key sanitizer, provider registry shape, truth-block convention. `multi_engine` + commit-reveal remain for multi-agent competition games (fixed per D30), separate from headless research runs.

New code lives in sub-packages under `Data/modules/market_sim/`; old flat files become thin compat shims only after parity tests pass.

# PART F — PHASES

The old large phases are split into smaller, independently shippable subphases. One named subphase per Cursor session unless the operator explicitly authorizes combining them.

Every implementation subphase updates backend + frontend contracts together where a user-visible capability becomes stable. T10 is integration/consolidation, not the first time the UI is wired.

## T0 — Recon, characterization, ownership, verifier (NO feature code)

1. Read all files listed in the original program plus current `App.tsx`, `navigation/menu.ts`, all `pages/trading/*`, worker catalog/entrypoint and current market-sim route/API client/types.

2. Create PASSING characterization tests for D1–D31 documenting current defective behavior. Tag each defect. Do not leave main red.

3. Create:

- `Data/docs/trading_program_state.md`
- `Data/docs/trading_gap_report.md`
- `Data/docs/trading_reference_hardware.json`
- `Data/docs/trading_performance_budget.json`
- `Data/docs/trading_frontend_action_matrix.md`
- `Data/backend/tests/trading_gates.json`
- `scripts/verify_trading_100.py`

4. Record each D1–D31 as `CONFIRMED | PARTIAL | REFUTED | ALREADY_FIXED` with evidence. New defects become D32+.

5. Record real migration head, API route map, job/capability map, worker ownership map, frontend control inventory, Settings entries and security boundaries.

6. Freeze reference performance budgets before feature optimization.

7. Run baseline suites and record existing failures honestly.

8. Stop for approval.

## T1A — Metrics/accounting truth [D1,D2]

- timeframe/calendar-aware annualization
- round-trip trade ledger
- win rate/profit factor/expectancy from ledger
- per-agent equity-series foundation
- known-answer metrics

## T1B — Risk sizing/fill unification [D3,D4,D5]

- trading-day reset
- explicit sizing models
- risk-to-stop semantics
- unified Decimal reference fill model
- spread/slippage/fees/participation
- partial-fill continuation

## T1C — Restart/determinism/persistence hot path [D6,D7,D8,D25-part]

- complete checkpoints
- kill/resume parity
- dataset hash verification
- batched writes
- no per-bar DB connection
- incremental metrics
- durable lease ownership

## T1D — Causality/commit/cadence [D10,D30,D31]

- bounded MarketView
- full observation/context commitment
- risk veto as separate immutable event
- explicit decision cadence
- poison-future regression

**Mandatory Skeptic pass.**

## T2A — Streaming Data Platform core [D9]

- streaming CSV/TSV/JSONL/optional Parquet
- explicit column mapping
- multi-symbol support
- quarantine
- versioned content-addressed dataset objects
- filename inference suggestion only
- heavy import as external job

## T2B — Time/calendars/quality/corporate actions [G02,G03,G04,G56]

- UTC/exchange time contract
- DST
- calendars
- quality checks
- split/dividend/delisting
- raw + adjusted views
- persisted quality report

## T2C — Splits/regimes/resampling/sealed [G06]

- deterministic resampling
- regime labels
- TRAIN/VALIDATION/SEALED
- purge/embargo
- sealed access ledger

## T2D — Providers v2 [D23,G07,G55]

- pagination
- rate limiting/backoff/jitter
- canonical network policy
- no overwrite
- provider provenance/licensing/adjustment state
- bid/ask when genuinely supported
- long historical fetch through canonical external jobs/provider pool

## T3A — Kernel v2 event/order/accounting core [G08,G09]

- deterministic event ordering
- multi-instrument
- long/short
- first-class MARKET/LIMIT/STOP/STOP_LIMIT
- TIF
- reduce-only
- bracket/OCO
- working orders
- golden accounting

## T3B — Execution realism + instrument rules [G08,G10]

- tick/lot/min-notional/fractional/shortability/currency/session
- gaps
- same-bar ambiguity policy
- spread/impact/fees/borrow/funding
- execution delay
- volume participation

## T3C — Margin/actions/checkpoints/performance [G11,G13]

- margin/leverage gated OFF by default
- liquidation
- actions/delisting
- bounded-memory iterator
- checkpoint/resume
- fingerprint
- performance instrumentation

## T3D — Strategy Spec v2 / feature library [G15,G17]

- preserve current two DSL strategies exactly
- feature registry with declared lookbacks
- causal indicators/features
- rule trees
- stops/targets/trailing
- sizing/rebalance/universe/portfolio construction
- hypothesis/expected regimes
- immutable lineage

## T3E — Restricted code strategy path [G16]

- AST policy
- JSON-schema IPC
- subprocess
- bounded MarketView
- timeout/resource enforcement
- requested/effective isolation
- escape suite
- refuse arbitrary untrusted code under insufficient isolation

**Mandatory Skeptic pass.**

## T4A — Capability/Gateway integration [D16,G37]

Register trading capabilities in the existing catalog. Side-effecting routes dispatch through ExecutionGateway/Policy/Approvals/effect receipts. Keep pure reads lightweight.

## T4B — Canonical JobRuntime + existing market_sim worker [D25,D26,G38,G51,G52]

- use JobStore leases/heartbeats/retry
- existing `Data.modules.workers.entrypoints.market_sim` owns `market_sim.*`
- no second queue/lease/supervisor
- compatibility `scripts/market_sim_worker.py` delegates to canonical worker plane if retained
- two-worker claim test
- crash/reclaim/cancel
- idempotency
- resource classes/backpressure
- interactive LEVIATHAN priority

## T4C — Secrets/network/settings [D19,G40]

- SecretsBroker
- canonical network path
- Settings Control Plane
- hot vs restart-required
- redaction
- no secret in jobs/public dict/log/prompt

## T4D — Persistence/ArtifactStore/observability/backup [D21,G39,G49,G50,G54,G58]

- migration head truth
- append-only ledgers
- ArtifactStore large series
- paginated/downsampled endpoints
- trading observability/status
- backup/restore temp-target round trip

## T5A — Metrics v2 + global Trial Ledger [D11,D12,D14,G18,G19,G21]

- verified ledger-derived metrics only
- caller metrics non-authoritative
- every candidate/failure counts where relevant
- effective-trial foundation

## T5B — WFA / purged CV / CPCV [D13,G20]

- rolling/anchored WFA
- purged K-fold
- CPCV
- stitched OOS
- parameter stability

## T5C — Robustness + sealed evaluation [G20,G21]

- cost 1.5x/2x/3x
- delay
- perturbation
- start shift
- regime/subperiod
- cross-asset
- Monte Carlo
- random-entry baseline
- sealed single-use

## T5D — PSR/DSR/PBO + false-discovery calibration [G18,G19,G46]

- known-answer statistics
- FAST calibration for CI
- RELEASE calibration for final acceptance
- pure-noise FDR gate uses a one-sided 95% upper confidence bound <= configured target
- planted-edge power gate uses one-sided 95% lower confidence bound >= configured target
- fixed seeds/config
- dependency-free Wilson bound acceptable if documented/verified

**Mandatory Skeptic pass.**

## T6A — Strategy Library / negative results / evidence [D15,G22]

- hypotheses
- versions
- positive + negative results
- postmortems
- lessons
- evidence links
- trust state
- correlation/similarity

## T6B — Point-in-time Brain/Memory [D22,G23]

Historical runs exclude current Brain by default or enforce `as_of <= decision_time`; content hashes/policies are part of run provenance where used.

## T6C — Promotion lifecycle [G31,G53]

`DRAFT → SCREENED → BACKTESTED → VALIDATED → SEALED_PASSED → PAPER_FORWARD → LIVE_ELIGIBLE`, with explicit evidence, no skipped states, UNMEASURED blocking, human-only LIVE_ELIGIBLE, demotion/decay/champion-challenger.

## T7A — Real Trading Role Executor [D17,G24]

Use AgentFleet/AgentRuntime/Cognition/Model Control Plane. Structured schema output. Agents propose/critique/explain; deterministic kernel/evidence systems compute fills/PnL/statistics/verdicts.

## T7B — Durable ResearchCampaign [G25]

Persist goal/universe/dataset/splits/budget/steps. Resume/cancel/retry/idempotency. No duplicate side effects.

## T7C — Search/strategy factory [G24,G25]

Grid/random/optional approved Bayesian search + mutation/crossover/family expansion. Every candidate immutable + lineage + Trial Ledger row.

## T8A — TradingGym environment [G26]

Same Kernel v2, not a toy simulator. Deterministic reset/step, causal observations, kernel reward, action validation, episode ledger, SEALED inaccessible by construction.

## T8B — Curriculum / domain randomization [G26]

Trend → mean-reversion → mixed → stress → randomized costs/latency/spread → multi-asset → adversarial perturbation. Promotion on validation windows with CIs.

## T8C — Policy adapters / training loop [G29]

Programmatic strategies, coarse/macro-action LLM agents, optional external ML/RL adapter, stdlib reference learner. External trainers are canonical jobs; checkpoints are artifacts.

## T8D — Scorecards/readiness/trajectory export [G27,G28,G29,G30]

Per-regime/year CIs + violations + token/latency + multiple-testing penalty; A0→A4 enforced; A5 blocked; verified trajectories export through existing Datasets/Training; sim-to-real gap foundation.

**Mandatory Skeptic pass.**

## T9A — Persistent PaperForwardRunner [D18,G32]

Per-session persistent wallets; strategy/agent→intent loop; restart/checkpoint; idempotent client order IDs; GET endpoints side-effect free.

## T9B — Risk Engine v2 [G34]

One unavoidable risk path for manual + strategy + agent paper orders. Pre-trade and continuous breakers. Persistent global/per-strategy kill switch. Human reset. Limit loosening approval-gated.

## T9C — Brokers/reconciliation/drift [G33,G35]

Persistent PaperBroker + ReplayBroker + Alpaca-paper through SecretsBroker; LiveBroker explicitly UNSUPPORTED; independent shadow-ledger reconciliation; stale-feed/data-quality pause; sim-real-gap report.

## T9D — Audit/failure injection/security [G36,G48]

Hash-chained intent→risk→broker→fill→reconcile audit; tamper test; duplicate order, stale feed, network failure, crash/restart and kill-switch failure injection.

**Mandatory Skeptic pass.**

## T10A — Make the existing six TradingCenter pages production-complete [G41,G42,G57,G59]

### Marktdata

Turn the existing page into the real data operations console: import/provider wizard, job progress, mapping, timezone/calendar, versions, quality report, quarantine, corporate-action/adjustment state, split editor, regime timeline, provenance/licensing, resampling. Heavy scan/import is never long inline API work.

### Simulatie

Replace the hard-coded 4-agent create path with a complete typed run builder: dataset version/split/window, engine, strategy/version, instruments, capital, sizing, costs, fill model, delay, risk, cadence, seed, game mode, optional agents/policies, Brain policy, checkpoints. Add run filters, progress/ETA/bars-sec, reproduce, compare, trade ledger, price+markers, equity, drawdown, exposure, benchmark, costs, per-year/per-regime, per-agent metrics, fingerprint/causality/error views. Series APIs support `tail`/`from`/`to`/`maxPoints`; never render stale oldest-N as if current.

### Strategieën

Working search/filter, Strategy Spec v2 round-trip, version tree/lineage/diff, hypothesis/expected regimes, static/causal validation, isolation status, evidence, promotion state, fork/archive. Existing illustrative visual builder must either truly compile/round-trip to the spec or remain clearly read-only — never imply execution of decorative nodes.

### Portefeuille

Bind to real simulation/paper portfolio sources with explicit provenance: holdings, allocation, cash, equity, PnL, exposure, correlations, risk contribution, drawdown, open orders and source run/session. Never mix simulation and paper state without labels.

### Paper Trading

Evolve the current manual-ticket page into the PaperForwardRunner operations console: session/policy/strategy/agent/autonomy selection; start/pause/stop; positions/orders/fills; persistent wallet; feed health; reconciliation; drift; incidents; sim-real gap; kill switch. Keep manual ticket but route it through Risk Engine/Gateway. Poll cached state; GET is side-effect free.

### Broker Trading

Honest broker/capability/readiness console: adapter health, paper capabilities, Secrets status without secret values, autonomy explanation, approvals/readiness checklist, live-guard state and explicit reasons real-money execution remains blocked.

**Frontend rules:** keep AppShell/current style, no second fetch wrapper, no mock values, strong TypeScript contracts, loading/empty/error/success, accessible controls and page-visibility-aware polling.

## T10B — Add the missing TradingCenter pages, integrated into current App.tsx + navigation/menu.ts

Add real pages/routes only when their backend capability exists:

1. `/trading/onderzoek` — **Onderzoek**

- ResearchCampaign create/list/open
- DAG/agent timeline
- blackboard summaries
- budget burn
- candidate lineage
- effective trial count / DSR warning
- pause/resume/cancel
- evidence links

2. `/trading/validatie` — **Validatie**

- WFA stitched OOS
- purged/CPCV results
- PBO/PSR/DSR
- bootstrap CIs
- robustness matrix
- SEALED status/access
- FDR/power calibration
- exact MeasurementState
- promotion eligibility explanation

3. `/trading/bibliotheek` — **Bibliotheek**

- hypotheses
- versions
- positive + negative results
- similarity/correlation
- lessons/postmortems
- trust state
- evidence links
- lineage

4. `/trading/training` — **Training / TradingGym**

- curriculum
- episodes
- policy versions
- scorecards/CIs
- violation counts
- leaderboard penalty
- readiness A0–A4
- trajectory export
- generated dataset links
- sim-real gap

5. `/trading/risico` — **Risico**

- current limits
- approval-gated edits
- breaker state
- exposure
- kill switch
- incidents
- risk events
- audit-chain verification
- policy source

**Recommended TradingCenter submenu order:**

Simulatie · Strategieën · Marktdata · Onderzoek · Validatie · Bibliotheek · Training · Paper Trading · Risico · Portefeuille · Broker

All user-facing TradingCenter labels should be consistent Dutch except standard technical/market terminology. Code/API identifiers/docs remain English.

## T10C — Shared Trading UI / chart / action architecture

Create/extend coherent reusable components under the existing trading frontend area:

- TimeSeriesChart
- PriceChart with trade markers
- EquityChart
- DrawdownChart
- ExposureChart
- CostBreakdown
- MetricCard+MeasurementState
- QualityBadge
- EvidenceLink
- RunFingerprint
- JobProgress
- SplitTimeline
- ValidationMatrix
- PromotionStepper
- RiskStateBadge
- IncidentTimeline
- ConfirmDangerButton
- Loading/Empty/Error states

No giant page rewrite just to abstract styling.

Charts require axes, units, timezone, tooltips and server-side downsampled/bounded data. No millions of raw points in React.

## T10D — Frontend action matrix + cross-system integration [G57,G59]

Create/update `Data/docs/trading_frontend_action_matrix.md`: page, visible control, endpoint/capability, side-effect class, success/error/busy/disabled semantics, automated/manual test and PASS state. No unexplained decorative control.

Integrate trading with existing LEVIATHAN:

- Jobs/Tasks projection for long work where supported
- Agents page for real trading missions
- Datasets/Training for trajectory datasets
- Evidence Vault for validation/promotion/incidents
- Brain/Knowledge/Memory with point-in-time policy
- Workflows/Schedules for canonical orchestration/scheduling
- Settings `markt_sim` section for all trading thresholds/policies
- Analytics/Status/Performance for real operational metrics

**Mandatory Skeptic pass.**

## T11 — Exit gates, CI, docs, completion [G43,G44,G45,G60]

Run targeted + full relevant backend suites, frontend test/typecheck/lint/build, Windows worker tests, migration fresh/upgrade, backup/restore and `scripts/verify_trading_100.py`. Generate final completion report only if required gates PASS. Live LLM/feed/broker integration remains explicitly `NOT_TESTED_IN_CI` where applicable and cannot be represented as production-live readiness.

# PART G — PERSISTENCE (additive migrations after the REAL head — verify D21)

Extend v16/v34 tables where sensible; new tables (adapt names to conventions after the Gap Report):


- market_datasets
- market_dataset_versions
- market_dataset_shards
- market_quality_reports
- market_quarantine_rows
- market_split_manifests
- market_sealed_access_log
- market_regime_labels
- market_corporate_actions
- market_instruments
- market_calendars
- market_run_fingerprints
- market_run_checkpoints
- market_trades (round-trip ledger)
- market_agent_equity
- market_strategy_lineage
- market_feature_registry
- market_trial_ledger (append-only)
- market_validation_reports
- market_validation_tests
- market_promotion_transitions
- market_campaigns
- market_campaign_steps
- market_library_entries
- market_postmortems
- market_lessons
- gym_episode_specs
- gym_episodes
- gym_curriculum_stages
- agent_policy_versions
- agent_scorecards
- agent_readiness
- training_trajectories
- preference_pairs_index
- paper_wallets
- paper_orders
- paper_fills
- paper_reconciliations
- paper_drift_stats
- risk_limits
- risk_events
- risk_kill_switch_log
- trading_audit_chain
- sim_real_gap_reports

Large series (equity, trades, episodes, prompts/outputs) → ArtifactStore (hash-verified). Append-only tables enforced by triggers or a store API without update/delete. Migration tests: fresh + upgrade + append-only enforcement.

## PART G.5 — FRONTEND/API HARMONY RULES

- Keep one frontend client: `Data/frontend/src/api/client.ts`.
- Keep one public contract home: `Data/frontend/src/types/api.ts`.
- Stable Trading API contracts must not remain `Record<string, unknown>` after their backend schemas are defined.
- Every async panel has `LOADING` / `EMPTY` / `ERROR` / `SUCCESS`.
- Polling is overlap-safe, visibility-aware and preserves selection/forms.
- Long operations return durable job IDs quickly; frontend polls/subscribes to job progress rather than holding an HTTP request open for the whole computation.
- Every dangerous action explains why it is allowed/blocked; frontend state never confers authority.
- Deep links should be supported for important run/strategy/campaign/report IDs where useful.

# PART H — API, CAPABILITIES, FLAGS, SETTINGS

- Keep every `/api/market-sim/*` route working. Additive groups: `/datasets*`, `/quality`, `/splits`, `/validation*`, `/trial-ledger`, `/campaigns*`, `/library/*`, `/promotion/*`, `/gym/{episodes,curriculum,agents,scorecards,readiness,export}`, `/paper/sessions/{id}/{start,stop,pause,refresh,reconcile,drift}`, `/risk/*`, `/audit*`. Series endpoints take `tail`, `from`, `to`, `maxPoints`. camelCase bodies. No second overlapping trading API.
- Flags under `LEVIATHAN_FEATURE_MARKET_SIM` (hierarchical validation in `config.py`): `_TRADING_DATA_PLATFORM`, `_TRADING_KERNEL_V2`, `_TRADING_VALIDATION`, `_TRADING_FACTORY`, `_TRADING_GYM`, `_TRADING_LIBRARY`, `_TRADING_PAPER_FORWARD`, `_TRADING_RISK_V2`, `_TRADING_LIVE` (default false; validated). Old env reads (`LEVIATHAN_LIVE_TRADING_UNLOCK`, `LEVIATHAN_LIVE_BROKER_ADAPTER`, `LEVIATHAN_ALPACA_PAPER_*`) move to Settings + SecretsBroker with backward-compatible loading and redaction.
- Settings Control Plane entries (versioned, audited, hot vs restart-required, secret redaction): min trades/OOS length, DSR/PSR/PBO cutoffs, robustness criteria, FDR/power targets, cost defaults, sizing defaults, risk limits, autonomy defaults, campaign budgets, curriculum thresholds, quality-check thresholds.
- `/api/status` shows real trading posture: dataset quality, active jobs, trial-ledger size, campaigns, gym stats, paper sessions, risk/kill-switch state, live flag, audit-chain verification state.

# PART I — TEST & VERIFICATION STRATEGY

Every gate maps to tests in `trading_gates.json`. Minimum coverage (in addition to G-specific tests above):

- **Characterization → regression:** one test per D-item (T0), green after its fixing phase.
- **Kernel:** golden fills/PnL (hand-computed, checked into repo as small JSON), property-based invariants, margin/liquidation, partials/TIF/gaps, same-bar ambiguity policies, corporate actions, timezone/DST/session, long/short round trips, instrument-rule enforcement, cost-model math.
- **Causality/determinism:** poison-future (every strategy/feature/MarketView), purge/embargo leakage, byte-identical replay, kill/resume, cross-process, job retry ⇒ no duplicate fills.
- **Statistics:** known-answer Sharpe/Sortino/PSR/DSR/PBO/bootstrap (seeded); ledger-bypass impossibility; calibration null/power (G46).
- **Sandbox/security:** escape suite; secrets never in `public_dict`/logs/prompts; approvals required for destructive capabilities; override keys blocked.
- **Promotion/library/gym:** cannot-skip, UNMEASURED blocks, human-only live-eligible, sealed single-use, caller metrics rejected; retrieval evidence-linked, `trust=model_output` rejected, memory causality; gym determinism, sealed-window unreachability, reward computed by kernel only, curriculum gating, scorecard CIs, readiness ladder, export contamination scan.
- **Agents/campaigns:** fake-LLM e2e; restart mid-campaign; budgets; no un-ledgered trials; schema-validation failures handled with repair then honest failure.
- **Paper/risk/broker:** per-session wallet isolation, restart/resume, reconciliation mismatch halts, stale feed pauses, every limit triggers, global kill switch under failure injection, autonomy policy, live refuses, TRADING_LIVE flag validation, audit-chain tamper detection.
- **Infra:** two-worker double-claim, hard-crash recovery, migrations fresh/upgrade, backup round-trip, Windows path/spawn tests, network-policy enforcement (no raw urllib in adapters — grep test).
- **Performance:** benchmarks recorded (bars/sec, memory), not asserted tightly except "does not OOM within the stated budget".
- **Frontend:** typecheck/lint/vitest/build + client contract tests.
- **Harness self-tests:** `verify_trading_100.py` fails when any gate lacks evidence; the anti-shortcut greps (TODO/skip/NotImplementedError) run inside it.

Live LLM, live market feed and any live broker path are `NOT_TESTED_IN_CI` and listed as such.

# PART J — ANTI-PATTERNS & EXPLICIT NON-CLAIMS

**Reject:**

- zero-cost or same-close-fill demos
- optimizing on everything then reporting it
- touching sealed data twice
- LLM-computed metrics
- any run path skipping the trial ledger
- reward or score computed by the agent
- training on SEALED windows
- silent defaults that flatter results
- survivor-biased data labeled validated
- a second registry/DB/gateway/job-queue/agent stack
- fake fills/progress/equity/mock UI numbers
- live trading enabled by default, by an agent, or without human sign-off
- undeclared dependencies
- bulk market data committed to git (belongs under `LEVIATHAN_MARKETS_ROOT`)
- claiming anything that wasn't run

**Explicitly NOT claimed** (repeat/adjust in `buildplan.md` and the Completion Report):

- profitability or expected returns of any strategy or agent
- that gym performance transfers to real markets
- production-grade live execution or any live venue integration
- L5 autonomy
- microstructure realism without L2/L3 data
- options/futures/forex support unless separately built and proven
- tax/legal compliance
- investment advice

# PART K — KICKOFF LINES

## Start (session 1)

> Read `Data/docs/trading_program.md` fully. Execute **T0 only**. Re-read the actual current source; code/tests win over this program. Do not write feature code. Produce passing characterization tests for D1–D31, the state/gap reports, real ownership map, worker/job/capability map, frontend action inventory, real migration head, frozen reference hardware/performance budget, gate manifest and verifier skeleton. Mark defects CONFIRMED/PARTIAL/REFUTED/ALREADY_FIXED with evidence. Run baseline suites. Stop and wait for approval.

## Every later session

> Read `Data/docs/trading_program_state.md` first. Execute exactly the requested subphase (for example T1A, T2D, T4B, T10A) from `Data/docs/trading_program.md`. Re-read the ownership matrix, invariants, relevant defects/gates and current source. Convert that subphase's passing characterization into the desired failing regression before implementation. Extend existing LEVIATHAN systems; no parallel DB/gateway/job queue/worker supervisor/agent/model/settings/frontend client. Update backend + frontend contracts together where relevant. Run targeted tests, impacted gates and the mandatory Skeptic pass when specified. Update state/docs with real evidence, then stop.

## Skeptic pass (when required)

> Act as the Skeptic for the completed subphase. Try to break causality, determinism, checkpoint/restart, trial-ledger completeness, SEALED isolation, statistical calibration, reward authority, sandbox isolation, promotion gates, side-effect authority, Risk Engine coverage, idempotency, worker double-claim, stale frontend state, secret handling and live-trading refusal as applicable. Write a failing regression before fixing each confirmed defect. Re-run affected gates.

## Final acceptance

> Run `scripts/verify_trading_100.py` on a clean checkout/runtime with all required backend/frontend/migration/worker/backup tests. Any required non-PASS gate means the program is incomplete. List exactly what is missing, fix it and repeat. When all required offline gates PASS, generate `trading_completion_report.md` with evidence, measured performance/reference hardware, known limitations and the required Explicitly NOT claimed section. Never represent NOT_TESTED live integrations as PASS.

End of Master Program v4.
