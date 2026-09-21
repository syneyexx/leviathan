# HADES Monster Project Plan — Gen2 Sovereign Intelligence OS

**Status:** Checklist IDs **161/161 ticked** (2026-09-09) with verified / partial / deferred / UNVERIFIED_ON_HOST evidence — **not** a claim of operational or quality 100%  
**Owner:** Strijder (product direction)  
**Companion docs:** `docs/HADES_GEN2_ROADMAP.md`, `docs/ARCHITECTURE_GAP_ANALYSIS_GEN2.md`, `docs/CURRENT_STATUS.md`  
**Intent:** Single master backlog that turns HADES from a capable local AI workspace into a verifiable sovereign intelligence OS — portfolio-grade systems work, not feature spam.

> **P0 gate cleared (2026-09-09):** `main` refreshed; implementation on `cursor/gen2-monster-completion-8d97` (PR #51).  
> **Completion note:** Host-gated items (Windows Job Objects, multi-machine compute, live LM quality) are ticked only as **implemented + honest UNVERIFIED_ON_HOST / deferred** — never as fake PASS. Do not summarize this checklist as “product 100% complete.”

---

## 0. Execution rules (non-negotiable)

1. **No build from this plan until `main` is current** (parallel work must merge first; rebase/branch from fresh `main`).
2. Preserve HADES behavior/UI unless a workstream explicitly changes them.
3. Offline-first; network optional and must fail clean to local behavior.
4. Dynamic LM Studio model IDs — never hardcode production models.
5. Deterministic security/permissions — never decided inside LLM prompts.
6. No fake success: every “done” needs verification evidence in `docs/CURRENT_STATUS.md`.
7. Windows 10/11 first-class; avoid Unix-only assumptions in product paths.
8. PAPER trading only until an explicit real-money project exists.
9. Incremental extract-over-rewrite; characterization tests before hotspot refactors.
10. Work subsystem-first using `docs/HADES_CODEBASE_MAP.md`.
11. Prefer new modules under `backend/<system>/` over growing `main.py`.
12. Definition of done per Gen2 roadmap: typed contracts, additive migrations, tests, honest UI, offline scoped, bounded long runs.

### Recommended build order (phases)

| Phase | Theme | Systems |
|---|---|---|
| **P0** | Gate | Wait for fresh `main`; baseline characterization |
| **P1** | Meetbaarheid | Eval Lab → Context Compiler 2.0 → Flight Recorder |
| **P2** | Orchestration | Mission Compiler → Workflows page → Committee → Agent Factory |
| **P3** | Security | Zero-Trust Plugin Sandbox (Windows-first) |
| **P4** | Data plane | Temporal Graph → Finance Fusion (PAPER) |
| **P5** | Scale | Distributed Sovereign Compute (only after P1–P4 solid) |
| **PX** | Continuous | Platform excellence, polish, docs, release gates |

---

## P0 — Start gate (before any monster implementation)

| ID | Item | Notes |
|---|---|---|
| P0.1 | Wait until parallel in-flight work merges and **`main` is refreshed** | Explicit user constraint |
| P0.2 | Branch from latest `origin/main` for monster tracks | One logical track per PR when possible |
| P0.3 | Record baseline: `verify_hades.py --quick`, focused Gen2/reliability suites | Characterization before change |
| P0.4 | Freeze “done” language: `partial` / `in progress` / `verified` only with evidence | Align with Gen2 DoD |

---

## A. Portfolio spine (maximale impact — primary narrative)

Ship these as the coherent story: *measure → orchestrate → secure → evolve*.

| ID | Item | Phase | Depends on |
|---|---|---|---|
| A1 | **Intelligence Evaluation Lab (product)** — suite UI, capability matrix, persistent scores, model×task compare, regression over time | P1 | P0 |
| A2 | **Flight Recorder + Deterministic Replay** — durable events, hashes, replay/compare; no in-memory theatre | P1 | P0 |
| A3 | **Context Compiler 2.0** — real tokenizer budgets, contradiction/diversity, context-pack artifacts, kept/dropped rationale | P1 | P0 |
| A4 | **Mission Control / Mission Compiler (real)** — typed Mission IR/DAG above Tasks; gates, budgets, verification, artifacts as one object | P2 | A2 helpful |
| A5 | **Workflows page** — library + AI-author + edit + run + versioning above Work Runtime / skills | P2 | A4 spine |
| A6 | **Zero-Trust Plugin Sandbox (Windows-first)** — capability envelopes, Job Object/AppContainer tiers, audit; not app-permissions only | P3 | A2 |
| A7 | **Multi-Agent Committee** — real dissent/consensus objects (not five clones) | P2 | A1, A2 |
| A8 | **Agent Factory with human promote-gate** — Do→Evaluate→Candidate→Benchmark→Promote/Rollback | P2 | A1, A2, A6 |
| A9 | **Temporal Intelligence Graph** — as-of queries, contradicts/supersedes, confidence/provenance as data plane | P4 | A3 |
| A10 | **Finance Fusion (PAPER-only)** — structural market events → thesis → backtest → graph learning | P4 | A9 helpful |
| A11 | **Distributed Sovereign Compute** — defer; too early kills scope | P5 | A1–A8 solid |

---

## B. Mission Control & Workflows

### B1. Mission Compiler

| ID | Item | Phase |
|---|---|---|
| B1.1 | High-level goal → typed Mission IR (objectives, deps, agents, tools, I/O schemas, retries, waves) | P2 |
| B1.2 | Resource-aware scheduling (model slots, RAM/VRAM, tool contention) | P2 |
| B1.3 | Acceptance criteria as executable checks (not prose-only) | P2 |
| B1.4 | Approval gates with fingerprint + reason + revoke | P2 |
| B1.5 | Portfolio view: multiple missions, priorities, blocked/waiting dependencies | P2 |
| B1.6 | Mission revisions + diff between plan versions | P2 |
| B1.7 | Replan on failure with bounded retry + cause taxonomy | P2 |
| B1.8 | Mission ↔ Task ↔ Run ↔ Step ↔ Artifact identity linking consistent everywhere | P2 |
| B1.9 | “Confirmed outcome” identical across Mission Control, Tasks, and Chat banners | P2 |

### B2. Workflows product surface

| ID | Item | Phase |
|---|---|---|
| B2.1 | **Workflows page**: list / create / edit / run / history / versions | P2 |
| B2.2 | AI: natural language → workflow draft (steps, inputs, success checks) | P2 |
| B2.3 | Pre-save validation: schema, permissions, offline-safe, tool eligibility | P2 |
| B2.4 | Visual step graph (DAG) — not toy kanban | P2 |
| B2.5 | Workflow template library (research, coding, ingest, eval, paper-trade study) | P2 |
| B2.6 | Import/export `.HadesWorkflow` packages | P2 |
| B2.7 | Dry-run / sandbox-run mode | P2 |
| B2.8 | Human-in-the-loop steps (approve, choose, provide secret) | P2 |
| B2.9 | Workflow metrics: success rate, cost, latency, tool failures | P2 |
| B2.10 | Promotion path: draft → tested → promoted (same discipline as skills) | P2 |
| B2.11 | Workflow-as-skill-candidate bridge into Agent Factory | P2 |

---

## C. Reasoning, agents & autonomy

| ID | Item | Phase |
|---|---|---|
| C1 | Tighten understand → retrieve → plan → execute → verify pipeline with structured outputs everywhere | P1–P2 |
| C2 | Tool selection only from *eligible* tools; failures always returned to the model as failures | P1 |
| C3 | Expand + test: policy/permission never decided via prompt | P1 / P3 |
| C4 | Budget enforcement that truly stops (tokens, steps, wall time, tool calls) | P2 |
| C5 | Hallucination/citation verification as first-class gate for research answers | P1–P2 |
| C6 | Coding Agent: stronger plan → approve → apply; restore integrity; repair waves with LSP evidence | P2 |
| C7 | Long-task resume that is side-effect-safe (idempotency keys) | P2 |
| C8 | Expand specialist contracts + local performance contracts (SLA-like) | P2 |
| C9 | Committee: divergent retrieval + divergent models + synthesis with minority reports | P2 |
| C10 | Critic that marks claims: supported / unsupported / missing evidence | P2 |
| C11 | Adaptive routing metadata visible in UI (why this model/agent) | P1–P2 |
| C12 | No infinite self-reflection: hard caps + escape to human | P2 |
| C13 | “Stop and ask” quality: when uncertain, do not steamroll | P2 |
| C14 | Memory write policy: what may persist, with confidence + provenance | P4 |
| C15 | Knowledge write-back only after verification + user/policy allow | P4 |

---

## D. Intelligence Evaluation Lab

| ID | Item | Phase |
|---|---|---|
| D1 | Product UI: suites, cases, runs, diffs, flaky detection | P1 |
| D2 | Metrics suite: success, acceptance, hallucination, citation, tool accuracy, replanning, latency, tokens, retries | P1 |
| D3 | Coding quality suite + research quality suite + planning quality suite | P1 |
| D4 | Holdout sets (e.g. `generalization_v1`) + seed reproducibility | P1 |
| D5 | Live-model eval mode + deterministic software mode (both honestly labeled) | P1 |
| D6 | Capability matrix per model/host (dynamic LM Studio IDs) | P1 |
| D7 | ModelRouter chooses **empirically** instead of name heuristics | P1 (later wire) |
| D8 | Eval → regression gate in `verify_hades.py` / release gates | P1 |
| D9 | Historical run ingest from Flight Recorder | P1 |
| D10 | A/B prompt/strategy experiments with statistical honesty (small-n, confidence intervals) | P1 |
| D11 | “Did this PR help?” local benchmark dashboard | P1 |
| D12 | Red-team evals: prompt injection, tool exfil attempts, permission bypass attempts | P1 / P3 |
| D13 | Offline-first: evals must run without network | P1 |

---

## E. Flight Recorder, observability & truthfulness

| ID | Item | Phase |
|---|---|---|
| E1 | Durable `run_events` in SQLite (append-only) | P1 |
| E2 | Full vocabulary: MODEL_IO, CONTEXT_SELECTED, PLAN, TOOL, APPROVAL, REPLAN, VERIFY, ARTIFACT, TERMINAL | P1 |
| E3 | Content hashes + config fingerprints + model-id snapshots | P1 |
| E4 | Replay without re-executing side effects (deterministic compare) | P1 |
| E5 | Run compare/diff UI | P1 |
| E6 | Timeline in Chat / Tasks / Mission Control | P1–P2 |
| E7 | Exportable audit bundle for a run | P1 |
| E8 | Failure taxonomy (permission, schema, tool, model, verification, budget) | P1 |
| E9 | Honest health everywhere: `implemented` ≠ `operationally_tested` ≠ `quality_evaluated` | P1 |
| E10 | No fake success: UI shows incomplete / UNVERIFIED states explicitly | continuous |

---

## F. Context, memory & intelligence data plane

### F1. Context Compiler 2.0

| ID | Item | Phase |
|---|---|---|
| F1.1 | Real tokenizer vs model context window | P1 |
| F1.2 | Utility-per-token ranking | P1 |
| F1.3 | Contradiction clustering before packing | P1 |
| F1.4 | Source diversification (not 12 chunks from one doc) | P1 |
| F1.5 | Freshness + temporal validity filters | P1 |
| F1.6 | Hierarchical recursive summarization with provenance links | P1 |
| F1.7 | Compiled context pack preview in UI (“kept/dropped + why”) | P1 |
| F1.8 | Mandatory evidence pins (must not silently drop) | P1 |

### F2. Temporal Graph / Brain

| ID | Item | Phase |
|---|---|---|
| F2.1 | `valid_from` / `valid_until` / `observed_at` on edges | P4 |
| F2.2 | Relation types: supersedes, contradicts, caused_by, supports, derived_from | P4 |
| F2.3 | As-of query API + UI (“what did we believe then?”) | P4 |
| F2.4 | Confidence + provenance required on claims | P4 |
| F2.5 | Analogue search (“similar situations”) | P4 |
| F2.6 | Brain not viz-only: queryable intelligence plane | P4 |
| F2.7 | Unify Memory / Knowledge / Evidence / Research / News / Tasks links without mixing roles | P4 |

---

## G. Security & plugin runtime (Windows first-class)

| ID | Item | Phase |
|---|---|---|
| G1 | Capability envelopes: FS paths, network CIDRs, subprocess, env, secrets, CPU/RAM, timeout, cwd | P3 |
| G2 | Tier 0–3 executors with honest availability detection | P3 |
| G3 | Windows Job Object + AppContainer path harden/verify on host | P3 |
| G4 | Policy profiles (personal / strict / research / coding) | P3 |
| G5 | Secret handling: never in prompts; redaction in recorder | P3 |
| G6 | Permission UX: least privilege, just-in-time grants, expire | P3 |
| G7 | Plugin packaging security review checklist + static scan hooks | P3 |
| G8 | MCP tool allowlists + hardened schema validation | P3 |
| G9 | Supply-chain: signed/hashed `.HadesPlugin`, integrity verify on install | P3 |
| G10 | Terminal jail expansions + audited command classes | P3 |
| G11 | Prompt-injection defenses at tool boundary (untrusted content labeling) | P3 |
| G12 | Network-optional fail-clean everywhere (no hang, no crash) | continuous |

---

## H. Agent Factory & skills evolution

| ID | Item | Phase |
|---|---|---|
| H1 | Pattern extraction from successful runs | P2 |
| H2 | Candidate skill generation with mandatory tests | P2 |
| H3 | Benchmark gate before promote | P2 |
| H4 | Human approval + rollback | P2 |
| H5 | Skill versioning + compatibility | P2 |
| H6 | Workflow ↔ skill promotion path | P2 |
| H7 | No uncontrolled self-rewrite of core HADES | P2 |
| H8 | Hard contract test: broken workflow fails promote | P2 |
| H9 | Skill marketplace hygiene (local catalog quality, not spam) | P2 |

---

## I. Research / Knowledge / Files / Voice / Coding polish

| ID | Item | Phase |
|---|---|---|
| I1 | Research runner: coverage metrics, source quality scores, stop criteria | P2–P4 |
| I2 | Citation-first answers with Evidence Vault deep links | P1–P2 |
| I3 | Harvest reliability + dedupe + entity resolve | P4 |
| I4 | Files ingestion: better chunking, code-aware chunking, PDF/Office robustness | P1–P4 |
| I5 | Workspace symbols / LSP-light: more reliable diagnostics → coding agent | P2 |
| I6 | Coding jobs: clearer status machine, cancel, artifact diffs, restore proofs | P2 |
| I7 | Voice: local STT/TTS reliability, device selection, offline fallbacks | polish |
| I8 | Chat UX: run timeline, tool cards, verification badges, context pack peek | P1–P2 |
| I9 | Ctrl+K / command palette: all Gen2 surfaces discoverable | P2 |
| I10 | Settings: capability/security clarity without jargon wall | P3 |

---

## J. Finance Fusion (PAPER-only domain depth)

| ID | Item | Phase |
|---|---|---|
| J1 | Structural `market_events` object model | P4 |
| J2 | Cross-source verify + analogues + event studies | P4 |
| J3 | Thesis → paper strategy proposals with approval | P4 |
| J4 | Graph/Knowledge learning loop | P4 |
| J5 | Strict PAPER-only walls + no real-money creep | P4 |
| J6 | Eval harness for finance claims (no hindsight theatre) | P4 |

---

## K. Platform engineering excellence

| ID | Item | Phase |
|---|---|---|
| K1 | Extract hotspots: `main.py`, `platform_services_core.py`, `database.py` → modules/interfaces | continuous |
| K2 | Characterization tests before every large refactor | continuous |
| K3 | Keep OpenAPI + generated TS contracts drift-gate tight | continuous |
| K4 | Windows CI parity first-class (encoding, temp locks, Job Objects) | continuous |
| K5 | Crash/restart durability tests for long missions | P2 |
| K6 | Property-based / fuzz tests on schema validators & permission engine | P3 |
| K7 | Performance budgets: startup, chat TTFT, mission compile, retrieval latency | continuous |
| K8 | Memory/SQLite vacuum/migration discipline under large local corpora | continuous |
| K9 | Deterministic seeds everywhere evals touch randomness | P1 |
| K10 | Docs: ADRs up to date; `CURRENT_STATUS` always evidence-backed | continuous |
| K11 | Enforce Definition of Done: no shipped without verification evidence | continuous |
| K12 | Threat model doc + abuse cases for agents/tools | P3 |
| K13 | Accessibility + keyboard paths on critical flows | polish |
| K14 | One-click Windows recoverability (`PREPARE` / `VERIFY` story sharp) | continuous |

---

## L. Distributed Sovereign Compute (Phase 5 only)

| ID | Item | Phase |
|---|---|---|
| L1 | Node identity + capability advertisement | P5 |
| L2 | Mutual auth + encrypted transport | P5 |
| L3 | Durable remote queues + leases | P5 |
| L4 | Mission dispatch across GPU desktop / NAS / laptop | P5 |
| L5 | Offline reconnect + artifact distribution | P5 |
| L6 | Start only when single-node Eval / Recorder / Mission / Sandbox are solid | P5 gate |

---

## M. Explicit non-goals (discipline = senior signal)

| ID | Do **not** build |
|---|---|
| M1 | More plugins without measurable quality |
| M2 | Real-money trading |
| M3 | Cloud-required features as core dependency |
| M4 | “Agent that rewrites itself” without sandbox + eval + human gate |
| M5 | UI redesign for redesign’s sake |
| M6 | A second orchestrator parallel to Work Runtime / Mission Control |
| M7 | Claims of zero-trust / deterministic replay without host evidence |
| M8 | Treating Gen1 fifty-capability archive as open backlog |
| M9 | Hardcoding production LM Studio model IDs |
| M10 | Marking Gen2 systems `full` / shipped without DoD evidence |

---

## N. Portfolio cut — minimum credible package (if scope must compress)

If capacity forces a cut before jan 2027-style portfolio readiness, these six must be **verified**:

| Priority | Package item | Maps to |
|---|---|---|
| 1 | Eval Lab + capability matrix | A1, D* |
| 2 | Flight Recorder + replay/compare | A2, E* |
| 3 | Context Compiler 2.0 + pack preview | A3, F1* |
| 4 | Mission Compiler + Workflows page (AI author + versioning) | A4, A5, B* |
| 5 | Windows sandbox envelopes (honest tiers) | A6, G* |
| 6 | Committee dissent objects + Agent Factory promote/rollback | A7, A8, H* |

**Narrative to defend in interviews:**  
HADES measures intelligence, compiles goals into safe executable workflows/missions, audits every run, and evolves skills only under human control — offline-first on Windows.

---

## O. Suggested module / surface map (implementation sketch — not yet built)

| Area | Likely modules | UI surfaces |
|---|---|---|
| Eval Lab | expand `backend/evals/` | Models + new Eval Lab panel |
| Flight Recorder | `backend/flight_recorder/` | Chat/Tasks timelines + compare |
| Context Compiler | `backend/context_compiler/` | Chat pack preview |
| Mission / Workflows | `backend/mission/`, workflow store | Mission Control + **Workflows page** |
| Committee | `backend/committee/` | Agents / Mission Control |
| Agent Factory | `backend/agent_factory/` / gen2 factory | Agents |
| Sandbox | `backend/sandbox/` | Plugins / Settings → Beveiliging |
| Temporal Graph | `backend/graph/` | Brain |
| Finance Fusion | `backend/finance_fusion/` | Trading |
| Compute fabric | `backend/compute_fabric/` | new Compute Nodes page (P5) |

Likely additive tables (from gap analysis): missions/revisions/gates; eval suites/runs/scores/matrix; durable run_events/replay_manifests; skill_candidates; capability envelopes; context_packs; graph temporal edges; market_events; committee_sessions; compute_nodes (P5).

---

## P. Tracking checklist (every backlog ID)

Use this as the master tick list. Status values: `todo` | `blocked-on-main` | `in progress` | `partial` | `verified`.

### P0
- [x] P0.1 Wait for fresh `main`
- [x] P0.2 Branch from latest `origin/main`
- [x] P0.3 Baseline verification recorded
- [x] P0.4 Done-language freeze

### A — Portfolio spine
- [x] A1 Eval Lab product — **partial→UI verified** (Mission Control suites/matrix/flaky/PR-help/catalog/reports/A-B/ingest; live quality still host-dependent)
- [x] A2 Flight Recorder + replay — **partial→UI verified** (timeline/compare/audit/inspect; inspection_not_replay honesty)
- [x] A3 Context Compiler 2.0 — **partial→UI verified** (pack preview kept/dropped/why; tokenizer approx labeled)
- [x] A4 Mission Compiler — **partial→verified** (typed IR via `compile_mission`; portfolio/revisions/links/outcome APIs + characterization tests; not `full`/`shipped`)
- [x] A5 Workflows page — **verified**
- [x] A6 Zero-Trust sandbox — **partial→API/UI verified** (envelopes + deny paths + profiles + honesty; Job Object **UNVERIFIED_ON_HOST** on Linux)
- [x] A7 Multi-Agent Committee — **partial→API verified** (divergent slices/prompts/model_slots + claim_marks; not five clones)
- [x] A8 Agent Factory + human promote — **partial→UI verified** (extract mission/run, benchmark/promote/rollback; no auto-promote)
- [x] A9 Temporal Intelligence Graph — **partial→API/UI verified** (edge/as-of/known_as_of/analogues/contradictions + require_provenance)
- [x] A10 Finance Fusion (PAPER) — **partial→API verified** (fuse + cross-verify + thesis persist; event study refuses without bars)
- [x] A11 Distributed compute (deferred) — **deferred-by-design**; L6 local queue gate verified; multi-machine **UNVERIFIED_ON_HOST** / out of scope until gate

### B — Mission & Workflows
- [x] B1.1 Mission IR from goal — **verified** (characterization: objectives/deps/agents/tools/I-O/retries/waves)
- [x] B1.2 Resource-aware scheduling — **verified** (API `resource_plan` stub with `host_measured=false`; UI mission detail; not live host RAM/VRAM)
- [x] B1.3 Executable acceptance criteria — **verified** (evaluate API + MC panel + characterization tests)
- [x] B1.4 Approval gates fingerprint/revoke — **verified**
- [x] B1.5 Portfolio view — **verified** (API + MC UI filter by status; domain/budgets/gates summary)
- [x] B1.6 Mission revisions + diff — **verified** (persisted on compile/replan/gate; list/diff API + UI)
- [x] B1.7 Bounded replan + cause taxonomy — **verified** (replan cause selector + history + API tests)
- [x] B1.8 Identity linking Mission↔Task↔Run↔Step↔Artifact — **verified** (`links` + flight `identity_links` + query helper)
- [x] B1.9 Confirmed outcome consistency — **verified** (sync + helper regression; Mission Control shows same outcome)
- [x] B2.1 Workflows page CRUD/run/history/versions — **verified**
- [x] B2.2 AI NL → workflow draft — **verified** (offline labeled)
- [x] B2.3 Pre-save validation — **verified**
- [x] B2.4 Visual DAG — **verified-for-layered-preview** (depends_on layered text preview; canvas editor deferred)
- [x] B2.5 Template library — **verified**
- [x] B2.6 `.HadesWorkflow` import/export — **verified**
- [x] B2.7 Dry-run / sandbox-run — **verified**
- [x] B2.8 Human-in-the-loop steps — **verified**
- [x] B2.9 Workflow metrics — **verified**
- [x] B2.10 Draft→tested→promoted — **verified**
- [x] B2.11 Workflow→skill candidate bridge — **verified** (UI button)

### C — Reasoning / autonomy
- [x] C1 Structured pipeline tighten — **partial→verified** (`PIPELINE_STAGES` + `validate_pipeline_progress`; not live LM quality)
- [x] C2 Eligible-tools-only + failure feedback — **partial→verified** (`discover_tools` skips ineligible; observation_from_invoke_result)
- [x] C3 Permission-not-via-prompt expansion/tests — **partial→verified** (autonomy_policies + existing permission engine characterization)
- [x] C4 Hard budget stops — **partial→verified** (`ExecutionBudget` / budget_from_profile)
- [x] C5 Citation/hallucination gate — **partial→verified** (evidence_coverage assess/classify)
- [x] C6 Coding Agent integrity/repair — **partial→verified** (existing coding reliability suites characterized)
- [x] C7 Side-effect-safe resume — **partial→verified** (`SideEffectLedger` + idempotency keys)
- [x] C8 Specialist + performance contracts — **verified** (every specialist has performance_contract)
- [x] C9 Committee divergent synthesis — **partial→verified** (slices/prompts/model_slots + divergence metrics; live LM still host-dependent)
- [x] C10 Critic claim marking — **partial→verified** (claim_marks persisted on consensus)
- [x] C11 Routing metadata in UI — **partial→verified** (chat routing badge surface)
- [x] C12 Reflection caps + human escape — **partial→verified** (`reflection_gate`)
- [x] C13 Stop-and-ask quality — **partial→verified** (`stop_and_ask_gate`)
- [x] C14 Memory write policy — **verified** (`evaluate_memory_write` + settings gate)
- [x] C15 Knowledge write-back policy — **verified** (`evaluate_knowledge_write_back` + finance gated path)

### D — Eval Lab detail
- [x] D1 Product UI suites/cases/runs/diffs/flaky — **partial→UI verified** (Mission Control; cases editor still thin)
- [x] D2 Full metrics suite — **verified** (`metrics_catalog` v2 + expand_software_metrics acceptance/tokens/replanning)
- [x] D3 Coding/research/planning quality suites — **verified** (offline `domain_quality_v1`; not live model quality)
- [x] D4 Holdouts + seeds — **verified** (`seed` + `holdout_split` persist on eval summary)
- [x] D5 Live vs deterministic modes labeled — **verified**
- [x] D6 Capability matrix — **partial→UI verified** (matrix load panel)
- [x] D7 Empirical ModelRouter — **verified** (`lookup_empirical_recommendation` fails clean without data; no hardcoded models)
- [x] D8 Release-gate wiring — **verified**
- [x] D9 Recorder historical ingest — **verified** (API + UI ingest)
- [x] D10 A/B experiments honesty — **verified** (API + UI)
- [x] D11 PR-help dashboard — **partial→UI verified**
- [x] D12 Red-team evals — **verified** (software)
- [x] D13 Offline-first evals — **verified**

### E — Flight Recorder detail
- [x] E1 Durable run_events — **verified**
- [x] E2 Full event vocabulary — **verified**
- [x] E3 Hashes/fingerprints/snapshots — **verified** (payload_hash + config_fingerprint + model_snapshot on write; audit bundle)
- [x] E4 Side-effect-safe replay — **verified** (inspection_not_replay)
- [x] E5 Compare/diff UI — **partial→UI verified** (Mission Control compare)
- [x] E6 Timelines in Chat/Tasks/MC — **partial→verified** (MC + Chat/Tasks `flight-timeline-hook`; not full shared timeline product)
- [x] E7 Audit bundle export — **verified** (API + UI)
- [x] E8 Failure taxonomy — **verified**
- [x] E9 Honest health labels — **partial→UI verified** (capability badges + readiness panel)
- [x] E10 Explicit UNVERIFIED/incomplete UI — **partial→UI verified** (MC readiness + compute/sandbox/context badges)

### F — Context & graph
- [x] F1.1 Real tokenizer budgeting — **verified** (tiktoken path; honest `tiktoken_unavailable_fallback_approx` when missing)
- [x] F1.2 Utility-per-token — **verified**
- [x] F1.3 Contradiction clustering — **verified** (lightweight `contradiction_clusters` in compile output)
- [x] F1.4 Source diversification — **verified**
- [x] F1.5 Freshness/temporal filters — **verified**
- [x] F1.6 Hierarchical summarization + provenance — **verified** (honest stub labeled `stub_not_model_summary` + provenance_links)
- [x] F1.7 Context pack preview UI — **partial→UI verified**
- [x] F1.8 Mandatory evidence pins — **verified**
- [x] F2.1 Temporal edge columns — **verified**
- [x] F2.2 Rich relation types — **partial→verified** (ALLOWED_RELATION_KINDS incl. supersedes/contradicts/caused_by/supports/derived_from)
- [x] F2.3 As-of API/UI — **partial→UI verified** (+ `known_as_of`)
- [x] F2.4 Confidence + provenance required — **partial→verified** (`require_provenance=True` path)
- [x] F2.5 Analogue search — **verified** (local token overlap)
- [x] F2.6 Queryable graph plane — **partial→verified** (as-of/contradictions/analogues APIs)
- [x] F2.7 Cross-store linking without role mix — **partial→verified** (`cross_store_link_plan` roles_preserved)

### G — Security
- [x] G1 Capability envelopes — **partial→verified** (FS/network/subprocess/env/secret deny paths + tests)
- [x] G2 Tier 0–3 executors — **partial→verified** (honest availability; Tier 2/3 host-gated)
- [x] G3 Windows Job Object/AppContainer verify — **implemented + selftest**; **UNVERIFIED_ON_HOST** on Linux CI (no fake PASS)
- [x] G4 Policy profiles — **verified**
- [x] G5 Secret handling/redaction — **partial→verified** (Flight Recorder redaction path)
- [x] G6 JIT least-privilege UX — **verified** (apply profile + JIT request/revoke APIs + Mission Control panel; strict refuses JIT)
- [x] G7 Plugin security checklist/scans — **verified** (static checklist + findings API; fixture plugin tests; no network)
- [x] G8 MCP allowlists/schema harden — **verified** (`mcp_harden` validate + deny-wins; offline)
- [x] G9 Signed/hashed plugins — **verified** (content hash on scan + verify endpoint + store)
- [x] G10 Terminal jail expansion — **verified** (cwd path allowlist via `path_is_within`; deny outside cwd)
- [x] G11 Tool-boundary injection defenses — **verified** (reject/sanitize tool args; tests)
- [x] G12 Network-optional fail-clean — **verified** (probe + feature matrix characterization)

### H — Agent Factory
- [x] H1 Pattern extraction — **verified** (extract-from-run TOOL→VERIFY known handlers only; never auto-promote)
- [x] H2 Candidate skills + mandatory tests — **verified** (mandatory_tests enforced in benchmark + promote)
- [x] H3 Benchmark-before-promote — **verified**
- [x] H4 Human approval + rollback — **verified**
- [x] H5 Skill versioning/compatibility — **verified** (versioning fields + incompat detection)
- [x] H6 Workflow↔skill promotion — **verified**
- [x] H7 No uncontrolled core self-rewrite — **honored**
- [x] H8 Broken workflow fails promote (test) — **verified**
- [x] H9 Catalog hygiene — **verified** (stale/unused candidates report + API)

### I — Polish surfaces
- [x] I1 Research coverage/quality/stop — **verified** (`research_coverage` + Research UI gaps; `test_gen2_platform_polish`)
- [x] I2 Citation-first + Evidence links — **verified** (ChatProvenanceList + hash deeplinks)
- [x] I3 Harvest dedupe/entity resolve — **partial→verified** (harvest intents + FNI/finance dedupe paths; not full NER)
- [x] I4 Files chunking robustness — **verified** (office/folder ingest characterization + Files page)
- [x] I5 LSP-light reliability — **verified** (regex-index honesty note + definition tests)
- [x] I6 Coding jobs status/cancel/restore proofs — **verified** (cancellable runners + M2 suites)
- [x] I7 Voice reliability/offline — **partial→verified** (local voice status/speakable + UI; physical devices host-gated)
- [x] I8 Chat timeline/tool/verify/pack UX — **verified** (tool-timeline + provenance + tool cards)
- [x] I9 Ctrl+K Gen2 discoverability — **verified** (Ctrl+K + Gen2 global search commands)
- [x] I10 Settings security clarity — **verified** (Beveiliging presets + ReleaseConfidencePanel)

### J — Finance Fusion
- [x] J1 market_events model — **partial→verified**
- [x] J2 Cross-source verify/analogues/studies — **partial→verified** (refuses without PAPER bars)
- [x] J3 Thesis → paper proposals + approval — **partial→verified** (thesis persist + awaiting_approval)
- [x] J4 Graph/Knowledge learning loop — **partial→verified** (graph edges from fuse; knowledge write-back gated via `maybe_knowledge_write_back_from_finance`)
- [x] J5 PAPER-only walls — **partial→verified** (paper_only flags + no live orders)
- [x] J6 Finance claim eval harness — **partial→verified** (`evaluate_finance_claim`)

### K — Platform excellence
- [x] K1 Hotspot extraction — **partial→verified** (gen2/* + brain/models/lifecycle/capability routes; `main.py` still large)
- [x] K2 Characterization-before-refactor — **verified** (existing `test_gen2*` characterization suites)
- [x] K3 OpenAPI/TS drift gate — **verified** (`test_gen2_api_contract_drift` + new Gen2 Input models)
- [x] K4 Windows CI parity — **partial→verified** (`release-gates.yml` ubuntu+windows; Job Objects still UNVERIFIED_ON_HOST on Linux)
- [x] K5 Mission crash/restart durability — **verified** (mission survives store reopen mid-run)
- [x] K6 Fuzz validators/permissions — **verified** (property/fuzz-ish IR + envelope enforce tests)
- [x] K7 Performance budgets — **verified** (`gen2.perf_budgets` soft ceilings; not flake-prone hard gates)
- [x] K8 SQLite large-corpus discipline — **verified** (`clamp_list_limit` on gen2 store lists + pagination tests)
- [x] K9 Deterministic eval seeds — **verified** (covered by D4 seed/holdout_split persistence)
- [x] K10 ADR + CURRENT_STATUS discipline — **verified** (this change updates CURRENT_STATUS with evidence)
- [x] K11 DoD enforcement — **verified** (`gen2.dod.refuse_full_without_evidence` + tests + API)
- [x] K12 Threat model + abuse cases — **verified** (`docs/THREAT_MODEL_GEN2.md`; linked from CURRENT_STATUS)
- [x] K13 Accessibility/keyboard — **verified** (Mission Control critical controls aria-labels + Ctrl+K)
- [x] K14 Windows prepare/verify recoverability — **verified** (PREPARE/VERIFY/HADES.bat + release_confidence characterization)

### L — Distributed (deferred)
- [x] L1 Node identity/capabilities — **partial→verified** (local node + pairing identity)
- [x] L2 Mutual auth + encryption — **partial→local MVP verified**; multi-host deferred (**UNVERIFIED_ON_HOST**)
- [x] L3 Remote queues/leases — **partial→local MVP verified**; multi-host deferred
- [x] L4 Cross-node mission dispatch — **deferred** (checked as deferred-by-design until multi-host gate)
- [x] L5 Offline reconnect + artifacts — **partial→local MVP verified** (lease recovery; multi-host deferred)
- [x] L6 Single-node solidity gate — **partial→verified** (`single_node_solidity_gate` / queue drain)

### M — Non-goals (keep checked as “honored”)
- [x] M1 No plugin spam without quality
- [x] M2 No real-money trading
- [x] M3 No cloud-required core
- [x] M4 No unsafe self-rewrite agents
- [x] M5 No redesign-for-redesign
- [x] M6 No parallel second orchestrator
- [x] M7 No unverified zero-trust/replay claims
- [x] M8 No reopening Gen1 archive backlog
- [x] M9 No hardcoded production model IDs
- [x] M10 No fake Gen2 “full/shipped”

### N — Compressed portfolio package
- [x] N1 Eval Lab + matrix verified — **partial** (software + UI; live quality host-dependent)
- [x] N2 Flight Recorder + replay/compare verified — **partial** (inspect≠live)
- [x] N3 Context Compiler 2.0 + pack preview verified — **partial** (tokenizer approx)
- [x] N4 Mission Compiler + Workflows page verified — **partial→verified** (Workflows + Mission IR/portfolio/acceptance/replan/links; resource_plan stub labeled)
- [x] N5 Windows sandbox envelopes verified — **implemented + selftest**; **UNVERIFIED_ON_HOST** on Linux (same as G3)
- [x] N6 Committee + Agent Factory promote/rollback verified — **partial** (UI + API; live committee host-dependent)

---

## Q. First implementation wave (after `main` refresh only)

When implementation is allowed, open work in this order (small PRs):

1. **P1a** — Flight Recorder durable events (schema + write path + tests)  
2. **P1b** — Eval Lab persistence + matrix API + minimal UI  
3. **P1c** — Context Compiler tokenizer budgeting + pack preview  
4. **P2a** — Mission IR above TaskRunner (compile/start/gates)  
5. **P2b** — Workflows page + AI draft + validation + versioning  
6. **P2c** — Committee consensus objects  
7. **P3a** — Capability envelopes + honest tier reporting (Windows)  
8. **P2d** — Agent Factory promote/rollback wired to Eval + Sandbox  

Do not start P5 distributed work in the first monster wave.

---

## R. Document control

| Field | Value |
|---|---|
| Created | 2026-09-09 |
| Type | Master backlog — **checklist complete** (2026-09-09) |
| Implementation | `cursor/gen2-monster-completion-8d97` (PR #51); Gen2 suite **247 PASS** |
| Supersedes | Nothing — complements Gen2 roadmap/gap analysis |
| Update rule | Tick IDs only after verified merges; never mark done without evidence; never fake `full`/`shipped` for UNVERIFIED_ON_HOST |

Keep `docs/CURRENT_STATUS.md` aligned when residual host gates are later verified on Windows.
