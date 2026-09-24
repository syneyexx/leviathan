# Trading Center — Architecture Map

Status: implemented expansion on feature flag `LEVIATHAN_FEATURE_MARKET_SIM` (default OFF).

## Existing components (reused)

| Component | Path | Role |
|---|---|---|
| Control plane | `Data/modules/market_sim/service.py` | Config, strategy CRUD, runs, paper, experiments, demos |
| Worker | `Data/modules/market_sim/worker.py` | Bar stepping outside HTTP; honest daemon/subprocess telemetry |
| Engines | `engine.py`, `multi_engine.py` | Causal loops; multi-wallet commit-reveal |
| Clock | `causality.py` | Sole time authority |
| Strategy DSL | `strategy_eval.py` | Structured rules only (no `eval`) |
| Deliberation | `deliberation.py` | Legacy shared-book propose/veto/vote |
| Commit-reveal | `commit_reveal.py` | Blind sealed decisions per bar |
| Accounting | `accounting.py` | Decimal wallets |
| Execution | `execution.py` | Next-bar-open fill schedule |
| Risk | `risk_guard.py` | Deterministic veto; override keys blocked |
| Providers | `providers/` | CSV, Binance public, Stooq |
| Paper | `paper_broker.py` | Local paper (+ optional Alpaca paper) |
| Experiments | `experiments.py` | Hypothesis ledger, walk-forward, memory causality |
| Roles | `roles.py` | Fleet role specs for trading |
| Capabilities | `capabilities.py` | Per-market HISTORICAL / PAPER / LIVE status |
| Live guard | `trading_live_guard.py` | Blocks real orders |
| Brain hooks | `brain_hooks.py` | Advisory Knowledge / Memory / Evidence / Neuro |
| Store | `store.py` | Metadata in central `leviathan.db` (+ migration 34) |
| Agent Fleet | `Data/modules/agents/` | Durable agents / missions (no second fleet) |
| Trading stub | `Data/modules/trading/stub.py` | Real orders refused |
| Secrets | `Data/modules/security/secrets_broker.py` | Never log keys |

## HADES submodule

Checked out at `Data/HADES` (`f143707`). Adapted concepts only (license: private/unlicensed root — same-owner reuse). Not adopted: full lab FastAPI surface, binary bar store, options/bonds, live broker (HADES has none).

## Modes

| Mode | Data | Orders | Claim |
|---|---|---|---|
| `historical_backtest` | Stored OHLCV | Simulated next-bar fills | Research only |
| `live_paper` | Live public quotes + paper ledger | Local (or Alpaca paper) | Not real money |
| `live_broker` | — | **Blocked** | Never default-on |

## Proven demos

- Equity: `POST /api/market-sim/demos/run` with `family=equity` (AAPL fixture)
- Crypto spot: `family=crypto_spot` (BTCUSDT fixture)

Both exercise: two trading agents + orchestrator/risk, commit-reveal, isolated wallets, strategy memory after reject, paper session scaffolding.

## Remaining blocked / unproven

- Real broker order placement
- Options / futures / forex end-to-end
- Guaranteed exchange-quality paper fills without broker paper API
- Autonomous LLM strategy invention (deterministic DSL baseline remains)
