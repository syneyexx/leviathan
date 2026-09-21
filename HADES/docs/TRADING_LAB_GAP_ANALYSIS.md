# HADES Trading Lab — gap analysis on main

Base commit inspected: `777adc27914823a99144876c433318e30c2e225e` (`main`, "HADES-10: Chat-primary product completion + Phase 10 certificate (#115)").

Read set: `backend/trading_service.py`, trading tables/migration 6 in `backend/platform_db.py`,
`/api/trading*` routes in `backend/main.py`, trading types/methods in `lib/hades-api.ts`,
`components/hades/pages/trading-page.tsx`, `components/hades/obsidian/pages/trading-obsidian.tsx`,
`backend/tests/test_api.py::test_trading_dashboard_seed_discover_and_paper_flow`,
`backend/tests/test_audit_full_repo_static_2026.py`, `backend/tests/test_audit_trading_disabled_honesty.py`,
`backend/reasoning/specialists.py` (`trading_specialist`), `docs/CURSOR_PAGE_INVENTORY.md`, `docs/HADES_CODEBASE_MAP.md`.

## Re-verified findings

| ID | Claim | Verdict on main | Evidence |
|---|---|---|---|
| A | `PaperTradingService` is a spot/long-only simulator with a single USDT wallet | **Confirmed** | `paper_positions.side CHECK(side IN ('long'))`, `paper_wallets` seeded only with `USDT`, `buy()`/`close()` are the only execution paths (`trading_service.py:71-191`) |
| B | `STRATEGY_KINDS` = `sma_crossover`, `momentum`, `mean_reversion` | **Confirmed** | `TradingBotService.STRATEGY_KINDS` (`trading_service.py:197`) |
| C | `discovery_grid` has 13 fixed parameter combinations | **Confirmed** | 5 SMA + 4 momentum + 4 mean-reversion = 13 (`trading_service.py:678-686`) |
| D | Backtest computes the signal from the close and trades on that same close | **Confirmed** | `signals_for(...)` indexes bar `i` closes, and the fill in the same loop iteration uses `price = float(bar["close"])` of bar `i` (`trading_service.py:598-631`) |
| E | No fees, spread, slippage or partial fills | **Confirmed** | `backtest()` moves the full `cash * position_fraction` at the raw close; no cost terms exist anywhere in the module |
| F | Strategies are selected on the same data their performance was measured on | **Confirmed** | `discover_strategies()` scores every grid entry on the identical `bars` list and returns the top N; there is no split |
| G | Sharpe proxy hardcodes `sqrt(24 * 365)` | **Confirmed** | `trading_service.py:654` — applied regardless of the run's `timeframe` |
| H | The paper bot applies one last signal per run, not a chronological learning simulation | **Confirmed** | `execute_paper_bot_step()` uses `signals[-1]` / `closes[-1]` only (`trading_service.py:745-783`) |
| I | Knowledge ingest stores reports; it does not prove a trained model or validated market knowledge | **Confirmed** | `ingest_learning()` writes a markdown summary as a knowledge source; no model weights, no held-out validation |
| J | `list_symbols` uses `MAX(close)` as `last_close` | **Confirmed — fixed in this change** | `trading_service.py:209` selected `MAX(close) AS last_close`, which returns the highest close in the group rather than the chronologically last one |
| K | CSV validation is incomplete | **Confirmed — hardened in this change** | `import_csv()` only checked float-parsability and `min(...) > 0`: no finite check (`float("inf")` parses), no timestamp normalisation, no OHLC consistency (`high >= max(open, close)`), no duplicate detection, and the positive-price rule is wrong for instruments that can print ≤ 0 |
| L | Manually entered simulation prices are treated like real broker fills | **Confirmed** | `/api/trading/buy` accepts an arbitrary `price` and books it as a `filled` order with no cost model or provenance marker |

Additional problems found while reading, not in the original list:

