# LEVIATHAN FRONTIER PROGRAM — A to Z

> Status: **APPROVED 2026-09-24 — building.** Delivered on branch `cursor/frontier-program-plan-1e6d`:
> F1 (trade orchestras + trading agents on the fleet, isolation G64), F2 (deliberation protocol,
> deterministic risk authority, append-only decision records G65, migration 43), F4 partial (news
> pipeline via provider_io with causal `available_at`, `BrainFacade.retrieve(as_of)`, G61–G63),
> F0-lite (`knowledge.ingest_scan` externalized for `/api/knowledge/ingest/scan` + `/api/neuro/absorb`;
> `market_sim.news.poll` on the market_sim pool), F8 (Agents page section 9 + `/trading/onderzoek`, G66).
> Evidence: `Data/backend/tests/test_trading_orchestra.py` (25 passed),
> `python3 scripts/verify_trading_100.py --run-tests` (G61–G66 PASS). Still open: F3 kernel v2 / sealed
> evaluation (readiness stays `UNMEASURED`), F5 strategy learning loop, F6 research campaigns, F7 paper
> fills from orchestra intents, remaining F0 routes (`agents/execute`, `agents/multi`, `neuro/soak` — see §1).
>
> Originally written as a proposal after reading `Data/backend/main.py`,
> `Data/modules/workers/*`, `Data/modules/market_sim/*`, `Data/modules/agents/*`,
> `Data/docs/leviathan_system.md`, `execution_fabric.md`, `background-workers.md`,
> `trading_program.md` (v4), `trading_gap_report.md`, `trading_program_state.md`,
> `FIX_REPORT_CHAT_BRAIN_WORKERS.md`. `Data/HADES` and `editor/` were **not** read
> (operator instruction) and remain out of scope.
>
> When this document disagrees with code and tests, code and tests win.
> This program **extends** Trading Master Program v4; it does not replace it.
> Where v4 already defines a gate or subphase, this document references it instead of
> re-specifying it.

---

## 0. Verdict on LEVIATHAN's current reasoning

What is right and must be kept (these are the reasons the system can become frontier at all):

- One control plane, one SQLite, one job kernel, one gateway, one secrets broker, one
  settings plane. No parallel stacks. Every proposal below reuses these owners.
- The invariants: `model output != evidence`, `dispatch != completion`,
  `unmeasured != passed`, `capability != authority`, `retrieved context != trusted fact`.
- Truthful failure (`UNAVAILABLE` / `UNMEASURED` / 409 / 501) instead of fabricated success.
- The worker fabric already exists (`JobStore` leases, `WorkerSupervisor`, 20 pools,
  `EXTERNAL_WORKER_CAPABILITIES`). Externalization is a wiring problem, not an
  architecture problem.
- Evaluation is release authority; the post-training flywheel (preferences → DPO →
  champion/challenger) already exists as a boundary.

What blocks "top frontier" today (verified in source):

