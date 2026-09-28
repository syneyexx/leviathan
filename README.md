# LEVIATHAN

**Local-first AI operating platform: cognitive orchestration, model control, Brain/Knowledge/Memory, governed tools and agents, durable worker execution, research/training, extensible external capabilities, and institutional-grade market research with autonomous paper trading.**

LEVIATHAN is not a single chatbot around an LLM. It is a layered control system that separates **reasoning**, **evidence**, **model inference**, **technical authority**, **durable execution** and **operator truth**.

The repository currently combines:

- a FastAPI control plane;
- a CognitiveRuntime with adaptive reasoning, planning, critics, TEAM collaboration and verification;
- a Model Control Plane for routing, residency, serving and measured capabilities;
- Brain/RAG, Knowledge, Memory, Evidence and Neuro/Cortex subsystems;
- a central ExecutionGateway with approvals, receipts and idempotency;
- Agent Fleet, Coding Agent and deep Research runtimes;
- JobRuntime + Worker Fabric for durable heavy work;
- datasets, document ingestion, training, evaluation and release controls;
- ModuleManager, Plugins, MCP, Skills and a generic external capability fabric;
- three canonical SQLite data domains — CONTROL, KNOWLEDGE and MARKET;
- a causal MarketSim platform with autonomous strategy discovery, scientific qualification and paper-forward continual research;
- a React/TypeScript operator console covering all major control surfaces.

> **Product-truth boundary:** LEVIATHAN deliberately distinguishes configured, available, measured, verified and qualified state. `UNMEASURED` is not PASS. A model saying it did something is not an execution receipt. Historical trading profitability is not a future guarantee. **Real-money autonomous trading remains BLOCKED.**

---

## Canonical system documentation

There are two canonical human-readable LEVIATHAN architecture references:

- **[Backend A–Z](Data/docs/Leviathan_system_backend.md)** — FastAPI composition, APIs, databases, cognition, models, Brain/RAG, Memory, workers, agents, research, datasets, training/evaluation, modules, security, MarketSim, verification and exact file ownership.
- **[Frontend A–Z](Data/docs/Leviathan_system_frontend.md)** — React bootstrap, AppShell, routes, navigation, API clients, state, every major page family, styles/tests and exact frontend file ownership.

Machine state stays in tests/manifests/verifiers rather than competing architecture documents.

---

## Architecture at a glance

```text
                                  OPERATOR
                                     |
                              React / TypeScript
                                     |
                                     v
+----------------------------------------------------------------------------------+
|                           FASTAPI CONTROL PLANE                                  |
|                           Data/backend/main.py                                   |
|                                                                                  |
|  Settings / BehaviorProfile                                                      |
|          |                                                                       |
|          v                                                                       |
|  CognitiveRuntime ------> Brain facade ------> Knowledge / RAG                   |
|       |      |               |              -> Memory                            |
|       |      |               |              -> Evidence                          |
|       |      |               +--------------> Neuro / Cortex (advisory)          |
|       |      |                                                                      |
|       |      +----------> Model Control Plane -> model providers / residency     |
|       |                                                                          |
|       +-----------------> CapabilityBroker -> ExecutionGateway                   |
|                                                |                                 |
|                                                +-> approvals / receipts          |
|                                                +-> functions / MCP / modules      |
|                                                                                  |
|  Agents / Coding / Research / Datasets / Training / MarketSim / Workflows       |
|                       |                                                          |
|                       v                                                          |
|                  JobRuntime                                                      |
+-----------------------|----------------------------------------------------------+
                        v
                 WORKER FABRIC
        heavy CPU / I/O / GPU / provider / commit jobs
                        |
          +-------------+-------------+
          |             |             |
          v             v             v
       CONTROL       KNOWLEDGE       MARKET           + ArtifactStore
        SQLite         SQLite         SQLite
```

The system intentionally avoids parallel owners: one CognitiveRuntime, one Model Control Plane, one canonical ContextBuilder, one ExecutionGateway, one JobRuntime/Worker Fabric, one Agent Fleet, one ModuleManager fabric and one MarketSim trading/research authority.

---

## Core systems

### CognitiveRuntime and TEAM

The deep reasoning path lives under `Data/modules/cognition/`. It maintains typed tasks, perception/belief state, bounded working memory, planning/replanning, action selection, capability discovery, model/tool/agent loops, critics/hypothesis search, verification and durable checkpoint/resume.

Reasoning depth and neural inference compute are separate control axes. TEAM mode adds task-aware specialist collaboration and quality contracts; lightweight conversation does not inherit the same strict artifact criteria as coding/research/quantitative work.

