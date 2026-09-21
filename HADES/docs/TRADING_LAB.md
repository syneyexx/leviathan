# HADES Trading Lab

Local research, simulation and paper environment for multiple markets, strategies and order types.
Everything in this subsystem is **SIMULATION/PAPER only**: there is no broker session, no real-money
code path, no API keys for a trading venue, and no paid data feed.

Base commit for the work: `777adc27914823a99144876c433318e30c2e225e` (`main`).
Gap analysis of the pre-existing trading code: [`TRADING_LAB_GAP_ANALYSIS.md`](TRADING_LAB_GAP_ANALYSIS.md).

## 1. What was kept

The existing `PaperTradingService`, `TradingBotService`, `TradingJobRunner`, migration 6 tables and all
`/api/trading*` routes are unchanged, so the current paper flows, the `trading_specialist` agent and the
existing tests keep working. The legacy page is preserved verbatim as the **Paper desk** tab.

Two pre-existing defects were fixed in place because they produced wrong answers rather than missing
features: `list_symbols` returned `MAX(close)` as "last close", and `import_csv` accepted non-finite
values, inconsistent OHLC rows, negative volume and duplicate timestamps.

## 2. Architecture

New code lives in `backend/trading_lab/` (additive package, ~15.7k lines). Direction of dependencies is
one-way: contracts ← domain modules ← service ← routes. Nothing in the domain imports FastAPI.

| Module | Responsibility |
|---|---|
| `contracts.py` | Pydantic contracts for every boundary: instruments, datasets, orders, fills, snapshots, risk, strategies, evaluation |
| `instruments.py` | Instrument registry: identity, tick/lot, calendar, margin and family-specific terms |
| `capabilities.py` | Capability matrix; refuses invalid instrument × strategy × order-type × data-level combinations |
| `calendars.py` | Trading calendars and periods-per-year for honest annualisation |
| `data_quality.py` | Timestamp normalisation and `BarValidator` (OHLC consistency, gaps, staleness, outliers, duplicates) |
| `bar_store.py` | Partitioned fixed-width binary bar store: year partitions, binary search, checksums, optional Parquet export |
| `catalog.py` | Dataset manifests, immutable revisions, chronological splits, coverage and gap reporting |
| `providers.py` | CSV import, local synthetic generation and optional public HTTP sources; honest per-provider status |
| `clock.py` | `SimulationClock`, `DataAccessPolicy`, `PointInTimeGateway`: the only read path for market data |
| `accounting.py` | Multi-currency `Decimal` ledger, positions, idempotent bookings, reconciliation |
| `adapters.py` | Per-family mechanics: spot wallets, perpetual funding, equity corporate actions, forex swap, futures roll, options greeks, bonds |
| `execution.py` | `ExchangeSimulator`: the only writer of fills. Spread, fees, slippage, latency, participation cap, rejects, expiry, OCO |
| `risk.py` | Deterministic risk engine with the decisive veto plus the model-override sanitizer |
| `strategies.py` | Thirteen strategy families as deterministic signal generators |
| `features.py`, `models.py` | Feature library and versioned model training (preprocessing, features, labels, weights, cutoff) |
| `engine.py` | Chronological run loop: observe → decide → risk → submit → fill on later events; checkpoints, rewind branches |
| `research.py` | Preregistered, bounded experiment search; every trial recorded |
| `evaluation.py` | Walk-forward folds, deflated Sharpe, block bootstrap intervals, stress scenarios, verdicts |
| `registry.py` | Strategy lifecycle, independent-evaluation gate, single-use sealed test |
| `agents.py` | Ten agent roles with explicit read/write permissions; deterministic services excluded from model control |
| `experience.py` | Idempotent experience records from delayed decision outcomes |
| `regimes.py` | Point-in-time OHLCV regime features (trend / volatility / stress) |
| `learning.py` | Deterministic aggregation, evidence-quality confidence, belief updates |
| `evolution.py` | Bounded declarative mutations, fingerprints, lineage |
| `champions.py` | Champion/challenger admission; development numbers cannot install a champion |
| `learning_cycle.py` | Durable bounded research loop with autonomy levels |
| `jobs.py` | Bounded job queue with idempotent keys, pause/step/cancel and resume after restart |
| `store.py` | SQLite persistence (additive `lab_*` tables) including append-only ledger, order events, decisions, experiences, beliefs |
| `service.py`, `routes.py` | Service facade and HTTP endpoints under `/api/trading/lab/*` |