| ID | Problem | Evidence |
|---|---|---|
| M | `get_bars` returns the *newest* N bars (`ORDER BY ts DESC LIMIT ?` then reversed), so a "backtest over 5000 bars" silently becomes a recency-biased window with no manifest | `trading_service.py:214-239` |
| N | `ts` is stored as free text and ordered lexicographically; a CSV with mixed offsets (`...+02:00` vs `...Z`) or `YYYY/MM/DD` sorts wrongly and `MIN/MAX(ts)` becomes meaningless | `market_bars.ts TEXT`, `bars.sort(key=lambda item: item.ts)` |
| O | `PaperTradingService.reset()` deletes all orders, positions and events; there is no audit-preserving alternative | `trading_service.py:108-120` |
| P | The `score` used for selection mixes return, Sharpe, drawdown and win rate into one scalar with magic weights and is persisted as the promotion signal (`status='active'` for rank 1) | `trading_service.py:659`, `persist_discovered()` |
| Q | `TradingJobRunner._run` re-runs a `failed`/`cancelled` run from scratch with no idempotency key; a retry after partial Knowledge ingest can create a second knowledge source and a second set of strategies | `trading_service.py:848-873` |
| R | Equity-curve drawdown is measured against `starting_balance` as the initial peak, so an immediate loss is attributed correctly, but the *recovery duration* and tail metrics required for admission are absent entirely | `backtest()` returns only `max_drawdown` |

## What this change does about it

`backend/trading_lab/` is a new, additive subsystem. The existing `PaperTradingService`,
`TradingBotService`, `TradingJobRunner`, migration 6 tables and all `/api/trading*` routes stay
byte-compatible so the current Paper flows, the `trading_specialist` agent and the existing tests keep
working. Two defects are fixed in place because they are wrong answers rather than missing features:

- **J** — `list_symbols` now returns the chronologically last close (per-group correlated subquery on the
  normalised timestamp), plus `last_close_ts` so the UI can show which observation it came from.
- **K** — `import_csv` now rejects non-finite values, normalises timestamps to UTC ISO-8601, enforces
  OHLC consistency, rejects duplicate timestamps, and delegates the price-sign rule to the instrument
  registry instead of assuming every price is positive.

Everything else is implemented in the new subsystem rather than by inflating `trading_service.py`:

| Finding | Where it is addressed |
|---|---|
| A | `trading_lab/adapters.py` (nine instrument families, long/short), `trading_lab/accounting.py` (multi-currency Decimal ledger) |
| B | `trading_lab/strategies.py` (twelve strategy families with declared data requirements) |
| C | `trading_lab/research.py` (bounded grid / random / sequential-refinement search with a recorded budget) |
| D | `trading_lab/clock.py` (`SimulationClock`, `PointInTimeGateway`) + `trading_lab/engine.py`: an intent raised from bar *i* can only fill on an event strictly after `available_at(i)` |
| E | `trading_lab/execution.py` (spread, fees with minimums, slippage, latency, participation-capped partial fills, rejects, expiry) |
| F | `trading_lab/evaluation.py` + `trading_lab/registry.py` (chronological dev/validation/sealed splits, holdout isolation, independent evaluator actor) |
| G | `trading_lab/evaluation.py::periods_per_year` (timeframe × trading calendar) |
| H | `trading_lab/engine.py` (full chronological event loop with play/pause/step/speed, checkpoints and rewind branches) |
| I | `trading_lab/research.py` separates knowledge capture, strategy search and explicit model training; `trading_lab/models.py` versions preprocessing, features, labels and weights |
| L | `trading_lab/execution.py` is the only writer of fills; `OrderIntent` carries no price guarantee, and manual tickets are marked `price_source="operator_input"` |
| M, N | `trading_lab/bar_store.py` (partitioned, streamed, chronological reads bound to a `DatasetManifest`), `trading_lab/data_quality.py` (timestamp normalisation) |
| O | `trading_lab/store.py` keeps an append-only `lab_ledger_entries` / `lab_order_events` audit trail; resets create a new account version instead of deleting history |
| P | `trading_lab/evaluation.py` reports the individual criteria and an explicit `insufficient_evidence` verdict; no single magic score gates promotion |
| Q | `trading_lab/jobs.py` (idempotent `job_key`, resumable checkpoints, no duplicate bookings after restart) |
| R | `trading_lab/evaluation.py` adds drawdown recovery duration, tail risk, turnover, concentration and stability-by-period |