LEVIATHAN exposes **public operational reasoning metadata**, not private chain-of-thought.

### Brain, Knowledge, Memory and Evidence

These are different systems by design:

- `Data/modules/brain/` — unified access facade;
- `Data/modules/knowledge/` — documents, chunks, hybrid retrieval, embeddings, DeepRecall/Atlas/Why;
- `Data/modules/memory/` — durable scoped memories with trust/correction state;
- `Data/modules/evidence/` — evidence/verification records;
- `Data/modules/observations/` — tool/capability observations and receipts;
- `Data/modules/neuro/` — advisory Cortex/association/residual system.

Retrieved or model-generated text is data, not instruction authority.

### Model Control Plane

`Data/modules/models/` owns registry, routing, measured capability profiles, hardware placement, residency and model sessions. `Data/modules/model_runtime/` owns provider dialects, inference contracts, streaming and managed serving.

Consumers — Chat/Cognition, Coding, Trading, Research — use this central plane rather than creating private Ollama/OpenAI clients.

A listed model is not automatically resident or capable. Vision/tool/reasoning support comes from measured capability state.

### ExecutionGateway and approvals

`Data/modules/execution/` is the single capability side-effect gateway. It provides risk metadata, authorization, idempotency and receipts. `Data/modules/approvals/` owns technical approvals.

```text
model proposes action
      |
      v
CapabilityBroker / catalog
      |
      v
ExecutionGateway
      |
      +--> permission / approval / risk / idempotency
      |
      v
Function | MCP | Module | Agent | domain handler
      |
      v
receipt / observation / artifact
```

A UI/model/request flag cannot self-grant authority.

### JobRuntime and Worker Fabric

`Data/modules/jobs/` owns durable job state, leases, retries, priorities, cancellation and resource declarations. `Data/modules/workers/` is the managed external execution plane.

Heavy coding, research, datasets/documents, embedding/rerank, training/evaluation, market simulation, MCP/module work, source ingestion, provider I/O, model download, maintenance and DB commit workloads can run outside the FastAPI request process.

Production startup proves API liveness before spawning WorkerSupervisor. Workers are not READY until registration + heartbeat are proven. Lease fencing prevents a stale worker from overwriting a newer result.

### Agents and Coding

`Data/modules/agents/` contains the Agent Fleet, governance, multi-agent orchestration and Signal Fabric. Signal Fabric is coordination over the existing Agent/Job/Memory/Execution architecture, not a second runtime or database.

`Data/modules/coding/` is the coding specialist. Code writes/tests are receipt-backed and remain subject to workspace/approval/execution rules.

### General Research

`Data/modules/research/` provides durable research projects with planning, local retrieval, optional web search/fetch, source snapshots, claims/evidence/conflicts, report generation, citation/quality checks and Brain/Knowledge assimilation.

Web permission, web-search configuration and successful evidence retrieval are separate states. Search hit ≠ fetched source ≠ evidence ≠ supported claim.

### Datasets, training and evaluation

The dataset/document stack supports ingest, quality/state tracking, canonical versions, indexing, offline workflows and Knowledge integration. Training/evaluation systems provide durable recipes/jobs, post-training candidates, evaluation/ablation/scorecards and guarded promotion/rollback paths.

A training recipe existing is not proof a model was trained; release/promotion consumes measured evidence.

---

## External capability fabric

LEVIATHAN includes one generic ModuleManager fabric under `Data/modules/module_manager/` with declarative external sources in `Data/external_capabilities/`.

Supported adapter families include:

- CLI;
- Model Context Protocol (MCP);
- owned process/service;
- HTTP/OpenAPI;
- skill packs;
- large catalogs;
- composite modules.

The design intentionally avoids a bespoke wrapper class for every external repository.

### Dependency-aware installation

Module installation is a single controlled flow:

```text
plan
 -> resolve declared system/runtime/app dependencies
 -> identify package manager / privilege requirements
 -> approval for privileged changes
 -> persist install operation
 -> fetch/stage
 -> install runtime/app deps
 -> post-install
 -> verify/re-probe
 -> promote version
 -> READY or typed failure
```

The backend `InstallationService` is the authority. Production installs normally execute through JobRuntime/Worker Fabric; synchronous fallback is default-off. Version activation/rollback, idle process sweep, logs/jobs/health and execution are all part of the same ModuleManager surface.

External finance/trading modules may provide analytics/research capabilities but cannot bypass MarketSim into real-money execution.

---

## Exactly three canonical databases

LEVIATHAN’s product metadata is split by ownership rather than stored in one ever-growing SQLite file:

| Database | Owns |
|---|---|
| **CONTROL** | settings, jobs/leases, runtime/control state, module/plugin/external lifecycle, approvals and similar metadata |
| **KNOWLEDGE** | documents/chunks/retrieval/knowledge-side durable records |
| **MARKET** | market data/simulation/strategy research/qualification/paper state |

Canonical paths are configured with `LEVIATHAN_CONTROL_DATABASE_PATH`, `LEVIATHAN_KNOWLEDGE_DATABASE_PATH` and `LEVIATHAN_MARKET_DATABASE_PATH`. Legacy `LEVIATHAN_DATABASE_PATH` is migration input, not post-cutover authority.

Table ownership is declared in `Data/backend/table_ownership.py`; fresh/cutover/domain migration logic is in `Data/backend/db_upgrade.py`. Heavy canonical mutations use the DB Commit Coordinator where required. SQLite Manager can inspect/control all three but is not a fourth store or migration authority.

---

## MarketSim / Trading Research

LEVIATHAN contains a causal market research/simulation environment under `Data/modules/market_sim/`.

It is more than a backtester: current main includes an autonomous research closed loop that can start from either an existing strategy or a research objective without a manual seed.

```text
historical/versioned market data
        |
        v
causal perception (as_of firewall)
        |
        +--> canonical numerical features / regimes
        +--> optional chart-vision observation (advisory)
        |
        v
falsifiable research hypotheses
        |
        v
Trading research agents + adaptive evolutionary learner
        |
        +--> agent-proposed candidates
        +--> mutation / crossover / exploration
        +--> candidate dedup / lineage
        |
        v
MarketSim trials
        |
        v
TRAIN -> validation -> walk-forward -> regime/robustness -> SEALED
        |
        v
QualificationAuthority Q01..Q11
        |
        v
qualified StrategyAsset
        |
        v
shadow / autonomous PAPER
        |
        v
forward evidence + drift
        |
        v
ContinualResearchTicket -> linked new Research Lab
```

### Scientific authority

Qualification remains deterministic/evidence-driven. The fixed institutional gate sequence covers data certification, reproducibility, baseline acceptance, walk-forward, multiplicity, regime matrix, adversarial robustness, execution validity, capacity, sealed holdout and portfolio compatibility.

The learner does **not** equate win rate with profitability. Post-cost expectancy, payoff structure, drawdown, stability, sample adequacy, regime/cost/parameter sensitivity and other measured economic evidence matter. A 70% win-rate system can still be rejected if its losses destroy net expectancy.

SEALED data is protected from adaptive reuse within the contaminated lineage. Chart vision follows the same causal `as_of` firewall and is advisory only.

### Paper only

Paper/shadow modes use simulated capital, durable sessions, deterministic RiskGuard and kill switches. Forward evidence must be sufficiently large before PASS/FAIL conclusions.

**Real-money live trading is BLOCKED by construction.** A5 is intentionally impossible; Broker UI/external modules do not override this boundary.

---

## Operator frontend

The React UI under `Data/frontend/` exposes current surfaces for:

- Command/dashboard and Tasks;
- Chat/Cognition/TEAM;
- Coding Agent;
- Models/providers/residency/serving;
- Agents and Worker Fabric;
- Training, Dataset Management and Offline Datasets;
- Analytics and performance;
- General Research;
- Brain, Memory, Knowledge and Evidence;
- Trading simulation, strategies, market data, portfolio, paper, guarded broker, Research Command, autonomous Research Lab and institutional Control Room;
- Media Control;
- Tools, Modules, Skills, MCP and Workflows;
- SQLite/runtime/operator console;
- Settings.

Route/file ownership is documented in the [frontend reference](Data/docs/Leviathan_system_frontend.md).

---

## Security and authority model

LEVIATHAN is local-first, not “trust everything on localhost forever.” Current backend includes a centralized mutation policy: loopback mutation follows local policy; non-loopback `/api` mutations require the configured operator token, and unsafe startup fails closed.

Other important boundaries:

- approvals are code-enforced and can be bound to exact operation arguments;
- web/news/tool/MCP/module/model output is untrusted data;
- private-host/network access uses trusted policy rather than request booleans;
- secrets are brokered/leased and should not appear in public telemetry;
- stale worker writes are lease-fenced;
- restore uses maintenance/recovery fencing;
- hidden chain-of-thought is not persisted/exposed;
- trading real-money execution is blocked independently of generic tool approval.

---

## Repository layout

