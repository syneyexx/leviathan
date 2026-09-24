# Market Simulation & Trading Center

> **Phase T0 (2026-09-24):** Source-verified gap report for the Trading Research Factory program lives in [`trading_gap_report.md`](./trading_gap_report.md). Program plan: [`trading_program.md`](./trading_program.md). Characterization tests: `Data/backend/tests/test_market_sim_characterization.py` (D1–D21). No correctness fixes in T0 — awaiting approval for Phase T1.


Causal, multi-agent market research for LEVIATHAN. Feature flag (default **OFF**):

```bash
LEVIATHAN_FEATURE_MARKET_SIM=true
LEVIATHAN_MARKETS_ROOT=.../markets   # optional
```

## One trading domain

```
verified market data → dataset hash
  → agents design/select DSL strategy
  → structured discussion + risk veto
  → causal backtest (next-bar-open fills)
  → independent validation / walk-forward
  → strategy version + evidence (incl. rejects)
  → live paper (same strategy identity)
  → compare paper vs backtest
  → live broker orders: BLOCKED
```

Shared strategy identity across modes; only datafeed, clock, and order adapter swap.

## Architecture

| Plane | Component |
|---|---|
| Control | `MarketSimControlPlane` — config, CRUD, paper sessions, experiments, demos |
| Execution | `MarketSimWorker` (daemon thread by default; `scripts/market_sim_worker.py` for subprocess) |
| Engines | `SimulationEngine` (legacy shared book) · `MultiAgentEngine` (per-agent wallets + commit-reveal) |
| Data | Files under markets root; metadata in `leviathan.db` |
| Providers | `csv_local`, `binance_public` (data-api.binance.vision), `stooq_public` (daily equities) |
| Paper | `local_paper` ledger; optional `alpaca_paper` when paper secrets present |
| Live | `TradingStub` + `LiveTradingGuard` — always blocked unless a future verified adapter |

## Causality & fills

- `SimulationClock` forbids look-ahead.
- Decisions on bar **T** become eligible on bar **T+1 open** (no same-close fill after observing that close).
- Commit-then-reveal: agents seal intents against a frozen `info_version` before the next market event.
- Brain / strategy memory retrieval is advisory and filtered by `available_at` ≤ decision time.

## Multi-agent wallets

Game modes: `individual_competition`, `shared_portfolio`, `research_tournament`.
Each trading agent has an isolated Decimal wallet (cash, reserved, positions, fees, tx history).
Risk veto cannot be overridden by model metadata keys (`bypass_risk`, `approved_by_model`, …).

## Capabilities (adapter-derived)

`GET /api/market-sim/capabilities` exposes per-family:

- `HISTORICAL_SIM_AVAILABLE`
- `LIVE_PAPER_AVAILABLE`
- `LIVE_TRADING_AVAILABLE`

Equity and crypto spot historical + paper paths are implemented. Options / futures / forex remain `NOT_IMPLEMENTED`. Live trading is always `BLOCKED`.

## API (existing `/api/market-sim/*`)

Adds: providers, capabilities, paper sessions/orders/kill-switch, experiments, demos, live-trading status.
Does **not** create a second overlapping trading API.

## Frontend

Trading Center pages bind to live APIs (Simulatie, Strategieën, Marktdata, Paper, Portefeuille, Broker honesty page).
Agents fleet page remains the single agent registry; trading roles tag `trading` / `market_sim`.

## HADES

Submodule at `Data/HADES` inspected. Concepts adapted (next-bar eligibility, risk override sanitizer, provider honesty, Decimal booking). Full `trading_lab` package not vendored.

## Honest limitations

- OHLCV ≠ order book.
- Profitable backtest ≠ profitable live strategy.
- Deterministic DSL ≠ autonomous LLM strategy creation.
- Daemon thread ≠ isolated OS process (subprocess entrypoint available).
- Local paper fills against public quotes are not exchange-matched.
- Live money trading is not implemented.