| # | Blocker | Evidence |
|---|---|---|
| B1 | `main.py` is 5 900 lines and is **not** a composition root. `POST /api/chat` alone is ~1 000 lines (2000–2988) and runs deep recall, staged retrieval + rerank, atlas, why-library, memory search, neuro advisor, cortex runtime, residual orchestration and model routing **inline in the request**. | `main.py` 2000–2988; own doc says "`main.py` must remain composition-oriented" (`leviathan_system.md` §3.1). |
| B2 | Heavy operator routes still execute synchronously in the API process: `knowledge/ingest/scan`, `knowledge/ingest/path`, `neuro/absorb`, `neuro/soak`, `neuro/contrastive`, `agents/execute`, `agents/multi`, `capabilities/{id}/execute`, `functions/{id}/execute`, `backup/restore`, knowledge atlas revise. | route table in `main.py` 3308–5872. |
| B3 | Startup does network discovery and multi-domain reconcile before the API is ready (`model_plane.reconcile_startup`, `dataset_service.reconcile`, `training_service.reconcile`, `agent_fleet.reconcile`, `research_service.recover`) and owns an asyncio serving-reconcile loop + telemetry sampler thread. | `lifespan` 1383–1626. |
| B4 | Cognitive Runtime `submit()` and `AgentRuntime.execute()` run in-process; there is no `cognition.advance` job kind. | `cognition/runtime.py:209`, `main.py:4113`. |
| B5 | Trading: 28 confirmed defects (D1–D31). Sharpe mis-annualized, ~1 % sizing, no round-trip ledger, restart-unsafe, per-bar SQLite connection, soft lease, routes bypass Gateway, "agents" are DSL tweaks, no LLM anywhere in the loop, no news, no `as_of` in `BrainFacade`, strategy memory never hydrated. | `trading_gap_report.md`; `brain_hooks.py` has no `as_of`; `rg -i news market_sim/` → 0 hits. |
| B6 | Learning loops are open: trading outcomes never reach the flywheel; agent scorecards, readiness ladder, trajectory export do not exist (G26–G31 NOT_STARTED). | `trading_program_state.md`. |
| B7 | Agents page shows the Fleet, but trading roles are `specialist`/`research` kinds with a `trading` tag; there is no first-class trading agent kind, no orchestra concept, no mandate/autonomy/readiness on the card. | `roles.py`, `fleet_types.py`, `AgentsPage.tsx:77`. |

Conclusion: the architecture is frontier-capable; the **process topology** (B1–B4) and the
**trading truth** (B5–B7) are not. Fix topology first — every later subsystem (trade agents,
news readers, campaigns, gym, flywheel) needs worker pools that do not import `main.py`
and a chat/API process that stays interactive while they run (v4 gate G51).

---

## 1. Externalization decision — what leaves `main.py` and where it goes

Classification used below:

- **SYNC** — stays in the API request (interactive fast path, bounded, no model call, no bulk I/O).
- **BOUNDED-REMOTE** — API enqueues a job and awaits the result with a hard timeout;
  on timeout it degrades honestly (same pattern as `provider_io`).
- **EXTERNAL** — API validates/authorizes/enqueues and returns a job id immediately.
- **ROUTER** — pure composition cleanup: moves to a `routes/*.py` builder; execution
  location unchanged.

### 1.1 Chat turn (`POST /api/chat`) → `Data/modules/chat/` + `routes/chat.py`

Stays SYNC (per `FIX_REPORT` §11, unchanged): validation, authority checks, behavior
snapshot, intent/retrieval gate, **fast lexical** index search (Tier 0), context compile,
model stream + normalize, persistence.

Becomes BOUNDED-REMOTE (new job kinds, existing pools):

| Work today inline | Job kind | Pool | Timeout / fallback |
|---|---|---|---|
| `deep_recall_service.recall` | `knowledge.deep_recall` | `knowledge_prepare` | budgeted by `EconomyGovernor`; fallback = lexical hits, `retrieval_source=lexical_fallback` |
| `staged_retriever` rerank stage | `rerank.batch` (exists) | `rerank` | fallback = un-reranked fusion, `rerank=skipped` |
| `cortex_runtime.run` + `residual_orchestrator` | `neuro.cortex` | `evaluation` (MODEL_INFERENCE) | fallback = advisory-only, `cortex=UNAVAILABLE` |
| `neuro_memory.retrieve` tiers 1–2 | `neuro.memory_retrieve` | `knowledge_prepare` | fallback = Tier 0 only |

Rule: chat never blocks on a worker longer than `chat.enrichment_timeout_ms` (Settings,
default 1 500 ms). The SSE stream carries a `context_enriched` frame when a late result is
still useful for the *next* turn (stored on the conversation, never injected mid-answer).

Cognition (`cognition_runtime.submit`) becomes EXTERNAL: job kind `cognition.advance`
in the `agents` pool; chat returns `cognition_run_id`, UI subscribes to `/api/cognition/*`
events (already exists).

### 1.2 Operator routes

