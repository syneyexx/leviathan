# HADES Gen2 — Architecture Gap Analysis

> **HISTORICAL / SUPERSEDED SNAPSHOT (2026-09-08).**  
> This document describes Gen2 status as of 2026-09-08. Later scoped deepening landed on `main`
> (see `docs/HADES_GEN2_ROADMAP.md` and `docs/CURRENT_STATUS.md`). Do **not** treat the
> “nine partial / Distributed missing / Flight Recorder in-memory-only” summary below as the
> current product truth. Keep this file as a dated gap baseline only.

**Date:** 2026-09-08  
**Scope:** `main` vs the 10 Gen2 strategic systems  
**Intent:** Analysis only — no Gen2 rewrite in this document’s companion PR beyond docs/archive.  
**Companion roadmap:** `docs/HADES_GEN2_ROADMAP.md`

Status legend used below:

| Status | Meaning |
|---|---|
| `full` | Meets the Gen2 target for that system |
| `partial` | Reusable spine exists; material Gen2 gaps remain |
| `missing` | No meaningful product/runtime foundation yet |

**Honest summary:** none of the ten systems is `full`. Nine are `partial`. Distributed Sovereign Compute is `missing`.

---

## 1. What already fully exists (Gen1 baseline, not Gen2)

The Gen1 “50 world-class capabilities” wave is **shipped and baseline**. Treat these as product floor, not backlog:

- Offline-first shell, Chat/Tasks/Agents/Research/Trading/Plugins/Brain/Memory/Files/Models/Settings
- Reasoning kernel (`backend/reasoning/`): profiles, understanding, context, retrieval, specialists, verification, budgets, plan scheduler, model router, events, run control
- Work Runtime: durable steps/checkpoints, waves, approvals/inbox, schedules, cancel/pause/resume/redirect
- Plugin Manager + MCP catalog + marketplace + application-level permissions
- Memory / Knowledge / Evidence separation with provenance-aware RAG (non-dumping)
- Live Brain graph UI + API overlays
- Coding Agent (plan → approve → apply/restore, repair waves, LSP-light, debug agent)
- PAPER trading + offline bot (seed/CSV, discovery, backtest, paper_bot, Knowledge learnings)
- Financial News Intelligence plugin (480-source collector → Knowledge ingest)
- Practice scenarios A–E and deterministic reasoning eval suite

Archive: `docs/archive/HADES_WORLD_CLASS_VISION.md`.

---

## 2. What partially exists (mapped to the 10 systems)

| # | System | Status | Strongest existing spine |
|---|---|---|---|
| 1 | Mission Control / Mission Compiler | `partial` | `TaskRunner`, `plan_scheduler.ValidatedPlan`, checkpoints, approvals, waves |
| 2 | Intelligence Evaluation Lab | `partial` | `backend/evals/`, practice API, ModelRouter caps metadata, capability tests |
| 3 | Temporal Intelligence Graph | `partial` | Brain nodes/links + Memory supersession + Knowledge provenance overlays |
| 4 | Self-Evolving Agent Factory | `partial` | Specialist contracts, agent_ops, skill plugins, practice harness |
| 5 | Zero-Trust Plugin Sandbox | `partial` | App-level permissions, terminal jail, approvals; **not** OS isolation |
| 6 | Context Compiler 2.0 | `partial` | `retrieval.py` + `context.py` + mentions + evidence coverage |
| 7 | Financial Intelligence Fusion | `partial` | News plugin + paper ledger + strategy bot — **not fused** |
| 8 | Flight Recorder + Deterministic Replay | `partial` | In-memory `RunEventBus` + SSE + tool_calls + artifacts |
| 9 | Multi-Agent Intelligence Committee | `partial` | Specialists + critic + parallel waves — **no debate/vote protocol** |
| 10 | Distributed Sovereign Compute | `missing` | Single-process FastAPI + local SQLite + local LM Studio only |

---

## 3. What is missing (Gen2 deltas)

### 1 — Mission Control / Mission Compiler
- No first-class **Mission** entity or Mission Compiler IR/DAG (objectives, I/O contracts, budgets, permissions, gates, verification requirements, artifacts, waves as one typed object)
- Tasks are the orchestration unit; no portfolio / cross-mission control plane above Tasks
- Plan JSON from the model ≠ compiled typed mission with resource-aware scheduling