### Backtesting engine decision

An external engine was evaluated and **not** adopted:

- **LEAN (QuantConnect)** needs the .NET runtime plus its own data format and configuration layer. That
  is a second runtime to ship on a Windows-first, offline-first installation, and its data conventions
  would have to be bridged to the HADES dataset manifests anyway.
- **NautilusTrader** is the closest fit architecturally, but it is a compiled (Cython) dependency with a
  heavy transitive set (`pandas`, `pyarrow`, `numpy`). Those packages are not in `requirements.txt` and
  cannot be installed in this environment, so adopting it would mean shipping a subsystem that cannot
  start on a clean offline machine.
- **`vectorbt` / `backtesting.py`** are vectorised research tools without an event-driven order
  lifecycle, margin accounting or a risk gate, which is most of what this subsystem is about.

The engine here is therefore native and dependency-free (standard library only), event-driven on closed
candles, and deliberately conservative where the data cannot answer a question. The cost of that choice
is that no third-party engine validates our fills; the mitigation is that fill rules are small, explicit
and unit-tested, and the report lists what the simulator cannot model.

## 3. Capability matrix

`GET /api/trading/lab/capabilities` returns the machine-readable matrix. Status vocabulary:
`implemented`, `implemented_needs_data` (code exists and runs, real history is missing), and
`blocked_missing_data` (refused at the API boundary instead of approximated).

**Instrument families:** crypto spot, crypto perpetual, equity, ETF, forex, future, option, CFD, bond.
All `implemented` except `option` and `bond`, which are `implemented_needs_data` (no chain history, no
dealer quotes).

**Strategy families:** trend following, momentum, breakout, mean reversion, pairs trading, statistical
arbitrage, carry/funding, basis, event driven, option volatility, market making, execution schedule,
model signal. `carry_funding` is `implemented_needs_data`; `event_driven`, `option_volatility` and
`market_making` are `blocked_missing_data` (no point-in-time news feed, no option chains, no level-2
book). Horizons (scalping, intraday, swing, position) and directions (long only, short only, long/short)
are declared per family and enforced.

**Order types:** market, limit, stop-market, stop-limit, trailing stop, take-profit and bracket/OCO, all
`implemented`. Modifiers: reduce-only, post-only, and time in force GTC, DAY, IOC, FOK. Multi-leg orders
are declared per family and only accepted where the family supports them.

Invalid combinations are refused with a reason at three points: `validate_order_capability` at order
submission, `validate_strategy_capability` at strategy registration, and the run planner when a dataset
does not provide the required data level.

## 4. Data and time

- Every observation stores **event time**, **availability time** and **ingestion time**. Availability is
  the bar close plus the declared publication delay, never the bar open.
- Datasets are immutable versions with a checksum, provider, licence, quality report and split
  boundaries. Freezing a dataset binds it to experiments; re-import creates a new revision.
- Coverage is whatever the operator imports or downloads. Nothing is invented: a requested range with no
  source produces a gap report, not generated prices. Synthetic data is labelled `synthetic` and cannot
  be used for a promotion verdict.
- One `SimulationClock` per run. An agent can only read events with `available_at <= clock.now`; a
  violation raises instead of returning data. Orders are created strictly after the observation that
  produced the signal, and fill only on later events. Intrabar fills are not produced without finer
  data; ambiguous cases are marked on the fill.
- Sealed splits are unreadable for agent policies and readable only by an evaluator policy. Caches are
  namespaced per policy and per clock instant.