| Route | Decision | Job kind → pool |
|---|---|---|
| `POST /api/knowledge/ingest/scan`, `/ingest/path` | EXTERNAL | `knowledge.prepare` → `knowledge_prepare`, commit via `knowledge.commit` lane |
| `POST /api/neuro/absorb` | EXTERNAL (it *is* `knowledge.ingest_scan`) | same lane |
| `POST /api/neuro/soak`, `/neuro/contrastive`, `/neuro/cortex/run` | EXTERNAL | `evaluation.run` → `evaluation` |
| `POST /api/agents/execute`, `/agents/multi` | EXTERNAL | `agent.advance` → `agents` |
| `POST /api/capabilities/{id}/execute` | SYNC if `side_effects=READ` and estimated cost small; else EXTERNAL | `general` |
| `POST /api/functions/{id}/execute` (`pdf_parser`, `csv_inspector` on large inputs) | EXTERNAL above size threshold (Settings) | `general` |
| `POST /api/evaluation/*` | EXTERNAL **always** (drop the inline branch; keep tests via `run_until_idle`) | `evaluation` |
| `POST /api/backup/restore` | EXTERNAL, approval-gated | `backup.restore` → `backup` |
| `POST /api/knowledge/atlas/{id}/revise` | EXTERNAL | `knowledge.prepare` |
| `POST /api/context/preview` | SYNC (pure compute, bounded) | ROUTER only |
| `POST /api/training`, `/flywheel/*`, `/training/synthetic/generate`, `/active-learning/mine` | EXTERNAL | `training.control` / `dataset.process` |
| `/api/browser|media|voice|multimodal` | already Gateway/job fixtures | ROUTER only |
| `/api/trading/order` (501 stub) | SYNC | ROUTER only |

### 1.3 Lifespan / background ownership

| Today in API process | Target owner |
|---|---|
| `migrations.apply_all()` | stays (fast, required before serve) |
| `model_plane.reconcile_startup()` (network discovery) | `maintenance.reconcile` job enqueued at boot; `/api/health` reports `reconcile: PENDING/DONE/FAILED` |
| `dataset_service.reconcile`, `training_service.reconcile`, `agent_fleet.reconcile`, `research_service.recover`, `cognition_store.reconcile_interrupted` | same boot job (one idempotent reconcile capability per domain) |
| `_serving_reconcile_loop` (asyncio, 15 s) | `schedule.tick` → `maintenance.reconcile(domain=serving)`; ServingSupervisor process ownership stays in Model Control Plane |
| `system_telemetry_sampler` thread | `telemetry` pool default_count 1 when workers enabled (pool exists, currently 0) |
| in-process `job_runtime.start_background_worker()` | only when `LEVIATHAN_WORKERS_ENABLED=false` (legacy/test path) |

### 1.4 Composition split (mechanical, behavior-preserving)

```
Data/backend/main.py            ≤ 300 lines: app factory + include_router + lifespan
Data/backend/composition.py     object graph (stores, services, planes) — importable by workers
Data/backend/routes/chat.py     POST /api/chat, conversations           ← from main.py 1958–2988
Data/backend/routes/knowledge.py  knowledge/atlas/deep-recall/why/ingest
Data/backend/routes/execution.py  capabilities/functions/jobs/workers/approvals/observations/evidence/verification
Data/backend/routes/memory.py
Data/backend/routes/neuro.py
Data/backend/routes/evaluation.py (+ isolation)
Data/backend/routes/workflows.py  (+ schedules)
Data/backend/routes/flywheel.py   (+ /api/training/* preference/synthetic/active-learning)
Data/backend/routes/runtimes.py   browser/media/voice/multimodal/native
Data/backend/routes/ops.py        health/metrics/product-truth/architecture/telemetry/backup/chaos/release/security/master
Data/modules/chat/turn_pipeline.py   ChatTurnPipeline (stages, each with SYNC/BOUNDED-REMOTE contract + timing)
```

