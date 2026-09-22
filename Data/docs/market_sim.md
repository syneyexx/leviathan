# Market Simulation (EXTERNAL-FIRST)

Causal, multi-agent, brain-connected paper market simulator for LEVIATHAN research.

Feature flag (default **OFF**):

```bash
LEVIATHAN_FEATURE_MARKET_SIM=true
LEVIATHAN_MARKETS_ROOT=D:/ModelData/markets   # optional; defaults to {LEVIATHAN_DATA_ROOT}/markets
```

## Architecture

```
LEVIATHAN CORE (control plane)
  MarketSimControlPlane — config, strategy store, run lifecycle, API
  MarketSimStore — metadata in central leviathan.db
        ↓
MarketSimWorker (execution plane — daemon worker; subprocess-ready)
  SimulationEngine — bar clock, fills, risk
  DeliberationRuntime — multi-agent proposals / veto / vote
  BrainFacade — Neuro / Knowledge / Memory / Evidence (advisory)
        ↓
results / fills / messages / equity / metrics → Core DB
```

**External-first:** heavy bar stepping never blocks HTTP. The worker is the execution unit.
No parallel canonical database. No real broker orders.

## Causality (hard rule)

`SimulationClock` is the only time authority. At bar index `i`, strategies and agents may only
observe bars `0..i`. Look-ahead raises `CausalityViolation` and increments the run counter.
Tests assert future reads fail.

## Real market data

1. Place OHLCV CSV under `LEVIATHAN_MARKETS_ROOT` (e.g. `BTCUSDT_1h.csv`).
2. Required columns: `timestamp,open,high,low,close,volume` (aliases accepted).
3. Open **Marktdata** → Scan / Register. DB stores metadata + content hash only.
4. Parquet is optional; without `pyarrow` the capability reports `PARQUET_UNAVAILABLE`.

Fixture for tests: `Data/backend/tests/fixtures/market_data/BTCUSDT_1h.csv`.

## Strategies

Structured DSL only (`ma_cross`, `mean_reversion`) — **no arbitrary code execution**.
Versioned + content-hashed in `market_strategies` / `market_strategy_versions`.

## Multi-agent deliberation

Default roles: trend, mean_reversion, risk_officer.
Each round: causal state → brain retrieve → proposal → optional veto → vote → risk → fill.
All messages persisted. Brain miss rate is a first-class metric.

## Brain integration

Agents call Knowledge / Memory / Neuro / Evidence facades with provenance labels.
Empty retrieval → agents still act; run records brain-miss.
Neural signals are advisory — never authority. Model output is never evidence.

## API

| Method | Path | Purpose |
|---|---|---|
| GET | `/api/market-sim/status` | Flag + health + worker telemetry |
| GET/POST | `/api/market-sim/data` / `scan` / `register` | Market files |
| CRUD | `/api/market-sim/strategies` | Strategy library |
| POST | `/api/market-sim/runs` + `start/pause/step/stop` | Run control |
| GET | `/api/market-sim/runs/{id}/live` | Clock, equity, fills, messages |

## Frontend

- `/trading` — Simulatie control room (live binding)
- `/trading/strategieen` — strategy library
- `/trading/marktdata` — file index / validation

## What is implemented vs stub

| Implemented | Still stub / out of scope |
|---|---|
| Causal engine, fees/slippage, risk kill-switch | Real broker / live money |
| Strategy store + versioning | Perfect L2 HFT microstructure without L2 files |
| Multi-agent deliberation + brain hooks | Guaranteed alpha |
| Metrics with UNMEASURED honesty | Foundation-model training inside the sim loop |
| Paper fills only | Live paper-trading bridge |

## Dependencies

Uses Python standard library + existing LEVIATHAN stack. No new required packages.
Optional: `pyarrow` for Parquet (undeclared until intentionally adopted).

## Self-review (external execution)

- [x] Heavy execution in worker, not HTTP
- [x] Central DB only; files on disk
- [x] Causality enforced + tested
- [x] Optional feature flag; Core boots without market data
- [x] No second job/approval/persistence system
- [x] Trading stub still refuses real broker orders