## 5. Reproducibility

Every run records `run_id`, base commit, engine version, strategy hash, dataset ids and checksums,
seeds, cost model, risk limits, model versions, split and (for a rewind) the parent run and branch
point. Rewinding never moves the clock backwards: it creates a new branch run from the nearest
engine checkpoint at or before the requested time, then continues to the parent's original end.
The parent run is not truncated and no post-branch events are deleted. Pause, play, step and
speed are honoured inside the event loop; they never change event order. Jobs start playing at
maximum speed so experiments finish without a UI click. A lower speed is an operator override.
`GET /api/trading/lab/runs/{run_id}/reproducibility` returns that record.

## 6. Agents

Ten roles: research director, market specialist, data steward, strategy researcher, quant builder,
experiment planner, independent validator, risk analyst, portfolio analyst, learning curator. Each has a
mandate, a read set, a write set, a forbidden set and a structured output schema.

The exchange simulator, ledger, risk engine, order executor and evaluation metrics are **deterministic
services**, not roles: no model influences them. Attempts to pass override fields (`force`,
`bypass_risk`, `override_limits`, anything `risk_*`) are stripped at the boundary and the attempt is
recorded; the risk engine additionally blocks the order outright.

Roles share one local model by default, with optional per-role overrides resolved from settings at call
time. No model id is hardcoded. With no model gateway available, the agent tab reports `unavailable`
with a reason instead of producing text.

**No model-written code is ever executed.** A strategy is declarative — a family from the registry plus
validated parameters — so there is no generated Python to compile, sandbox or gate. The lab contains no
`exec`, `eval` or `compile` call for model output; a model that cannot express an idea in a supported
family must say so in `unsupported_aspects`, which is the honest outcome rather than inventing code.
`StrategySpec.code_reference` and `code_hash` only point at code that already exists in the repository.

## 7. Missing external data

From `providers.KNOWN_DATA_GAPS`, surfaced in the Overview and Knowledge tabs:

| Area | Missing | Consequence |
|---|---|---|
| Corporate actions | licensed split/dividend/symbol-change history | equity backtests are only correct for imported action series |
| Point-in-time index membership | constituent lists with add/remove dates | survivorship bias if a universe is built from today's members |
| Options | chain history with implied volatility | `option_volatility` cannot run on real data |
| Order book | level-2 depth, full quote tape | market making is blocked by design |
| Funding and borrow | historical funding rates, borrow fees | carry reports `missing_funding_data`; borrow falls back to configured rates |
| Fundamentals | point-in-time statements and estimates | no fundamental factor research in this installation |

Optional public sources (Binance public, Stooq, CoinGecko demo) are off unless network access is enabled
in Settings, and each reports its own licence and usability.

## 8. Verification status

**VERIFIED_ON_HOST (2026-09-17, Linux Cloud Agent, Python 3.12):** Trading Lab unit suites
were executed on this tip:

```bash
python3 -m unittest discover -s backend/tests -p 'test_trading*.py' -v
```