### 2 — Intelligence Evaluation Lab
- No productized local benchmark lab / capability matrix UI
- No empirical model×task scoring store driving ModelRouter
- Deterministic eval exists; live-model + historical-run evaluation does not
- No hallucination / citation / coding / research / planning metric suite as durable product data

### 3 — Temporal Intelligence Graph
- `brain_links` lack `valid_from` / `valid_until` / `observed_at` / confidence / provenance / supersedes / contradicts / caused_by
- Overlays are recomputed views, not a persisted temporal intelligence plane
- No as-of queries (“what did we believe 3 months ago?”)

### 4 — Self-Evolving Agent Factory
- No Do→Observe→Evaluate→Extract→Candidate→Benchmark→Promote→Reuse loop
- Specialists are static Python contracts; planned agents are stubs
- No candidate sandbox + mandatory human promotion gate for generated skills/agents

### 5 — Zero-Trust Plugin Sandbox
- Explicitly documented: application-level only (`PLUGIN_RUNTIME_CONTRACT.md`)
- No capability envelope with FS/network/CPU/RAM/job-object/AppContainer/Docker tiers
- Third-party plugins can still run as the HADES user when permitted

### 6 — Context Compiler 2.0
- Char budgets, not real tokenizer budgeting against model context limits
- No contradiction grouping, source diversification pass, hierarchical recursive summarization product, or context-utility-per-token optimizer
- No durable compiled context pack artifacts

### 7 — Financial Intelligence Fusion Engine
- News events, paper book, Fincept, and strategy bot remain separate paths
- No structural market-event objects with cross-source verification, analogues, event studies wired into Knowledge/Graph learning as one pipeline
- PAPER-only remains correct policy (D011)

### 8 — Flight Recorder + Deterministic Replay
- Events are **in-memory** (ring buffer); not durable across restart
- No full event vocabulary (MODEL_REQUEST/RESPONSE, CONTEXT_SELECTED, …) persisted with hashes/fingerprints
- No replay-from-event, compare-two-runs, or side-effect-safe deterministic replay

### 9 — Multi-Agent Intelligence Committee
- No isolated multi-perspective deliberation with divergent retrieval/models
- No consensus object (agreements / disagreements / minority / unsupported / missing evidence)
- Critic ≠ committee

### 10 — Distributed Sovereign Compute
- No node identity, capability advertisement, mutual auth, encrypted transport, durable remote queues, or Mission Control dispatch across machines

---

## 4. Reusable modules (do not rebuild)

| Area | Reuse |
|---|---|
| Mission Control | `TaskRunner`, `plan_scheduler`, `work_steps`/`work_checkpoints`, `approvals`, `inbox`, `schedules`, `SharedBudgetPool` patterns |
| Eval Lab | `backend/evals/reasoning_eval.py`, `practice_api.py`, ModelRouter capability fields, release_confidence |
| Temporal Graph | Brain CRUD API, Memory supersession fields, Knowledge sources/chunks, research coverage |
| Agent Factory | `specialists.py` contracts, `agent_ops`, plugin skill packages, practice A–E |
| Sandbox | `PluginManager`, `enforce_plugin_permissions`, terminal allowlist/cwd jail, approval fingerprints |
| Context Compiler | `retrieval.py`, `context.py`, `conversation_state.py`, `mentions.py`, `evidence_coverage.py` |
| Finance Fusion | `trading_service.py` (Paper + Bot), `financial-news-intelligence`, Fincept plugin, trading Knowledge ingest |
| Flight Recorder | `reasoning/events.py` schema/SSE, `tool_calls`, `artifacts.py`, task_events, run inspection |
| Committee | specialists, verification critic, wave parallelism, ResearchRunner iteration |
| Distributed (later) | task queue abstraction, plugin process boundary, artifact checksums, schedule claim pattern |

Hotspots to **extract from**, not enlarge blindly: `backend/main.py`, `platform_services_core.py`, `platform_db.py`, `database.py`, `lib/hades-api.ts`.

---

## 5. Likely database changes

Prefer additive SQLite migrations (forward-compatible). Probable new/extended tables:

| System | Likely schema |
|---|---|
| Mission Control | `missions`, `mission_revisions`, `mission_gates`, bind to `tasks` / plan version |
| Eval Lab | `eval_suites`, `eval_cases`, `eval_runs`, `eval_scores`, `model_capability_matrix` |
| Temporal Graph | extend `brain_links` / new `graph_edges` with temporal+provenance columns; optional `graph_events` append-only |
| Agent Factory | `agent_definitions`, `agent_versions`, `skill_candidates`, promotion audit |
| Sandbox | `policy_profiles`, `capability_envelopes`, sandbox run manifests/audit |
| Context Compiler | optional `context_packs` (hash, kept/dropped, tokenizer stats) |
| Finance Fusion | `market_events`, `event_entities`, `theses`, links news→event→signal→paper_order |
| Flight Recorder | durable `run_events`, `model_io_records`, `replay_manifests` |
| Committee | `committee_sessions`, `committee_ballots`, `dissent_records` |
| Distributed | `compute_nodes`, `node_capabilities`, `remote_jobs`, `leases` |

No destructive resets. Existing Memory/Knowledge/Evidence roles stay distinct (D004).

---

## 6. Likely API contracts

Typed FastAPI + mirrored `lib/hades-api.ts` types. Suggested surfaces (incremental):

| System | API sketch |
|---|---|
| Mission Control | `POST/GET /api/missions`, `…/compile`, `…/start`, `…/gates/{id}/decide`, portfolio list |
| Eval Lab | `POST /api/evals/run`, `GET /api/evals/reports`, `GET /api/evals/matrix` |
| Temporal Graph | `GET /api/graph/as-of`, path/contradiction queries; edge CRUD with temporal fields |
| Agent Factory | `POST /api/skills/candidates`, `…/benchmark`, `…/promote`, `…/rollback` |
| Sandbox | policy profile CRUD; `GET /api/plugins/{id}/envelope`; sandbox status |
| Context Compiler | `POST /api/context/compile` (preview), attach pack id on run inspection |
| Finance Fusion | fused feed, `market_events`, signal→paper proposal + approval |
| Flight Recorder | durable events GET; `POST /api/runs/{id}/replay`; `GET /api/runs/compare` |
| Committee | `POST /api/committees`, stream rounds, consensus object |
| Distributed | node register/heartbeat, capability discover, job dispatch/cancel |

Keep deterministic security off the LLM path (D009).

---

## 7. Recommended new backend modules

Prefer new packages over growing `main.py`:

```text
backend/mission/          # Mission IR, compiler, control plane (calls TaskRunner)
backend/evals/            # expand: suites, live runners, matrix, historical ingest
backend/graph/            # temporal intelligence data plane (Brain evolves into this)
backend/agent_factory/    # candidate skills, promote/rollback
backend/sandbox/          # capability envelopes + tiered executors
backend/context_compiler/ # compiler 2.0 (wraps reasoning/retrieval+context)
backend/finance_fusion/   # event pipeline above trading + news plugins
backend/flight_recorder/  # durable events + replay/compare
backend/committee/        # multi-agent deliberation protocol
backend/compute_fabric/   # nodes, auth, queues (Phase 5 only)
```

`main.py` becomes route registration + wiring; services own logic.

---

## 8. Frontend pages / panels impacted

| Page / surface | Gen2 impact |
|---|---|
| Tasks | Mission binding, gates, waves from Mission Control |
| Agents | Committee sessions; Agent Factory candidates/promote |
| Models | Capability matrix; empirical router explanations |
| Chat | Context pack preview; Flight Recorder timeline; committee dissent banners |
| Brain | Temporal as-of, contradictions, causal edges |
| Memory / Research / Files | Graph-linked provenance; fusion evidence |
| Trading | Fused events/theses (still PAPER-only) |
| Plugins / Settings → Beveiliging | Envelopes, tiers, policy profiles |
| New pages (later) | Mission Control, Eval Lab, Flight Recorder, Compute Nodes |
| Ctrl+K / health | Discoverability + honest subsystem health |

Preserve established GUI language unless a page is explicitly requested (D003).

---

## 9. Top technical risks

1. **Hotspot gravity** — continuing to dump Gen2 into `main.py` / `platform_services_core.py` without interfaces
2. **Fake autonomy** — Mission Control/Factory/Committee without Eval Lab + Flight Recorder → unverifiable “improvements”
3. **Security theatre** — labeling app-level permissions as zero-trust
4. **Schema breakage** — non-migrated Brain/Memory changes wiping local user graphs
5. **Non-durable “replay”** — claiming determinism from in-memory SSE events
6. **Model hardcoding** — empirical router regressing to name heuristics (violates D002)
7. **Finance scope creep** — real-money trading before explicit separate architecture (D011)
8. **Distributed too early** — multi-node before single-node recorder/mission/eval are solid
9. **Uncontrolled self-modification** — Agent Factory promoting without sandbox + human gate
10. **Context regressions** — compiler 2.0 silently dropping mandatory evidence