```text
LEVIATHAN/
├── Data/
│   ├── backend/                 # FastAPI composition, config, DB ownership/upgrades, routes, tests
│   ├── docs/                    # exactly two canonical system references
│   ├── external_capabilities/   # declarative external module manifests/catalog
│   ├── frontend/                # React + TypeScript + Vite operator UI
│   ├── functions/               # cold FunctionRuntime implementations
│   ├── launcher/                # native backend host / process supervisor
│   ├── modules/                 # canonical domain/control-plane modules
│   ├── native/                  # native/Rust compute/data-plane boundary
│   └── HADES/                   # separate submodule/boundary, not a core LEVIATHAN owner
├── editor/                      # separate editor product tree
├── scripts/                     # verifiers, worker helpers, operational tooling
├── leviathan.py                 # canonical Python entrypoint
├── requirements.txt
├── .env.example                 # environment/configuration catalogue
├── installer.bat
├── build_run_leviathan_exe.bat  # build native backend host on Windows
├── run_leviathan.bat            # exe-first launcher / legacy-console fallback
└── run_leviathan_workers.bat    # manual WorkerSupervisor recovery path
```

For exact backend file ownership, use the [Backend A–Z reference](Data/docs/Leviathan_system_backend.md).

---

## Quick start

### Source/frontend development

```bash
# Python dependencies
pip install -r requirements.txt

# Frontend development
cd Data/frontend
npm install
npm run dev
```

Production frontend build:

```bash
cd Data/frontend
npm run build
```

Configure non-default model/provider/network/storage/runtime settings through `.env` (see `.env.example`) and/or the Settings Control Plane.

### Windows launcher

`run_leviathan.exe` is the native **backend host**. It supervises the existing Python runtime; it is not a separate frontend. When the exe is absent, `run_leviathan.bat` provides the normal fallback path.

Build the host with:

```text
build_run_leviathan_exe.bat
```

The host build requires Node.js 20+, Rust, Visual Studio C++ build tools and WebView2. Source installs do not require Rust merely to run the Python backend/frontend.

`run_leviathan_workers.bat` is the manual WorkerSupervisor recovery path. Safe Mode is a process-local API-only profile and does not rewrite `.env`.

Default local UI/API binding is configured by settings (commonly `http://127.0.0.1:8765/`).

---

## Tests and verification

Backend:

```bash
python -m pytest Data/backend/tests -q
```

Frontend:

```bash
cd Data/frontend
npm test
npm run typecheck
npm run lint
npm run build
```

Major verifiers:

```bash
python scripts/verify_leviathan.py --allow-incomplete --write-report
python scripts/verify_frontier_reasoning.py --allow-f0-skeleton-only
python scripts/verify_trading_100.py --allow-incomplete
python scripts/verify_trading_100.py --strict --run-tests
```

Machine manifests intentionally remain conservative: an unfinished or externally unmeasured gate is not reported complete simply because a file exists or another subsystem is green.

Notable machine sources include:

- `Data/backend/tests/frontier_reasoning_gates.json`;
- `Data/backend/tests/trading_gates.json`;
- `Data/backend/tests/trading_completion_report.json` (generated by verifier);
- `Data/backend/tests/production_quality_program.json`;
- `Data/backend/tests/` executable regression/architecture tests.

---

## Runtime truth and limitations

LEVIATHAN is designed to say what it knows rather than infer success from configuration.

Examples:

- outbound network allowed ≠ web search configured;
- web search result ≠ fetched/evidenced claim;
- model registered ≠ model resident;
- model response ≠ successful side effect;
- tool listed ≠ tool approved;
- worker process started ≠ READY heartbeat;
- dataset file exists ≠ dataset learned/indexed;
- training recipe exists ≠ training completed;
- module discovered ≠ installed/READY;
- chart pattern predicted ≠ deterministic market fact;
- TRAIN backtest green ≠ validation/SEALED/qualification;
- paper-forward sample too small ≠ stable edge;
- market simulation/paper profit ≠ guaranteed future profitability;
- paper/broker UI presence ≠ permission for real-money trading.

These distinctions are architectural invariants, not cosmetic wording.

---

## Documentation contribution rule

Do not add a new competing LEVIATHAN architecture/program document under `Data/docs`.

- Backend/runtime/system changes → update `Data/docs/Leviathan_system_backend.md`.
- Frontend/routes/UI/API-presentation changes → update `Data/docs/Leviathan_system_frontend.md`.
- Cross-cutting changes → update both.
- Machine gate/readiness state → update its JSON/test/verifier, not prose alone.
- Generated reports → regenerate through the owning verifier.

The goal is simple: **Cursor and human maintainers should be able to understand where any LEVIATHAN responsibility lives by starting with these two documents, while executable code/tests remain the final implementation truth.**