| File | Covers | Result |
|---|---|---|
| `backend/tests/test_trading_lab_point_in_time.py` | clock monotonicity, availability delay, sealed-split isolation, cache isolation, partitioned store | PASS |
| `backend/tests/test_trading_lab_accounting.py` | Decimal exactness, idempotent replay, weighted-average realised PnL, fee accounts, unconvertible currency warning, reconciliation, state round-trip | PASS |
| `backend/tests/test_trading_lab_execution.py` | no same-bar fills, cost direction, limit at its own price, gapped stops, participation partial fills, post-only, IOC, FOK, reduce-only, lot size, bracket OCO, determinism | PASS |
| `backend/tests/test_trading_lab_risk.py` | limits, kill switch, risk-reduction exception, override refusal and sanitizer, drawdown, incomplete data, open-order ceiling, reproducibility | PASS |
| `backend/tests/test_trading_lab_data_quality.py` | timestamp formats, availability computation, OHLC consistency, non-finite and negative values, duplicates, gap counting, staleness | PASS |
| `backend/tests/test_trading_lab_evaluation.py` | period returns, drawdown from running peak, deflated Sharpe versus trial count, deterministic bootstrap, verdict refusals, stress scenarios | PASS |
| `backend/tests/test_trading_lab_lifecycle.py` | capability matrix honesty, capability refusals (instrument family before direction), hypothesis requirement, promotion gate, single-use sealed test, evidence dossier | PASS |
| `backend/tests/test_trading_lab_models_providers.py` | refusal on too little history and unknown model kinds, training window and baseline comparison, determinism, artefact round-trip, provider usability and licences, declared data gaps | PASS |
| `backend/tests/test_trading_lab_control.py` | pause/cancel properties, step budget, rewind checkpoint selection (nearest at-or-before, refusal, latest fallback) | PASS |
| `backend/tests/test_trading_lab_learning.py` | experiences, regimes, beliefs, evolution, champions (development ≠ champion), recovery | PASS |

Aggregate for `test_trading*.py` on this host: see `docs/CURRENT_STATUS.md` (latest SpaceX evidence entry). Capability matrix `verification` field defaults to `verified_on_host`.

Canonical demo write-up: [`docs/demos/TRADING_LAB_SYNTHETIC_DEMO.md`](demos/TRADING_LAB_SYNTHETIC_DEMO.md).

Frontend checks for Lab UI labels (Paper desk legacy banner + Overview capability matrix) are covered by the repo `npm run typecheck` / `npm run lint` / `npm test` gates when those are recorded in CURRENT_STATUS.

### GUI checklist (manual)

Owner Windows GUI for Trading Lab tabs remains **UNVERIFIED_ON_HOST** in this Cloud Agent run unless separately recorded. Software contracts above are unit-verified.

1. **Overview** — counts, coverage window, provider states, known gaps, **live capability matrix**, simulator limitations, job queue.
2. **Market data** — register an instrument; import a CSV; observe the quality report rejecting a broken
   row; generate synthetic data and see it labelled; set splits; import a corporate action series; freeze
   a dataset and see the checksum.
3. **Simulator** — start a run; Speel/Pauzeer/Stap/snelheid; equity and benchmark curve; decision
   log showing data check, signal, cost assessment and action reason; pick a checkpoint that has an
   engine checkpoint and rewind into a branch that continues to the original end while the original
   stays intact.
4. **Strategy Lab** — register a strategy without a hypothesis and see the refusal; save a new version and
   watch the status fall back to draft; inspect the evidence dossier; attempt promotion without an
   independent pass and see the reason.
5. **Experiments** — preregister a search, start it, inspect every recorded trial.
6. **Validation** — run a validation evaluation; read the folds, deflated Sharpe, intervals and stress
   results; attempt a second sealed-test evaluation for the same version and see it refused.
7. **Agent team** — with no model gateway, the tab reports unavailable with a reason; the deterministic
   services list is shown as outside model control.
8. **Portfolio & risk** — equity, cash per currency, positions, ledger totals; risk preview showing a
   block reason and any stripped override keys.
9. **Orders & execution** — order preview refusing an unsupported combination; order and fill lists for a
   run, including partial fills and reject reasons.
10. **Knowledge** — train a baseline model; see its training cutoff, its training window and whether it
    beats the training-window drift baseline.
11. **Paper desk (legacy)** — labelled educational/in-sample; wallet/orders/kill switch work; discovery
    scores are **not** shown as validated strategies; manual price = `operator_input`.
12. **Settings** — cost model, risk limits, kill switch, network toggle, worker limit, default model, learning autonomy.
13. **Leren** — experiences, beliefs, lineage, cycles and champion/challenger. Autonomy default remains OFF.

**CI note:** GitHub Actions may report red because runners/billing are unavailable
(`BLOCKED_EXTERNAL`). That is **not** a software FAIL. Software PASS is recorded from host/local
gates only.