Existing architecture test "pool workers must not import `Data.backend.main`" stays; a new
test asserts workers may import `Data.backend.composition` and that `main.py` line count
< 400. Every route keeps its path, body and response shape (contract tests in
`test_round9_product_truth.py` style).

---

## 2. A to Z — every subsystem to frontier

Each letter: **owner** · **today** · **frontier target** · **how it is verified**.
"Frontier" here means: durable, externalized where heavy, measured, self-improving where
evidence allows, honest where it does not.

**A — Agents (Fleet / Runtime / Cognition).** Today: fleet + missions, cognition in-process,
kinds `generic|coding|research|orchestrator|specialist`. Target: new kind `trading`
(§3), `cognition.advance` and `agent.advance` as the only execution paths, schema-validated
JSON I/O with retry-with-repair for every role executor, per-agent scorecards and a
readiness ladder that is enforced by policy (not by UI). Verified: fake-LLM e2e missions,
restart mid-mission without duplicate side effects.

**B — Brain (Knowledge V2 / Memory / Atlas / Why).** Today: hybrid retrieval, no `as_of`.
Target: point-in-time retrieval everywhere (`available_at` on chunks and memories,
`as_of <= decision_time` enforced in `BrainFacade` and trading MarketView), index
generations atomic (exists), embeddings/rerank always in pools. Verified: leakage test
(document dated after `as_of` never retrievable), doc/code parity test (D22 → G23).

**C — Chat / Cognition.** Today: 1 000-line inline turn. Target: `ChatTurnPipeline`
(§1.1), per-stage timing in observability, enrichment via bounded jobs, cognition external.
Verified: p95 turn overhead (excluding model) under a Settings envelope while a 2.6 M-bar
simulation and a campaign run in workers (v4 G51).

**D — Datasets / Data platform.** Today: strong for text datasets; market data is
all-or-nothing CSV. Target: trading datasets are Dataset versions (content-addressed,
quality report, quarantine, split manifests TRAIN/VALIDATION/SEALED) reusing
`Data/modules/datasets` shard/mixture/contamination code instead of a second data platform
(v4 T2A–T2C). Verified: G01–G06.

**E — Evaluation.** Today: platform + scorecards, inline branch remains. Target: always
external; trading validation (WFA, CPCV, PSR/DSR/PBO, robustness, sealed single-use) is an
`EvaluationPlatform` suite family, not a private trading evaluator; agent scorecards are
evaluation reports. Verified: G18–G21, G27, G46.

**F — Flywheel / Training.** Today: preferences → DPO → promote/rollback exists, nothing
feeds it from agents. Target: trading trajectories (verified outcomes only, sealed-window
contamination scan) → preference pairs / SFT via existing Datasets/Training → challenger
trading model → champion/challenger on the readiness ladder. Verified: G29, no training
row references a SEALED window (test).

**G — Gateway / Capabilities / Approvals.** Today: trading routes bypass. Target: every
trading side effect (run start, paper order, promotion, limit loosening, kill-switch reset)
is a registered capability with receipts; Risk Officer veto and human-only
`LIVE_ELIGIBLE` are policy, not prompt text. Verified: G37, patch-every-run-path bypass test.

**H — Health / Observability / Status.** Target: `/api/health` includes reconcile state and
worker heartbeat ages; `category=trading` events; queue wait, run-advance latency,
bars/sec, feed staleness, paper-loop lag measured or `UNMEASURED`. Verified: G49, G58.

**I — Ingestion (source_ingestion → Knowledge).** Target: news items (§3.4) enter through
the same pipeline as any document, with `available_at` provenance and licensing state.
Verified: G55-style provenance test for news.

**J — Jobs / Workers.** Today: complete kernel, partially used. Target: §1 fully applied;
new job kinds registered in `EXTERNAL_WORKER_CAPABILITIES`, `execution/builtins.py` and
`pools.py`; `market_sim.advance` on the lease path only; two-worker double-claim
impossible; interactive priority via existing resource admission. Verified: G38, G51, G52.

