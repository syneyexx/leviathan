# HADES Gen2 Roadmap — Sovereign Intelligence OS

**Status:** Implementation complete for scoped Gen2 deliverables (2026-09-09) — residual host-only verification remains honest, not faked  
**Baseline:** Gen1 “50 world-class capabilities” are **complete** and archived in `docs/archive/HADES_WORLD_CLASS_VISION.md`  
**Gap analysis:** `docs/ARCHITECTURE_GAP_ANALYSIS_GEN2.md`  
**Companion backlog:** `docs/HADES_MONSTER_PROJECT_PLAN.md` (all checklist IDs ticked with evidence / deferred / UNVERIFIED_ON_HOST notes)  
**Product thesis unchanged:** offline-first, Windows-first, dynamic LM Studio models, deterministic safety, no fake success

This generation lifts HADES from a capable local AI workspace to a **sovereign intelligence OS**: goal → compiled mission → measured execution → temporal knowledge → controlled evolution — still without requiring cloud.

---

## Non-negotiables (carry forward)

1. Offline-first core; network is optional enrichment  
2. Dynamic LM Studio model IDs — never hardcode production models  
3. Deterministic security/permissions — never decided inside LLM prompts  
4. No fake success; verification and honest incomplete states  
5. Windows 10/11 first-class  
6. PAPER trading only until an explicit real-money project exists  
7. Incremental extract-over-rewrite (`docs/DECISIONS.md` D012)  
8. Characterization tests before large refactors of hotspots  

---

## Target architecture layers