## 9. What “learning” means in HADES

This is **not** model training, **not** a prompt that says “I learned”, and **not** one profitable trade.

| Concept | What it is | What it is not |
|---|---|---|
| Raw evidence | Immutable decisions, fills, later outcomes, experiment/evaluation rows | Something an LLM may rewrite |
| Experience | Deterministic record: given this context and decision, this later outcome occurred | A belief |
| Aggregated finding | Statistics over similar experiences, with `insufficient_evidence` when n is too small | A licence to trade |
| Belief | Versioned, evidence-backed claim with a confidence *cap* from sample size, split, consistency, recency | An LLM saying “high confidence” |
| Candidate | A new declarative strategy version with lineage | An overwrite of the parent |
| Champion | The strongest *qualified* strategy for a scope | The development-set winner |

Lifecycle now implemented:

Research → hypothesis → candidate → simulation → outcomes → experiences → aggregation → evidence-backed learning → belief update → bounded mutation → development testing → independent validation → champion/challenger → paper (still a separate registry step) → repeat.

A later cycle starts with the belief store already populated. Negative results are first-class: a failed fingerprint is not immediately re-proposed unless the operator labels a replication.

### Autonomy levels

Default is **OFF**. The setting never silently moves upward.

| Level | Automatic behaviour |
|---|---|
| `off` | Nothing automatic. Experiences, beliefs and cycles are operator-triggered. |
| `learn_only` | Ingest experiences, aggregate, update beliefs. No new strategies. |
| `propose` | Also emit bounded candidate versions with lineage. No experiments. |
| `research` | Also run development experiments for those candidates. Validation stays manual. |
| `auto_research` | Also run independent *validation* (not sealed holdout) and compare against the champion. |

Sealed test remains single-use per version via the existing registry gate. A learning cycle never consumes it. Validation evidence does not flow back into development mutation context. If a version is mutated after sealed-test feedback, it is a new version and prior sealed evidence does not transfer (existing registry rule).

### Champion / challenger

Admission requires `validated` or `paper` plus an independent validation evaluation whose verdict is not `fail` / `insufficient_evidence`. Development-only numbers cannot install a Champion. Replacement uses documented weights over existing evaluation fields (net return, Sharpe, drawdown, costs, verdict, optional sealed/paper bonuses) plus a small diversity bonus for a different family or regime specialisation. The risk engine, holdout gate and promotion API are unchanged.

### Token efficiency

Deterministic (no LLM): experience creation, regime features, metrics, grouping, ranking, fingerprints, lineage, confidence caps, validation checks, champion scoring, dedupe.

LLM (optional, Learning Curator and the existing research roles): interpreting aggregates, proposing bounded mutations, explaining contradictions, naming open questions. Agents receive compact retrieved beliefs and finding IDs, not price histories or raw trade dumps.

### Known limitations (learning)

- Counterfactual “what if it had held / exited” replay is **not** implemented in this change; it would be a budgeted engine replay, not invented prices.
- MAE/MFE are stored only when a price path is supplied; otherwise they are explicitly unavailable.
- AUTO_RESEARCH writes evaluations as `automatic_gate`. Champion *replacement* still expects an independent validator role for a true promotion to `validated` through the existing registry.
- Numerical model retraining can be *proposed* as a mutation of `model_signal` parameters; actual `train_model` remains the existing deterministic trainer and is not auto-promoted.

## 10. Remaining blocks

- `event_driven`, `option_volatility` and `market_making` stay blocked until the corresponding data
  exists locally. They refuse to run rather than approximate.
- Market impact of own orders, queue position and intrabar path remain unmodelled; the participation cap
  and the conservative stop-versus-target rule are stand-ins, and both are stated in every report.
- Prospective paper evaluation is a separate evidence class from historical simulation; a strategy that
  passes a historical evaluation is still not promoted on that basis alone.
- Parquet export is only available when `pyarrow` happens to be installed; the native binary store is
  the supported path.
