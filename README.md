# LEVIATHAN

**A local-first AI control plane for models, agents, knowledge, research, coding, training, tools and durable execution.**

LEVIATHAN is an actively developed AI system built around a Python control plane, a React/TypeScript operator interface, local persistence, explicit capability boundaries, and honest runtime state.

The project is designed to become a single environment in which local models, tools, datasets, research workflows, coding agents, training jobs and future specialized workers can be managed through shared infrastructure instead of separate one-off systems.

> **Project status:** active development. Several core subsystems are already real and wired end-to-end; other product surfaces are still experimental, visual-only, or intentionally stubbed. This README distinguishes between them.

---

## What LEVIATHAN is today

At its current stage, LEVIATHAN includes a real local application stack with:

- **FastAPI control plane** for APIs, lifecycle and service composition
- **React 19 + TypeScript + Vite** frontend
- **SQLite persistence** with versioned migrations
- **OpenAI-compatible model runtime** designed for local endpoints such as LM Studio
- **Model Control Plane** with providers, discovery, profiles, routing, gateway state and capability probing
- **Persistent chat** with reasoning metadata, Knowledge retrieval and model routing
- **Knowledge V2** with documents, chunks, provenance, ingest state and lexical retrieval
- **Datasets subsystem** for local upload/import, Hugging Face materialization, validation, transforms, splits, export and Knowledge indexing
- **Training subsystem** with hardware/preflight inspection, durable jobs, LoRA/QLoRA worker paths, metrics, checkpoints, recovery, evaluation and trained-artifact registration
- **Research subsystem** with persistent projects, local retrieval, optional web research, sources, evidence, claims, conflicts and report export
- **Coding Agent** with isolated workspace rules, background execution, capability-driven file operations, test execution, patches and approval-gated writes
- **Execution Gateway** and capability catalog for controlled side effects
- **Approvals and policy** for privileged operations
- **Durable Jobs, Runs, Observations, Artifacts, Evidence and Verification**
- **Memory** as a separate controlled persistence domain
- **Workflows and schedules** built on shared runtime primitives
- **Agent runtime** and multi-agent coordination foundations
- **Neuro Layer** experiments for advisory signals, cortex/critic interfaces, memory tiers and optional residual-runtime adapters
- **Universal Module Manager** with optional subprocess isolation
- **Backup, metrics, security posture, release gates and resilience helpers**

The guiding rule is simple: **the UI should reflect backend truth**. LEVIATHAN avoids presenting unavailable providers, fake telemetry, fabricated research sources or simulated completion as real success.

---

## Current product surfaces

### Fully wired / operational foundations

| Area | Current state |
|---|---|
| Chat | Persistent conversations, Knowledge context, reasoning metadata and real model calls |
| Models | Provider management, discovery, profiles, routing, gateway, probes, test inference |
| Datasets | Import, materialize, inspect, prepare, transform, split, export, Knowledge indexing |
| Model Training | Preflight, hardware planning, durable jobs, LoRA/QLoRA paths, checkpoints, evaluation |
| Research | Projects, plans, local evidence pipeline, optional web provider, reports and exports |
| Coding Agent | Persistent sessions, workspace tools, patches, tests, approvals and verification loop |
| Knowledge | Durable documents/chunks, ingest, provenance and retrieval |
| Execution | Capabilities, gateway, policy, approvals, jobs, effects and observations |
| Evidence / Verification | Artifact/file/observation evidence and evidence-based verification |
| Memory | Controlled durable memory with search and context integration |
| Workflows / Schedules | Durable workflow execution and scheduled triggers |

### Foundations present, still evolving

- Agent orchestration and multi-agent specialization
- Neuro/cortex/critic experiments
- Module subprocess isolation
- Evaluation and release-gate infrastructure
- Runtime metrics and operator status surfaces
- Tool/plugin catalog integration

### Not yet production-complete

Some visible areas are currently shells, prototypes, honest stubs, or partially wired operator surfaces. In particular, the repository does **not** currently claim production-ready:

- browser automation runtime
- media publishing/automation runtime
- voice runtime
- native/C++ execution runtime
- live trading execution
- full trading simulation stack
- full MCP network client/runtime
- managed llama.cpp runtime
- production GPU residual hooks
- production authentication / internet-facing deployment perimeter
- chat token streaming over SSE
- cloud backup/sync or production APM

If a capability is unavailable, the intended behavior is to report it as unavailable rather than fabricate success.

---

## Architecture

```text
                         LEVIATHAN
                             │
                  React / TypeScript UI
                             │
                        typed API
                             │
                     FastAPI control plane
                             │
       ┌─────────────────────┼─────────────────────┐
       │                     │                     │
       ▼                     ▼                     ▼
   Model System         Execution Layer       Data / Intelligence
       │                     │                     │
 Registry / Router      Capabilities           Knowledge
 Gateway / Profiles     Policy / Approvals      Memory
 Providers              Jobs / Observations     Datasets
       │                Evidence / Verify        Research
       │                     │                  Training
       └─────────────────────┴─────────────────────┘
                             │
                         SQLite +
                     filesystem artifacts
```