**K — Kernel (trading simulator).** Today: two engines, two fill models, float + Decimal.
Target: Kernel v2 (v4 T3A–T3C): one causal engine, multi-asset, long/short,
MARKET/LIMIT/STOP/STOP_LIMIT, TIF, bracket/OCO, partials, instrument rules, margin gated
OFF, checkpoint/resume byte-identical, bounded-memory iterator. `multi_engine` +
commit-reveal kept for competition games (fixed per D30). Verified: G08–G14.

**L — Library (strategy memory).** Target: hypotheses, versions, lineage, positive **and
negative** results, post-mortems `trust=agent_proposed` until verified, similarity, lessons
hydrated into runs with `available_at` causality. Verified: G22.

**M — Models / Serving.** Today: full control plane. Target: role routing gets trading
roles (`trading.analyst`, `trading.news`, `trading.author`, `trading.critic`) with measured
routing; serving reconcile moves out of API (§1.3); model version is part of every
promotion-grade provenance fingerprint. Verified: G53.

**N — News & Event Intelligence (new).** §3.4. Verified: G61–G63 (new gates below).

**O — Orchestration (Workflows / Schedules).** Target: research campaigns, nightly
validation batches, news polling cadences and decay monitors are Workflows + Schedules,
not private timers. Verified: schedule tick → campaign step (test).

**P — Paper trading.** Target: `PaperForwardRunner` (v4 T9A): persistent per-session
wallets, strategy/agent → intent loop, idempotent client order ids, reconciliation vs
shadow ledger, drift bands, sim-to-real gap report. Verified: G32, G33, G30.

**Q — Quality & statistics.** Target: Metrics v2 only from the ledger, global append-only
Trial Ledger, FDR/power calibration on synthetic noise / planted-edge datasets. Verified:
G18, G19, G46.

**R — Research.** Today: durable research with web provider abstraction. Target: the
trading News Analyst and Macro Analyst reuse `research/web.py` + `provider_io` for fetch
and the research evidence ledger for claims; no second web client. Verified: grep test "no
raw urllib in trading adapters" (G07).

**S — Settings / Secrets / Security.** Target: all trading thresholds, autonomy defaults,
news sources, enrichment timeouts in the Settings Control Plane (`markt_sim` section);
Alpaca/news keys only via `SecretsBroker`; live flag validated OFF; security auditor
includes trading posture. Verified: G40, G48.

**T — Trade Orchestras & Trade Agents (new).** §3. Verified: G24, G25, G28, G64–G66.

**U — UI / Frontend.** Target: Agents page shows trading kind, orchestras, mandate,
autonomy, readiness, labeled paper PnL (§3.6); TradingCenter pages per v4 T10A–T10D
(Onderzoek, Validatie, Bibliotheek, Training, Risico added when their backend exists);
typed contracts, no `Record<string, unknown>` for stable objects. Verified: G41, G42, G57, G59.

**V — Verification / Evidence.** Target: validation verdicts, promotion transitions,
incidents and news-signal provenance are Evidence records; Evidence Vault lists them.
Verified: G21, G36 (hash-chained audit).

**W — Wallets / Risk.** Target: Risk Engine v2 on **every** order path (manual, strategy,
agent, paper), continuous breakers, global + per-strategy kill switch with human reset,
loosening approval-gated. The Risk Officer *agent* explains; the Risk Engine *decides*.
Verified: G34.

**X — eXternalization of `main.py`.** §1. Verified: `main.py` < 400 lines, no heavy
route runs inline when workers enabled (test enumerates routes and asserts job ids), all
existing route contract tests green.

**Y — Yield scorecards & readiness.** Target: per agent-version × regime × year with
CIs, violation counts (risk rejections, override attempts, causality attempts), token and
latency cost, multiple-testing penalty; ladder A0 gym → A1 validation → A2 sealed once →
A3 shadow paper → A4 autonomous paper; A5 live blocked. Verified: G27, G28.

