# LEVIATHAN

**Local-first AI control plane, cognitive runtime and operator platform.**

LEVIATHAN is a private AI system built around one coherent runtime rather than a collection of disconnected assistants. It combines model routing, cognitive orchestration, Brain/RAG, durable memory, Neuro/Cortex advisory signals, tools and approvals, specialist agents, external workers, evidence/verification, datasets, training/evaluation, research, coding and market simulation behind a React operator interface.

> Runtime code and tests are the source of truth. Feature availability depends on configuration, provider support and hardware. This README intentionally avoids claiming unavailable integrations or unverified model quality.

## Canonical documentation

`Data/docs/` is intentionally kept small. There are two system references:

- **[Backend architecture & file map](Data/docs/Leviathan_system_backend.md)** — every backend system, canonical owner, runtime flow and where to find it.
- **[Frontend architecture & file map](Data/docs/Leviathan_system_frontend.md)** — routes, pages, API/client structure, components and frontend files.

Machine gate/program state lives next to tests/scripts rather than as extra architecture documents.

---

## What LEVIATHAN contains today

### Cognitive runtime

LEVIATHAN's canonical reasoning/orchestration owner is `CognitiveRuntime`. It works with:

- `TaskModel`;
- Perception;
- `BeliefState`;
- `WorkingMemory`;
- `MetaController`;
- `CognitivePlanner`;
- `ActionSelector`;
- capability discovery/execution;
- agent delegation;
- verification/completion;
- durable experience/persistence.

The older `ReasoningEngine` remains a lightweight intent/complexity/retrieval compatibility layer; it is not a second cognitive runtime.

Current reasoning modes are **FAST, STANDARD, DEEP, MAXIMUM and ADAPTIVE**, with real orchestration budgets for model calls, tools, agents, retrieval, critics, iterations, context and time.

### Brain / RAG / knowledge

The knowledge stack includes:

- one `BrainAccessFacade`;
- document/chunk storage with provenance;
- lexical+dense hybrid retrieval;
- staged retrieval;
- embeddings/reranking where configured;
- Atlas;
- Deep Recall;
- Why Library;
- knowledge assimilation/indexing.

Brain/RAG is retained as a core subsystem. Retrieved content is data/evidence, not automatic system authority.

### Memory

Durable scoped memory is separate from:

- conversation history;
- cognition WorkingMemory;
- Brain/Knowledge documents;
- VerifiedExperience.

This separation is intentional and is preserved by the active reasoning program.

### Neuro / Cortex

Neuro remains part of LEVIATHAN. The current stack includes advisory neural associations, Cortex planning/runtime, process criticism, memory tiers and residual-adapter boundaries. Neuro can influence retrieval, hypotheses and strategy, but neural association is not treated as an exact fact or permission grant.

### Model Control Plane

Models are managed through one Model Control Plane with:

- registry and profiles;
- provider discovery;
- routing;
- inference sessions;
- residency/resource management;
- capability probing;
- downloads/import;
- managed runtime boundaries;
- OpenAI-compatible inference transport.

Supported provider adapters/boundaries include LM Studio, Ollama, OpenAI-compatible backends and local-serving boundaries present in the repository. Actual availability is discovered/reported rather than assumed.

### Tools and side effects

The canonical side-effect boundary is `ExecutionGateway`.

It combines:

- `CapabilityCatalog`;
- FunctionRuntime;
- approvals/policy;
- observations;
- capability receipts;
- file/workspace operations;
- coding tests/Git helpers;
- knowledge/artifact capabilities;
- MCP;
- browser/media/voice paths when enabled.

A model saying it executed something is not proof that it ran.

### Agents, Coding and Research

LEVIATHAN includes:

- AgentRuntime / AgentFleet;
- DAG multi-agent coordination and blackboard;
- CodingControlPlane with workspace/tool/test/patch/verification flows;
- ResearchService with local retrieval, uploads, source quality, claim/evidence/conflict tracking and optional web/provider access.

Cognition can delegate to specialists while remaining the parent orchestration authority.

### Jobs and external workers

Long/heavy work can run outside the main API process through `JobRuntime` and the external worker system. Worker families cover areas such as coding, research, datasets, source ingestion, embeddings, reranking, evaluation, training control, market simulation, provider I/O, MCP, workflows, scheduler and maintenance.

The main process is the **control plane**; workers are the **execution plane**.

### Evidence and verification

LEVIATHAN tracks observations, evidence, execution receipts and verification reports. Core truth rule:

```text
model output != observation
request != authority
execution request != successful side effect
model says done != verified completion
```

### Datasets and training

The dataset stack supports ingest, validation, quality checks, canonicalization, dedupe, PII/contamination handling, shards/splits/mixtures, indexing and export.

The training stack contains SFT/preference/DPO-oriented infrastructure, active-learning and synthetic-data components, lineage/integrity/model registration, worker boundaries and explicit candidate promotion/rollback controls. Training availability still depends on the configured backend/hardware; LEVIATHAN does not silently replace the active model after one successful run.

### Evaluation and release truth

Evaluation has a durable harness/platform, scorecards, paired evaluation and ablations. `UNMEASURED` is not converted into PASS. Release/promotion decisions are intended to consume measured evidence.

### MCP, plugins and runtime modules

LEVIATHAN includes a universal MCP bridge, plugin registry and ModuleManager. MCP tools synchronize into the same capability world and still execute through the canonical gateway/authority path.

### Market Simulation / TradingCenter