```text
HADES OS
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

`backend/main.py` and large service modules are **hotspots to decouple** via stable interfaces — not one-shot rewrite targets.

---

## The 10 strategic systems

### 1. Mission Control / Mission Compiler
Compile a high-level end goal into a typed executable mission DAG (objectives, subtasks, dependencies, agents, models, tools, I/O contracts, budgets, permissions, retries, checkpoints, approval gates, acceptance criteria, verification, artifacts, waves).  
**Sits above** Tasks, Agents, reasoning, tools, verification.  
**Builds on:** Work Runtime, `plan_scheduler`, approvals, budgets.

### 2. Intelligence Evaluation Lab
Local benchmark lab for models, agents, prompts, retrieval strategies, and tools. Metrics include success, acceptance, hallucination, citation correctness, structured output, tool accuracy/efficiency, replanning, latency, tokens, RAM/VRAM, retries, verification failures, context sensitivity, coding/research/planning quality.  
Produces a **capability matrix**; ModelRouter eventually chooses empirically.  
**Builds on:** `backend/evals/`, practice scenarios, ModelRouter metadata.

### 3. Temporal Intelligence Graph
Evolve Brain into a time-aware intelligence graph (`valid_from`/`valid_until`/`observed_at`, provenance, confidence, supersedes/contradicts/caused_by/…). Integrate Memory, Knowledge, Evidence, Research, News, Trading, Agents, Tasks, tools, documents, code intelligence.  
Answer as-of, contradiction, and analogue questions as a **data plane**, not only a visualization.  
**Builds on:** Brain API, Memory supersession, Knowledge provenance.

### 4. Self-Evolving Agent Factory
Controlled loop: Do → Observe → Evaluate → Extract Pattern → Candidate Skill → Benchmark → Promote → Reuse.  
Candidates require tests, benchmarks, sandboxing, and **human approval** before promotion. No uncontrolled self-rewrite.  
**Builds on:** specialist contracts, agent_ops, skill plugins, Eval Lab, Sandbox.

### 5. Zero-Trust Plugin Sandbox
Capability envelopes (FS read/write, network ranges, subprocess, env/secrets, timeout, CPU/RAM, cwd, execution mode, autonomous vs approval).  
Tiers: 0 core → 1 restricted subprocess → 2 Windows Job Object/AppContainer → 3 Docker/WSL/VM.  
**Builds on:** PluginManager permissions (explicitly app-level today).

### 6. Context Compiler 2.0
Replace simple retrieval packing with an intelligent compiler: relevance, reliability, provenance, freshness, temporal validity, usefulness, uniqueness, contradiction risk, diversity, token cost, **real tokenizer**, model context size.  
**Builds on:** `retrieval.py`, `context.py`, mentions, evidence coverage.

### 7. Financial Intelligence Fusion Engine
Fuse Financial News Intelligence + PAPER trading/bot into an event pipeline: normalize → dedupe → entity resolve → extract → cross-verify → classify → map assets → analogues → reaction analysis → hypothesis → backtest/event study → paper strategy → Graph/Knowledge learning.  
Structural events, not “just articles”. PAPER-only.  
**Builds on:** news plugin, `TradingBotService`, paper ledger, Knowledge ingest.

### 8. Flight Recorder + Deterministic Replay
Durable, sequenced run events (create, context, model I/O, plan, tools, approvals, replan, checkpoint, verification, artifacts, terminal states) with hashes, fingerprints, versions, config snapshots.  
Replay/compare/diff for debug, benchmark, regression, audit.  
**Builds on:** `RunEventBus`/SSE (make durable), tool_calls, artifacts.

### 9. Multi-Agent Intelligence Committee
Independent deliberation with divergent context/prompts/models where useful; synthesis of agreements, disagreements, minority positions, unsupported claims, confidence, missing evidence.  
Avoid “five agents say the same thing.”  
**Builds on:** specialists, critic, waves.

### 10. Distributed Sovereign Compute
Personal local/distributed cluster: capability nodes (GPU desktop, NAS, laptop, mini-PC), discovery, auth, encrypted transport, durable queues, offline/reconnect, artifact distribution, Mission Control dispatch. No cloud required.  
**Builds on:** nothing distributed yet — greenfield after single-node maturity.

---

## Implementation phases

### Phase 1 — Meetbaarheid en intelligencekwaliteit
| Order | System | Why first | Status (2026-09-09) |
|---|---|---|---|
| 1 | Intelligence Evaluation Lab | Know whether changes help | **partial→verified** (metrics catalog v2, domain_quality suites, holdout seeds, empirical ModelRouter lookup; live quality still host-dependent) |
| 2 | Context Compiler 2.0 | Raise answer quality under hard context limits | **partial→verified** (tokenizer honesty + contradiction clusters + hierarchical stub provenance); chat-path **opt-in only** |
| 3 | Flight Recorder + Replay | Auditability + eval data + safe debugging | **partial→verified** (payload hashes/config fingerprints/model snapshots + audit); inspect≠live replay honesty preserved |

### Phase 2 — Autonomie en orchestration
| Order | System | Status (2026-09-09) |
|---|---|---|
| 4 | Mission Control / Mission Compiler | **partial→verified** — typed IR + portfolio/revisions/links/acceptance/replan + layered DAG preview; resource_plan stub `host_measured=false` (not full/shipped) |
| 5 | Multi-Agent Intelligence Committee | **partial→deepened** — divergent slices/prompts/`model_slots`; claim_marks persisted; clone_risk divergence metrics |
| 6 | Self-Evolving Agent Factory | **partial→verified** — mandatory_tests + versioning/compat + catalog hygiene; human promote+hash; extract-from-run never auto-promotes |

### Phase 3 — Security
| Order | System | Status (2026-09-09) |
|---|---|---|
| 7 | Zero-Trust Plugin Sandbox | **partial→verified** — envelopes + JIT UX + plugin checklist/hash + MCP harden + terminal jail + tool-boundary defenses; Job Object **implemented + selftest**, **UNVERIFIED_ON_HOST** on Linux CI |

Security must grow before very broad autonomous tool execution / promoted agents.

### Phase 4 — Intelligence Data Plane
| Order | System | Status (2026-09-09) |
|---|---|---|
| 8 | Temporal Intelligence Graph | **partial→deepened** — as-of + `known_as_of`; require_provenance; contradictions/analogues product tests |
| 9 | Financial Intelligence Fusion Engine | **partial→deepened** — fuse + cross-verify + thesis persist; event study refuses without PAPER bars |

### Phase 5 — Schaal
| Order | System | Status (2026-09-09) |
|---|---|---|
| 10 | Distributed Sovereign Compute | **MVP local/LAN** — L6 local gate verified; A11/L2–L5 multi-host **deferred / UNVERIFIED_ON_HOST** (not full/shipped) |

**Completion discipline:** all ten systems have implemented spines with tests + UI/API surfaces. None are marked `full` / `shipped` where host isolation, live LM quality, or multi-machine compute remain **UNVERIFIED_ON_HOST** or deferred-by-design. Evidence lives in `docs/CURRENT_STATUS.md`.

### Residual host / scope gates (not open backlog)

| Gate | Status |
|---|---|
| Windows Job Object / AppContainer operational PASS | **UNVERIFIED_ON_HOST** on Linux CI (module + selftest present) |
| Live LM Studio model-quality evals | Host-dependent; software/offline suites verified |
| Multi-host distributed compute (A11 beyond L6) | Deferred-by-design until single-node solidity stays green |
| Context Compiler as default chat path | Opt-in only (`HADES_CONTEXT_COMPILER_CHAT`) — intentional |

---

## Definition of done (per system)

A Gen2 system may be called **done** only when:

1. Typed contracts exist between subsystems  
2. Additive DB migrations preserve local data  
3. Focused characterization + feature tests pass  
4. Relevant UI surfaces show honest status (including failures)  
5. Offline/local-first behavior is verified or explicitly scoped  
6. No security decision is delegated to the model  
7. Long runs are bounded, observable, cancellable, and resumable where applicable  
8. `docs/CURRENT_STATUS.md` records verification evidence  

**Scoped completion (this roadmap):** Phases 1–5 deliverables above are implemented and test-backed (`test_gen2*.py` **247 PASS** on 2026-09-09). Host-gated DoD items stay labeled — never fake `shipped`.

---

## Near-term engineering rules for Gen2 work

- Analyze existing implementation before building parallel systems  
- Reuse Gen1 spines listed in the gap analysis  
- Prefer new modules under `backend/<system>/` over megfile growth  
- Small, logically separated commits  
- Update this roadmap’s phase checkboxes only after verified merges  
- Keep Gen1 archive docs historical; do not reopen the 50-capability backlog  

---

## Document map

| Doc | Role |
|---|---|
| `docs/HADES_GEN2_ROADMAP.md` | **This file** — Gen2 roadmap (scoped implementation complete; residual host gates explicit) |
| `docs/HADES_MONSTER_PROJECT_PLAN.md` | Master monster backlog — **161/161 IDs ticked** with verified / partial / deferred / UNVERIFIED_ON_HOST (not operational 100%) |
| `docs/ARCHITECTURE_GAP_ANALYSIS_GEN2.md` | Current vs Gen2 gap analysis (12-point deliverable) |
| `docs/ARCHITECTURE.md` | Live architecture overview |
| `docs/REASONING_ARCHITECTURE.md` | Reasoning kernel contract |
| `docs/PLUGIN_RUNTIME_CONTRACT.md` | Plugin behavioral contract |
| `docs/DECISIONS.md` | Durable decisions |
| `docs/archive/` | Completed Gen1 / superseded plans |