**Z — Zero-trust live boundary.** Unchanged and strengthened: `LiveTradingGuard` +
`TradingStub` refuse; `LiveBroker = UNSUPPORTED`; only a human can enter `LIVE_ELIGIBLE`;
an orchestra has `cannot_enable_live=true` by construction. Verified: G35, G48.

---

## 3. Trade Orchestras and Trade Agents — design

### 3.1 Concepts (all on the existing Agent Fleet; no second fleet)

| Concept | Implementation | Notes |
|---|---|---|
| **Trade Agent** | `AgentDefinition` with new `AgentDefinitionKind.TRADING` | Only usable inside trading missions/campaigns; refused for coding/research plans. Carries `mandate`, `autonomyLevel`, `readiness`, `modelRef`, `budget`. |
| **Trade Orchestra** | `AgentDefinition` kind `ORCHESTRATOR` with `role=trade_orchestra` and `OrchestratorConfig.memberAgentIds` = trade agents | Owns: universe, paper capital allocation, mandate (risk limits), cadence, campaign budget, readiness ceiling. `cannot_enable_live=true` immutable. |
| **Mandate** | typed object persisted on the agent | max gross/net exposure, per-trade risk-to-stop, max orders/day, allowed instruments/families, allowed order types, autonomy level A0–A4. Loosening = approval. |
| **Mission** | existing `AgentMission`, advanced by `agent.advance` in the `agents` pool | Kinds: `research_campaign`, `deliberation_round`, `news_digest`, `post_mortem`, `paper_session`. |
| **Decision record** | append-only `market_decisions` | proposal → critique → risk decision → order intent → fill → post-mortem, each with `as_of`, prompt/output artifacts, model version. |

### 3.2 Roles (extends `roles.py`; existing 7 roles are kept and re-typed to `TRADING`)

| Role | Reads | Produces (schema-validated) | Authority |
|---|---|---|---|
| `trade_orchestra` | campaign state, scorecards, budgets | assignments, stop decisions, cadence | manages task; may not order, veto or enable live |
| `signal_analyst` | bounded `MarketView` (features, regimes) | `SignalProposal{instrument, direction, horizon, confidence, rationale, featureRefs}` | may propose |
| `news_analyst` | news items with `available_at <= as_of` | `NewsSignal{instruments, eventType, direction, magnitude, confidence, horizon, evidenceRefs}` | may propose; never orders |
| `macro_regime_analyst` | calendar, cross-asset features, news digests | `RegimeHypothesis` | may propose |
| `strategy_author` | library lessons (`as_of`), spec schema | Strategy Spec v2 candidate **or** sandboxed code candidate (v4 T3D/T3E) | may propose; each candidate → Trial Ledger row |
| `critic` | proposals, candidates | `Counterargument{riskFlags, falsificationTests}` | may veto (non-binding) |
| `risk_officer` | intents, wallet, mandate | `RiskExplanation` | **binding veto is the deterministic Risk Engine v2**; the agent explains, cannot loosen |
| `execution_agent` | approved intents | `OrderIntent` (order type, limit/stop, TIF) → kernel / paper broker | may order within mandate; all through Gateway |
| `evaluator` | run ids only | validation verdict request | independent; never trades in design window |
| `postmortem_agent` | closed trades, decision records | `Lesson{claim, evidenceRefs, trust=agent_proposed}` → Library + Memory | may write lessons; cannot mark verified |

### 3.3 Decision cadence (no LLM in the per-bar hot loop)

- Kernel steps bars deterministically in the `market_sim` pool.
- Agents deliberate at an explicit, recorded cadence (`decision_cadence`: `daily_close`,
  `hourly`, `every_n_bars`, `event_driven`) — v4 D31 fix — as `agent.advance` jobs in the
  `agents` pool (MODEL_INFERENCE resource class).
- Between deliberations the last committed strategy/order plan runs; commit-then-reveal
  seals the full observation set (D30 fix).