LEVIATHAN contains a causal market-simulation and paper-trading environment with strategies, market-data handling, accounting/risk, experiment metrics, trading-only orchestras/agents and Brain/Memory/Neuro hooks.

**No profitability claim is made. Live broker/real-money execution remains deliberately guarded; simulation/paper research is the safe supported posture.**

### Operator frontend

The React/TypeScript/Vite UI currently exposes major surfaces for:

- Chat;
- Coding;
- Tasks;
- Models;
- Agents;
- Training;
- Dataset Management / Offline Datasets;
- Analytics;
- Research;
- Brain;
- Memory;
- Knowledge Library;
- Evidence Vault;
- TradingCenter;
- Media Control;
- Tools;
- MCP;
- Workflows;
- Performance/runtime;
- Settings.

See the [frontend reference](Data/docs/Leviathan_system_frontend.md) for the route and file map.

---

## Architecture at a glance

```text
                              +--------------------+
                              |   React Frontend   |
                              +---------+----------+
                                        |
                                        v
+--------------------------------------------------------------------------------+
|                           FastAPI Control Plane                                |
|                                                                                |
|  Settings/Behavior  ->  CognitiveRuntime  ->  Model Control Plane              |
|                            |        |                 |                        |
|                            |        |                 v                        |
|                            |        |          Model providers/runtime          |
|                            |        |                                          |
|                            |        +--> CapabilityBroker -> ExecutionGateway   |
|                            |                              -> approvals/receipts  |
|                            |                                                   |
|                            +--> Brain/RAG ----+                                 |
|                            +--> Memory        |                                 |
|                            +--> Evidence      +--> Perception/BeliefState       |
|                            +--> Neuro/Cortex  |                                 |
|                            +--> Agents -------+                                 |
|                                                                                |
|  Jobs / Workflows / Research / Coding / Dataset / Training / MarketSim         |
|                 |                                                              |
|                 v                                                              |
|          External Worker Pools                                                 |
|                                                                                |
|  Central SQLite metadata + artifacts + observations + verification             |
+--------------------------------------------------------------------------------+
```

---

## Frontier Reasoning + Inference-Time Compute program

LEVIATHAN is being upgraded **in place**. The program explicitly preserves the existing CognitiveRuntime, Brain/RAG, Memory, Neuro/Cortex, Model Control Plane, tools, agents, workers, Settings, Training and Evaluation systems.

The target combines two axes:

```text
Reasoning depth
  = orchestration compute
  + neural inference-time compute
```

Target work includes provider-native reasoning effort, a local-model test-time-compute fallback, candidate/hypothesis search, critics, stronger verification, capability self-awareness, async cognition, verified experience aggregation and post-training bridges.

**Current-main truth at this README snapshot:** the F0 baseline/audit machinery is merged. F1–F18 are active implementation phases and must not be treated as implemented until their gates/tests pass.

Machine state:

- `Data/backend/tests/frontier_reasoning_gates.json`
- `scripts/verify_frontier_reasoning.py`

---

## Repository layout

```text
LEVIATHAN/
├── Data/
│   ├── backend/        # FastAPI, config, SQLite, migrations, routes, tests
│   ├── frontend/       # React + TypeScript + Vite operator UI
│   ├── modules/        # canonical domain/control-plane modules
│   ├── functions/      # cold-path FunctionRuntime functions
│   └── docs/           # exactly two canonical system references
├── scripts/            # worker/verification/operational helpers
├── leviathan.py        # launcher helper
├── requirements.txt
├── .env.example
├── installer.bat
└── run_leviathan.bat
```

Detailed ownership/file locations: [backend system reference](Data/docs/Leviathan_system_backend.md).

---

## Quick start

### Windows

```text
1. Clone/open the repository.
2. Configure `.env` if non-default model/network/storage settings are needed.
3. Install Python dependencies.
4. Install frontend dependencies under `Data/frontend`.
5. Build the frontend.
6. Start LEVIATHAN with the repository launcher/batch flow.
```

Typical frontend development commands:

```bash
cd Data/frontend
npm install
npm run dev
```

Typical production frontend build:

```bash
cd Data/frontend
npm run build
```

Backend configuration is documented in `.env.example` and the backend reference. Model availability depends on the configured provider/runtime.

---

## Tests

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

Frontier Reasoning verifier:

```bash
python scripts/verify_frontier_reasoning.py
```

Trading verifier:

```bash
python scripts/verify_trading_100.py
```

Verification harnesses intentionally return non-success while required program gates are still open; an unfinished program is not reported as complete.

---

## Runtime truth and limitations

LEVIATHAN is designed to report capability state honestly.

Examples:

- outbound network permission does not automatically mean web search is configured;
- generating code does not require permission to execute it;
- an available tool is not necessarily authorized for a side effect;
- a fixture/stub is not a production integration;
- a model response is not an execution receipt;
- a training recipe existing is not proof a GPU training run completed;
- market simulation does not imply profitable or production-ready live trading.

These distinctions are architectural invariants, not UI wording choices.

---

## Documentation contribution rule

Do not add another architecture/program Markdown file under `Data/docs`.

- Backend/runtime changes → update `Data/docs/Leviathan_system_backend.md`.
- Frontend/routes/UI changes → update `Data/docs/Leviathan_system_frontend.md`.
- Machine gate state → keep it in `Data/backend/tests/*.json` and verification scripts.

This keeps GitHub documentation discoverable while code/tests remain the implementation truth.
