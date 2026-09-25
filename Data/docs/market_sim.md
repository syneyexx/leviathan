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

## Trade orchestras & trading agents (`Data/modules/market_sim/orchestra/`)

Trading-only agents live on the **existing Agent Fleet** as `kind=trading`; a trade orchestra is a fleet
orchestrator with `role=trade_orchestra`. The fleet delegates both to the registered trading executor
(`AgentFleetService.register_kind_executor`), so no second fleet, runtime or scheduler exists.

- **Mandate** (operator-owned limits: universe, paper capital, exposure/risk/orders/drawdown, autonomy
  `A0..A4`, model budget). `cannotEnableLive` is immutable; loosening a mandate needs an approval for
  `market_sim.mandate.loosen`. Stored in the orchestrator's metadata with a fingerprint + history.
- **Deliberation round** (`deliberation_round`): news digest → per-instrument proposals (signal analysts)
  → critique → **deterministic `RiskGuard` decision** → paper order intent (recorded, not routed).
  Agents propose/critique/explain; they never size or approve. Every step is an append-only
  `DecisionRecord` (`market_decisions`, migration 43; UPDATE/DELETE refused by triggers) with `as_of`,
  `mandateFingerprint` and `modelId`.
- **News** (`news_digest`): feeds are fetched only by the `market_sim.news.poll` job through the
  `provider_io` pool; items carry `available_at = max(published, fetched) + declared latency` and are
  invisible to any decision whose `as_of` is earlier. Article text is `<reference_context>` in prompts;
  the news analyst emits schema-validated signals (data, not authority).
- **Learning** (`post_mortem`): lessons are written to Memory as `trust=derived` /
  `trust_state=agent_proposed` with evidence refs to decision ids; never as facts.
- **Model access:** `TradingModelAdapter` → Model Control Plane (`consumer="trading"`,
  `model_role="trading.<role>"`). Without a bound model the round degrades to labelled `tier0_rules`
  proposals or `UNAVAILABLE`; nothing is fabricated. No LLM call happens inside the per-bar kernel.
- **Isolation:** trading agents cannot join non-trading orchestrators and vice versa; generic planners
  refuse `kind=trading` (409 `TRADING_EXECUTOR_REQUIRED`). Chat is not involved.
- **API:** `/api/market-sim/orchestras[/summary|/{id}|/{id}/mandate|/{id}/autonomy|/{id}/missions|/{id}/decisions]`,
  `/api/market-sim/news/{feeds,poll,items,signals}`, `/api/market-sim/decisions`.
- **Readiness:** stays `UNMEASURED` until a sealed evaluation exists (Frontier Program F3); paper PnL is
  only shown when fill records exist.

## Frontend

Trading Center pages bind to live APIs (Simulatie, Strategieën, Marktdata, Paper, Portefeuille, Broker honesty page,
Onderzoek = orkesten + nieuws + beslissingsketen).
Agents fleet page remains the single agent registry; trading roles tag `trading` / `market_sim` and appear in
section 9 (trade orkesten) with mandate, autonomy, readiness and the decision timeline.

## HADES

Submodule at `Data/HADES` inspected. Concepts adapted (next-bar eligibility, risk override sanitizer, provider honesty, Decimal booking). Full `trading_lab` package not vendored.

## Honest limitations

- OHLCV ≠ order book.
- Profitable backtest ≠ profitable live strategy.
- Deterministic DSL ≠ autonomous LLM strategy creation.
- Daemon thread ≠ isolated OS process (subprocess entrypoint available).
- Local paper fills against public quotes are not exchange-matched.
- Live money trading is not implemented.