- Backtests with LLM agents are **budgeted** (max model calls per campaign, Settings) and
  are always paired with a deterministic replay of the resulting strategy version so the
  result is reproducible without the model.

### 3.4 News & Event Intelligence (new sub-domain `Data/modules/market_sim/news/`)

Sources (all through `provider_io`, network policy, `SecretsBroker`):

- RSS/Atom feeds (operator-configured list in Settings) — no key required.
- Configured HTTP news/search APIs (keyed; optional).
- Historical news datasets supplied by the operator (e.g. archive exports) imported as
  Dataset versions with `published_at` — required for any backtest that uses news.

Pipeline:

```
schedule.tick → provider.news.fetch (provider_io) → market_news_items
  (source, url, hash, published_at, fetched_at, available_at, license_state=UNKNOWN unless declared)
  → source_ingestion.process → Knowledge V2 document with available_at provenance
  → agent.advance(news_analyst) → NewsSignal rows (as_of = available_at)
  → MarketView.news(as_of) exposes only signals with available_at <= decision_time
```

Rules:

- `available_at = max(published_at, fetched_at) + declared_latency` for live; for
  historical datasets `available_at` must be present or the dataset is capped below
  promotion-grade (`NEWS_TIMING: UNMEASURED`).
- A `NewsSignal` is data, not authority; it enters strategies as a feature with a declared
  lookback like any other feature (G15 no-look-ahead test applies).
- Prompt-injection posture: article text is untrusted `reference_context` (same boundary
  as Brain chunks in chat); signals are schema-validated; no capability calls from the
  news reader.

### 3.5 Self-learning — what "learning" means here (honest)

1. **Strategy evolution** (fast loop): hypothesis → candidate → Trial Ledger → validation
   → library lesson, including negative results. Search: grid/random/mutation/crossover
   (v4 T7C). Agents author and critique; the platform computes every number.
2. **Memory** (medium loop): lessons and post-mortems retrievable with `as_of`, trust state
   upgraded only by verified evidence.
3. **Scorecards + readiness** (medium loop): agent versions move A0→A4 on CIs, violations
   and cost; demotion on decay.
4. **Model improvement** (slow loop): verified trajectories → preference pairs → DPO/SFT via
   the existing flywheel → challenger model registered in the Model Control Plane →
   champion/challenger through the same ladder. Optional RL adapter via TradingGym
   (v4 T8C) — reward computed by the kernel only.

Not claimed: profitability, gym→real transfer, live readiness.

### 3.6 Agents page integration (`/agents`)

- New kind filter **Trading**; roster groups orchestras with their members.
- Orchestra card: mandate summary, autonomy level, readiness ceiling, active mission,
  campaign budget burn, **paper** PnL and drawdown (always labeled `paper`/`simulatie`,
  never mixed with backtest), risk-engine state, kill-switch state.
- Trade-agent card: role, model ref, readiness A0–A4, scorecard CIs, violations, cost.
- Actions: create orchestra (wizard: members, universe, mandate, cadence), launch
  campaign / news digest / post-mortem mission, pause/cancel, open in
  `/trading/onderzoek`. Loosening a mandate or resetting a kill switch shows the approval
  flow. No decorative controls (G57 applies to this page too).
- `/api/agents/roster` and `/api/agents/system` extend with trading fields; contracts typed
  in `types/api.ts`.

### 3.7 New gates (append to `trading_gates.json` after v4 G60)

- **G61** News provenance: every news item has source, hash, `published_at`, `fetched_at`,
  `available_at`, license state; items fetched only through `provider_io`.
- **G62** News causality: poison-future test — an article with `available_at > as_of` is
  unreachable from `MarketView`, `BrainFacade` and any strategy feature.
- **G63** News-reader safety: schema-validation failure → repair → honest failure; article
  text can trigger no capability call; injection corpus test.
- **G64** Trading kind isolation: `TRADING` agents are refused by coding/research planners;
  orchestras cannot enable live by any route (test patches every mutation path).
- **G65** Decision record completeness: every paper/agent order links proposal → critique →
  risk decision → intent → fill → post-mortem with `as_of` and model version.