---

## 10. Concrete implementation order

Aligns with the user-recommended phases (measure → autonomy → security → data plane → scale):

### Phase 1 — Meetbaarheid en intelligencekwaliteit
1. **Intelligence Evaluation Lab** (productize evals + matrix; wire scores into ModelRouter later)
2. **Context Compiler 2.0** (tokenizer-aware packing on top of current retrieval)
3. **Flight Recorder + Deterministic Replay** (durable events first; replay/compare next)

### Phase 2 — Autonomie en orchestration
4. **Mission Control / Mission Compiler** (Mission IR above TaskRunner)
5. **Multi-Agent Intelligence Committee**
6. **Self-Evolving Agent Factory** (requires eval + recorder + human promote)

### Phase 3 — Security
7. **Zero-Trust Plugin Sandbox** (tiered isolation; Windows first-class)

### Phase 4 — Intelligence Data Plane
8. **Temporal Intelligence Graph**
9. **Financial Intelligence Fusion Engine**

### Phase 5 — Schaal
10. **Distributed Sovereign Compute**

Within each system: characterization tests → additive schema → module extract → API → UI → focused verification. Never mark `done` without evidence.

---

## 11. Dependencies between the ten systems

```text
Flight Recorder ──────► Eval Lab (historical runs as eval data)
         │                      │
         ▼                      ▼
Context Compiler 2.0 ◄── matrix scores ──► ModelRouter (empirical)
         │
         ▼
Mission Control ──► Committee ──► Agent Factory
         │                │              │
         │                └──────────────┤
         ▼                               ▼
   TaskRunner / Agents            promote only after eval+sandbox+human

Zero-Trust Sandbox ── required before broad autonomous Factory/Mission tool use

Temporal Graph ◄── Flight Recorder events + Memory/Knowledge/Evidence writes
       ▲
Finance Fusion ── writes structural events into Graph/Knowledge (PAPER strategies reuse TradingBot)

Distributed Compute ── requires Mission Control dispatch + Sandbox envelopes + Recorder audit
```

Critical path: **Recorder + Eval + Context** before deep autonomy; **Sandbox** before wide autonomous promotion; **Graph** before serious fusion claims; **Distributed** last.

---

## 12. Old roadmap / documentation disposition

| Document | Action |
|---|---|
| `docs/HADES_WORLD_CLASS_VISION.md` | **Archived** → `docs/archive/HADES_WORLD_CLASS_VISION.md` (Gen1 baseline) |
| `docs/RELIABLE_ORCHESTRATION_PLAN.md` | **Archived** (stale inventory) |
| `docs/REASONING_ORCHESTRATION_PLAN.md` | **Archived** (completed A–G plan) |
| `docs/REASONING_AUDIT.md` | **Keep** (historical baseline audit) |
| `docs/REASONING_CHANGELOG.md` | **Keep** |
| `docs/REASONING_ARCHITECTURE.md` | **Keep** (live kernel contract; extend when Gen2 extracts modules) |
| `docs/ARCHITECTURE.md` | **Keep** — updated for Gen2 layer diagram |
| `docs/PLUGIN_RUNTIME_CONTRACT.md` | **Keep** (still accurate; sandbox is future tier) |
| `docs/DECISIONS.md` | **Keep** — add Gen2 decision |
| `docs/REASONING_EVAL_REPORT.json` | **Keep** as sample artifact until Eval Lab owns reports |
| `docs/CURRENT_STATUS.md` / `HADES_CODEBASE_MAP.md` | **Update** to point at Gen2 docs |

Do **not** delete tests, capability suites, or architecture contracts that encode Gen1 behavior.

---

## Target layering (Gen2 direction)

```text
HADES OS (UI shell)
  → Mission Control
  → Reasoning Kernel / Agents / Scheduler
  → Capability Fabric
  → Plugins / MCP / Native Tools
  → Secure Execution Fabric
  → Local / Container / Remote Nodes
  → Intelligence Data Plane
  → Memory / Knowledge / Evidence / Temporal Graph
  → Evaluation / Replay
```

Extract via stable interfaces (D012). No giant rewrite of `main.py` in one generation.
