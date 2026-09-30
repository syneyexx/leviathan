# Progressive disclosure plan — 4 Trading Center workspaces

Keep the four main screens dense but not overloaded.  
Every COMPLETE operator-relevant capability must be reachable via PRIMARY, SECONDARY, or ADVANCED disclosure — **never** via a fifth page.

---

## Shared: Trading Context Bar (all workspaces)

Always visible under header:

- Mode: Offline / Live / Hybrid (Live means live **data**, never live money)
- Market / Symbol
- Timeframe
- Dataset / Feed
- Regime + Volatility badges (deterministic; HMM not claimed)
- Execution badge: **PAPER ONLY** / live **BLOCKED**

---

## 1. Command Hub

### PRIMARY
- Hero: Autonomous Trading Command Hub + CTAs (new research session, open paper session)
- KPI strip: candidates, experiments, paper sessions, data sources, paper wallets, promotion queue
- Active operations (agent workload table)
- Markt & Regime summary (context for selected market)
- Databronnen live status (summary; detail → Market Data)
- Paper / Research sessions tabs
- Attention / Decisions feed
- Promotion & Control queue (high-level)
- Trading Center Status (engine, network, market data, paper, risk, agents, uptime)
- Live Trading Guard badge

### SECONDARY
- Agent focus (“Wat kijken de agents nu?”)
- Research Command session binder (orchestra + portfolio + lab)
- Watchlist / opportunities / volatility / news tabs
- Thesis / positioning summaries
- Evidence drawer link
- Kill-switch / flatten PAPER controls

### ADVANCED (drawers / tabs / dialogs)
- Institutional Control Room projection (gap matrix, multi-asset, assurance)
- Qualification attention detail (gate failures, blockers)
- Exceptions / reconciliation breaks / audit verify
- Decision ledger browser
- Authority request/approve (when permissioned)
- Full capability / action matrix
- API & event fabric catalog

---

## 2. Strategy Lab

### PRIMARY
- Hero actions: new search, research session, paper validation, compare
- KPI strip: candidates, experiments, research sessions, paper validations, ready for promotion, data sources
- Strategy discovery table (family, metrics, status)
- Validation ladder: Discovered → Researching → Backtesting → Paper Validation → Promotion Ready → Promoted
- Research session list + create/start/pause/resume/cancel
- Historical simulation run control (from legacy Simulatie)

### SECONDARY
- Strategy library / builder / versions (legacy Strategieen)
- Experiment pipeline overview (grid/evolutionary/regime/multi-agent/WFA/OOS/robustness counts)
- Robustness-by-regime heatmap (deterministic regimes)
- Paper validation snapshot for selected strategy
- Strategy families registry

### ADVANCED
- Hypotheses · Perception · Generations · Population · Lineage · Lessons
- Cost pack
- Qualification Q01–Q11 gate inspector
- Walk-forward fold detail
- Out-of-sample / sealed holdout evidence
- Statistical multiplicity evidence (honest UNMEASURED)
- Adversarial robustness evidence
- Execution validity / capacity evidence
- Candidate explainability drawer (`/candidates/{id}/explain`)
- Reproducibility / contamination firewall flags
- Gym episode tooling (if exposed)
- Recent findings / lessons chronologies

---

## 3. Trading Desk

### PRIMARY
- Paper chart workspace (symbols, TF, indicators)
- Wallets (agent + portfolio) — **new first-class panel** (backend COMPLETE, legacy UI weak)
- Positions · Orders · Executions/Fills
- RiskGuard envelope + kill switch
- Portfolio select + lifecycle (start/pause/resume/stop)
- Deploy / Pause / Flatten PAPER
- Orchestrator mode (autonomous / assisted / manual)

### SECONDARY
- Analytics / performance charts
- Allocation views (asset/sector/geography)
- Activity / decision stream (public)
- Open paper deployment list + promote-from-desk (when qualified)

### ADVANCED
- Agent fleet table (orchestra members)
- Orchestra configuration / autonomy / missions
- Allocations save · rebalance preview/execute
- Recommendations · export
- Shadow observe · drift review · execution calibration
- Strategy-risk / portfolio compatibility detail
- Execution diagnostics / sim-to-paper gap
- Optional Alpaca paper broker indicator (secrets present ≠ live)
- Live/broker boundary inspector (read-only BLOCKED)

---

## 4. Market Data

### PRIMARY
- Hero actions: import dataset, manage feeds, certify data, open replay
- KPI strip: offline datasets, live feeds, symbols, timeframes, ingestion jobs, data quality
- Offline dataset library table
- Live feed health table
- Shared context bar market/dataset selection

### SECONDARY
- Symbol coverage matrix
- Regime monitor (deterministic)
- Data quality & gaps panel
- Providers & limits
- Ingestion / sync jobs tabs

### ADVANCED
- Bron provenance / certification audits
- Dataset seal / sealed holdout binding
- Point-in-time fabric / causality evidence
- Replay & sampling configurator (dataset, symbol, period, TF, indicators, realistic latency)
- Scan-batch / profile / convert job detail
- Family capability matrix (equity/crypto COMPLETE; futures/FX hist only; options/FI UNAVAILABLE)

---

## Disclosure anti-patterns (forbidden)

- Creating pages 5–7 for “advanced” topics
- Showing STUB/UNAVAILABLE as green operational widgets
- Inferring capability from screenshot chrome without backend evidence
- Hiding COMPLETE operator capabilities solely because legacy UI lacked a control