LEVIATHAN intentionally keeps important concerns separate:

```text
model output        != evidence
request             != authority
dispatch            != completion
persisted status    != current runtime truth
unmeasured          != passed
```

### Core design principles

- **Python-first:** orchestration, APIs, reasoning, persistence and intelligence systems live primarily in Python.
- **Local-first:** the default runtime binds to loopback and works with local model endpoints.
- **Single control plane:** models, tools, jobs, approvals, evidence and state should not each invent a separate runtime.
- **One persistence architecture:** durable domain state is kept in the central SQLite architecture plus registered filesystem artifacts.
- **Capability-driven execution:** privileged work flows through explicit capability, policy and approval boundaries.
- **Truthful failure:** offline or unsupported functionality stays offline or unsupported in the UI/API.
- **Modular growth:** large domains live under `Data/modules/`; small cold-path helpers live under `Data/functions/`.
- **External-worker direction:** heavy, crash-prone or specialized workloads are intended to move behind supervised worker/runtime boundaries instead of bloating the core process.

---

## Repository layout

```text
LEVIATHAN/
├── Data/
│   ├── backend/          # FastAPI control plane, config, DB, migrations, routes, tests
│   ├── frontend/         # React + TypeScript + Vite operator UI
│   ├── modules/          # Stateful/domain subsystems
│   ├── functions/        # On-demand reusable execution functions
│   └── docs/             # Architecture, build history and operator documentation
├── .env.example
├── requirements.txt
├── installer.bat
├── run_leviathan.bat
├── leviathan.py
└── README.md
```

Important documentation:

- [`Data/docs/buildplan.md`](Data/docs/buildplan.md) — chronological implementation record
- [`Data/docs/leviathan_system.md`](Data/docs/leviathan_system.md) — current architecture and runtime truth
- [`Data/docs/cursor.md`](Data/docs/cursor.md) — repository ownership map
- [`Data/docs/models_datasets_training_research.md`](Data/docs/models_datasets_training_research.md) — operational guide for those subsystems
- [`Data/docs/neuro_layer_architecture.md`](Data/docs/neuro_layer_architecture.md) — Neuro Layer architecture and limitations

---

## Technology stack

### Backend

- Python 3.11+
- FastAPI
- Uvicorn
- Pydantic
- HTTPX
- SQLite
- python-dotenv

### Frontend

- React 19
- TypeScript 5
- Vite 7
- React Router
- Vitest
- oxlint

### Optional ML / training environment

Training support can use optional packages such as:

- PyTorch
- Transformers
- Datasets
- Accelerate
- PEFT
- bitsandbytes
- Safetensors
- Tokenizers
- PyArrow

These are intentionally not required for the lightweight core API to start. Training capability detection reports missing requirements instead of crashing the entire application.

---

## Quick start

### Requirements

- **Python 3.11+**
- **Node.js 20+**
- A local OpenAI-compatible model server is recommended for chat/model features

LM Studio works with the default local endpoint configuration.

### Windows

The easiest setup path is:

```text
1. Run installer.bat
2. Configure .env if needed
3. Run run_leviathan.bat
4. Open http://127.0.0.1:8765/
```

`installer.bat` creates the Python virtual environment, installs core Python packages, installs frontend dependencies, builds the frontend, creates local data directories and creates `.env` from `.env.example` when needed.

### Manual setup

```bash
python -m venv .venv
```

Activate the virtual environment.

**Windows:**

```bat
.venv\Scripts\activate
```

**Linux/macOS:**

```bash
source .venv/bin/activate
```

Install the backend:

```bash
pip install -r requirements.txt
```

Create your environment file:

```bash
cp .env.example .env
```

On Windows CMD:

```bat
copy .env.example .env
```

Install and build the frontend:

```bash
cd Data/frontend
npm install
npm run build
cd ../..
```

Start LEVIATHAN:

```bash
python -m uvicorn Data.backend.main:app --host 127.0.0.1 --port 8765
```

Open:

- Application: `http://127.0.0.1:8765/`
- Chat: `http://127.0.0.1:8765/chat`
- Models: `http://127.0.0.1:8765/models`
- Datasets: `http://127.0.0.1:8765/datasets`
- Training: `http://127.0.0.1:8765/training`
- Research: `http://127.0.0.1:8765/research`
- Coding Agent: `http://127.0.0.1:8765/coding`
- API documentation: `http://127.0.0.1:8765/docs`

---

## Model configuration

Default OpenAI-compatible endpoint:

```text
http://127.0.0.1:1234/v1
```

The endpoint and model can be configured through `.env`.

Typical configuration:

```env
LEVIATHAN_LLM_BASE_URL=http://127.0.0.1:1234/v1
LEVIATHAN_LLM_MODEL=
LEVIATHAN_LLM_API_KEY=not-needed
```

If no model is pinned, LEVIATHAN can discover models from the configured provider.

The Models control plane also supports provider records and adapters for local/OpenAI-compatible runtimes. Provider capabilities determine which lifecycle operations are actually offered.

---

## Datasets, training and research

### Datasets

Supported core local formats currently include:

```text
.jsonl  .ndjson  .json  .csv  .tsv  .txt  .md
```

Datasets can be imported from local files/paths and supported Hugging Face sources. Raw imports are treated as immutable; transforms create derived versions with lineage.

### Training

The training flow is designed around:

```text
hardware inspection
    → preflight
    → planning
    → durable job
    → worker process
    → metrics/checkpoints
    → evaluation
    → trained artifact registration
```

LoRA and QLoRA paths exist, but actual GPU training remains dependent on the local CUDA/ML environment. LEVIATHAN does not treat an unavailable CUDA runtime as successful training.

### Research

Research can run against local Knowledge and dataset indexes without internet access.

Optional web research requires an explicitly configured outbound network policy and search provider. Sources are stored with provenance and feed an evidence ledger; contradictions are preserved instead of silently discarded.

Reports can be exported as Markdown, HTML and JSON evidence bundles.

---

## Coding Agent

The Coding Agent is a persistent operator-controlled coding loop rather than a separate unrestricted shell.

Current design includes:

- dedicated workspace confinement
- persistent coding sessions and turns
- background execution
- file listing/search/read/write/patch/delete capabilities
- Git status/diff support
- test execution
- patch records
- approval-gated writes and execution
- verification integration
- low-temperature coding model profile

Coding capabilities use the same central execution and approval infrastructure as the rest of LEVIATHAN.

---

## Safety and trust boundaries

LEVIATHAN is currently a **local operator application**, not a hardened public multi-user service.

Important properties:

- default server bind is loopback
- side effects can be policy/approval gated
- Knowledge is treated as context data, not system authority
- model output is not automatically evidence
- secrets should stay in `.env` / server-side configuration
- research web fetching includes SSRF-oriented restrictions
- training workers use explicit subprocess arguments rather than shell command concatenation
- destructive or privileged operations are intended to flow through shared control-plane boundaries

### Important deployment warning

**Do not expose the current development server directly to an untrusted network or the public internet.** The project is local-first and does not currently claim a production-grade authentication/perimeter layer.

---

## Development

### Backend tests

```bash
python -m pytest Data/backend/tests
```

The repository contains regression tests across configuration, persistence, models, datasets, training, research, coding, capabilities, approvals, jobs, evidence, memory, agents, workflows, isolation and other core infrastructure.

### Frontend checks

```bash
cd Data/frontend
npm run typecheck
npm run lint
npm run test
npm run build
```

### Frontend development server

Run the backend:

```bash
python -m uvicorn Data.backend.main:app --host 127.0.0.1 --port 8765
```

Then in another terminal:

```bash
cd Data/frontend
npm run dev
```

Vite proxies `/api` to the backend.

---

## Development status and roadmap

LEVIATHAN is being built incrementally. The current focus is not to make every menu item appear complete, but to turn each domain into a real subsystem with durable state, explicit contracts, tests and truthful failure semantics.

Near- and medium-term directions include:

- supervised **external-first workers** for heavy/specialized execution
- deeper multi-agent orchestration
- richer Coding Agent execution/review flows
- browser automation as an isolated runtime
- real MCP client/server integration
- production media automation
- market simulation and trading infrastructure
- stronger vector/embedding backends
- managed native/model runtimes
- richer evaluation and observability
- streaming model transports
- stronger release/security hardening

For the most accurate technical progress log, see [`Data/docs/buildplan.md`](Data/docs/buildplan.md).

---

## Philosophy

LEVIATHAN is built around a few invariants:

> **Capability is not authority.**
>
> **Model output is not evidence.**
>
> **Dispatch is not completion.**
>
> **Unmeasured is not passed.**
>
> **The control plane should remain the source of truth.**

The objective is not merely to build another chat UI. The long-term goal is a coherent local AI operating environment in which models, agents, tools, knowledge, datasets, training, research and specialized workers can cooperate without giving up observability, ownership or control.

---

## Contributing

The repository is public and under active development. If you are exploring or contributing, start with:

1. `Data/docs/leviathan_system.md`
2. `Data/docs/buildplan.md`
3. `Data/docs/cursor.md`
4. the owning module under `Data/modules/`
5. the related tests under `Data/backend/tests/`

Please keep changes scoped, preserve existing contracts where possible, add tests for meaningful behavior, and avoid reporting unverified functionality as complete.

---

## License

No project license is currently declared in the repository. Public source visibility alone does not grant reuse, modification or redistribution rights. Add a license before treating the project as open-source software in the legal sense.