- **G66** Agents page truth: trading cards render only backend fields; paper vs simulation
  never mixed; `UNMEASURED` rendered as such (client contract test).

---

## 4. Execution order (phases; one subphase per session as in v4 Part K)

No calendar estimates. Order is driven by dependencies.

| Phase | Content | Depends on | Maps to v4 |
|---|---|---|---|
| **F0 Topology** | §1: composition split, `ChatTurnPipeline`, external/bounded-remote job kinds, boot reconcile job, telemetry/serving reconcile out of API, route contract tests, `main.py` < 400 | — | prerequisite for G51 |
| **F1 Trading truth** | D1–D8, D10, D30, D31 fixes | F0 (worker pools reusable) | T1A–T1D |
| **F2 Trading on the fabric** | Gateway capabilities, `market_sim.advance` on leases, two-worker test, idempotency, secrets/settings | F0 | T4A–T4C |
| **F3 Trade Agents & Orchestras** | `TRADING` kind, orchestra + mandate, role executors with fake-LLM e2e, decision records, Agents page | F2 | T7A + new |
| **F4 Point-in-time Brain + News** | `as_of` everywhere, news pipeline, `news_analyst`, G61–G63 | F3 | T6B + new |
| **F5 Validation & Library & Promotion** | Metrics v2, Trial Ledger, WFA/CPCV/robustness/sealed, Library, promotion SM | F1 | T5A–T5D, T6A, T6C |
| **F6 Campaigns, Gym, Flywheel** | durable campaigns, strategy factory, TradingGym, scorecards, readiness, trajectory export → DPO | F3, F5 | T7B, T7C, T8A–T8D |
| **F7 Paper forward & Risk v2** | PaperForwardRunner, Risk Engine v2, brokers, reconciliation, audit chain | F2, F3 | T9A–T9D |
| **F8 Data platform v2** | streaming ingest, quality, calendars, corporate actions, splits, providers v2 | F0 | T2A–T2D (can run parallel to F3–F5) |
| **F9 Kernel v2** | one engine, order types, instrument rules, margin OFF, checkpoints, parity | F1 | T3A–T3E (parallel to F5–F7 behind `engine: legacy`) |
| **F10 UI & gates** | TradingCenter pages, shared chart components, action matrix, verify script, docs | all | T10A–T10D, T11 |

Parallel A–Z tracks that do not block trading: B (Brain `as_of`), C (chat pipeline
timing), E (evaluation always external), M (trading roles in router), S (settings
sections). Each ships with tests and a `buildplan.md` entry.

Every phase ends with: targeted tests → impacted suites → Skeptic pass where v4 requires
it → docs → state file update → stop.

---

## 5. Decisions requested from the operator

1. **Approve F0 first.** It is a large mechanical diff to `main.py` (split into routers +
   `composition.py`) with zero intended behavior change. Without it, every agent/news
   worker either imports `main.py` (forbidden by architecture tests) or duplicates wiring.
2. **New `AgentDefinitionKind.TRADING`** (recommended) versus tag-only. Kind gives hard
   isolation (G64); tag does not.
3. **News sources for the first iteration:** RSS/Atom only (no keys) — recommended; keyed
   APIs added later via `SecretsBroker`.
4. **LLM agents inside backtests:** allowed only at explicit cadence with a campaign budget,
   always paired with a deterministic replay (recommended), or research-time only.
5. **Trading model roles in the router** (`trading.analyst`, `trading.news`,
   `trading.author`, `trading.critic`) so a smaller local model can serve news extraction
   while the main model authors strategies.

---

## 6. Explicitly NOT claimed

Profitability or expected returns; gym → real transfer; production live execution or any
live venue; L5 autonomy; microstructure realism without L2/L3 data; options/futures/forex
unless separately built and proven; that news sentiment is predictive; tax/legal compliance;
investment advice. `Data/HADES` and `editor/` are not read, imported or depended on.
