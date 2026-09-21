# CURRENT_STATUS.md

## Latest change — Neural V2 associative memory (embeddings + Chat wiring)

Production Neural Memory is associative recall beside Exact Brain — **not** an LLM.
This pass hardens V2 after #181/#183:

- Production encoder (`lm_studio_embedding`) encodes **without requiring torch**
  (`FrozenEmbeddingVector` / `encode_text_list`); toy remains test-only.
- Chat dual retrieval wires Exact from live knowledge/memory context + Neural
  cosine retrieve when `neural_allow` + READ/SHADOW + encoder ready (no injected
  retrieve hooks required). SHADOW scores only; READ injects bounded
  `neural_association` (`trusted=False`).
- Verified-experience ingest: batch API `POST /api/neural/experience-ingest` +
  fail-open post-task hook after Work completion (allow + read|shadow only).
  Failures → negative Slow samples; secrets still rejected.
- `docs/neural/STATUS.md` restored to honest V1 COMPLETE / V2 IN PROGRESS frame
  plus F-06 READ-as-primary refusal.
- Eval artifact remains **UNMEASURED** without an embedding provider.
- Defaults unchanged: `neural_allow=false`, `neural_mode=off`, LEARN disabled.

### Verification actually run (this host)

| Check | Result |
|---|---|
| `python3 -m unittest` neural V2 + OFF/gateway/dual/continual/experience/checkpoint/domain/acceptance/read_f06 | **PASS** 111/111 (25 skipped: torch) |
| `docs/neural/v2_eval.json` | **UNMEASURED** (harness only) |
| Full `verify_hades.py` | **NOT RUN** |

## Previous — Fase 3 complete (T1–T16) + gen2 gate align

Audit remediation **T1–T16** is on branch `cursor/fase1-stabilize-t1-t5-bf8f`
(PR #183). This entry records T16 and the offline Gen2 gate fixture align.

### T16/F-33 (central logging + trace_id)

- `errors/logging_setup.py`: rotating `data_root/logs/hades.log` with
  `trace_id=` on every line.
- `errors/http_errors.py`: per-request correlation middleware; every 5xx JSON
  body includes `trace_id` and is logged under that id (unhandled, HTTPException,
  HadesError). Uses `request.state.trace_id` so BaseHTTPMiddleware task hops
  cannot drop the id.
- Doc drift: MCP scale claim corrected to 500 plugin + **120** MCP tools;
  CODEBASE_MAP clarifies Lux remains coded default, FINALBETA optional.

| Task | Finding | Result |
|---|---|---|
| T16 | F-33 | 5xx → `trace_id` → matching log line |

### Gen2 offline gate (software-only)

- S4 discovery fixtures set `trust=manual` (autonomous eligibility trust ladder).
- ADV43 accepts `UrlSecurityError` wording from `assert_public_http_url`.

| Check | Result |
|---|---|
| `python3 -m evals.gen2_release_gate` | **PASS** (reasoning/red_team/frontier 1.0) |
| `tests.test_central_logging_t16` (+ T12–T15 focused) | **PASS** |
| Ruff boundary (`backend/errors/`, trust/url modules) | **PASS** |
| `npm run typecheck` | **FAIL** — pre-existing FINALBETA TS errors (not introduced by T1–T16) |
| GitHub Actions `release-gates` | **BLOCKED_EXTERNAL** — account billing/spending limit |

### Consciously deferred (unchanged)

- T7 chat schedule+stream for `_execute_work` (cancel/offload done)
- T9 settings-console RPC
- T10 bulk `implemented=None` audit
- T12 live LM Studio holdout run
- Full `unittest discover` / `verify_hades.py` end-to-end on this host (discover
  historically hangs on unrelated API fixtures; CI runners not starting)

## Previous — Fase 3 T15 (citation verification)

- `verify_quoted_citations` / `annotate_uncovered_citations` run on every
  source-using chat answer (knowledge/evidence/memory/tools/attachments), not
  only the critic path.
- Invented quotes that do not appear in evidence texts get an honest
  `[HADES citaatcontrole]` marker; `completed` is demoted to `partial`.

| Task | Finding | Result |
|---|---|---|
| T15 | citation verification | Invented quotes marked uncovered on sourced answers |

### Verification actually run (this host)

| Check | Result |
|---|---|
| `tests.test_citation_verification_t15` | PASS |

## Previous — Fase 3 T14/F-17 (token estimates)

- Domain-aware `token_estimate` replaces blind `chars//4` for NL/code.
- Provider budget overflow is explicit (`context_limit_exceeded_explicit`).

| Task | Finding | Result |
|---|---|---|
| T14 | F-17 | Token deviation under calibration margin for NL/code |

### Verification actually run (this host)

| Check | Result |
|---|---|
| `tests.test_token_estimate_f17_t14` | PASS |

## Previous — Fase 3 T13 (rejecting critic)

- New suite `tests/test_rejecting_critic_t13.py`: critic `passed=False` is refused
  by `verification_allows_success`; `verification_failed` checkpoints cannot
  complete; Work owner persists task `failed` (not `completed`) when verification
  raises after a rejecting critic.

| Task | Finding | Result |
|---|---|---|
| T13 | test theatre / critic | Rejecting critic → task failed |

### Verification actually run (this host)

| Check | Result |
|---|---|
| `tests.test_rejecting_critic_t13` | PASS |

## Previous — Fase 3 T12/S-B (measurable agent quality)


- Fixed task set contract: `evals/fixed_task_set.py` (20–50 holdout tasks,
  deterministic judges only).
- Release thresholds **v2**: `model_answer` and `agent_task` are **required when
  measured**; UNMEASURED still allowed without LM Studio.
- Aggregate metrics now include `tool_success_ratio`, `task_completion`,
  `model_calls`, `latency_ms`.

| Task | Finding | Result |
|---|---|---|
| T12 | S-B | Measured agent quality can fail the gate; offline stays honest |

### Verification actually run (this host)

| Check | Result |
|---|---|
| `tests.test_fixed_task_set_t12` | PASS |
| `tests.test_agent_eval_a01` | PASS |

### Consciously deferred (T12 slice)

- Live LM Studio run of the full holdout set (no model in this environment).

## Previous — Fase 2 T11/F-11+F-13+F-18+F-19 (trust boundaries)


- **F-11:** `LocalApiTrustMiddleware` gates all methods on TCP peer loopback;
  non-loopback bind refused unless `HADES_ALLOW_NON_LOOPBACK_BIND=1`; launcher
  sets `HADES_BIND_HOST=127.0.0.1`; voice WS rejects untrusted peers.
- **F-13:** Web research redirect hops use `allow_loopback=False` (initial URL
  may still be loopback).
- **F-18:** Native and text tool-result modes both wrap with untrusted marker.
- **F-19:** `DELETE /api/memories/{id}` calls `embedding_index.mark_deleted`.

| Task | Finding | Result |
|---|---|---|
| T11 | F-11+F-13+F-18+F-19 | Peer trust, no redirect SSRF, tool demarcation, embed invalidate |

### Verification actually run (this host)

| Check | Result |
|---|---|
| `tests.test_trust_boundaries_f11_f13_f18_f19` | PASS |
| `tests.test_local_api_origin_security` | PASS (lifespan mocked for CI) |

## Previous — Fase 2 T10/F-10-structural (settings implemented flag)

- `SettingDefinition.implemented`: `True` (enforced), `False` (stored only),
  `None` (not yet audited).
- Confirmed F-04 dead keys labeled `implemented=False` (autonomy policies,
  delegation timeout, tool timeout, verification/critic passes, memory read,
  research.prefer_local).
- Network allow/deny/redirect + logging.retention claim `implemented=True` with
  entries in `control/consumers.py`.
- Control Center hides unimplemented by default and badges them when shown.
- Registry test fails if `implemented=True` lacks a consumer.

| Task | Finding | Result |
|---|---|---|
| T10 | F-10-structural | Catalog cannot claim enforcement without a consumer |

### Verification actually run (this host)

| Check | Result |
|---|---|
| `tests.test_settings_implemented_f10_structural` | PASS |

### Consciously deferred (T10 slice)

- Bulk audit of remaining ~330 settings (`implemented=None`); mark True only when
  a consumer is registered.

## Previous — Fase 2 T9/F-21+F-10+F-22 (routes + real actions)


- Single FINALBETA hash schema `#/fb/<page>`; Lux hashes redirect explicitly.
- Unmounted `MissionControlPage` / `SystemPage` removed from exports.
- Settings `pageId`/`initialTab` scroll to real sections.
- Workflows create-from-template wired; knowledge inspector actions call APIs
  or honest “not connected” toasts (no toast-only theater on those controls).
- Performance tabs have content branches + `tabpanel` semantics.

| Task | Finding | Result |
|---|---|---|
| T9 | F-21+F-10+F-22 | One route table; live create/actions; real perf tabs |

### Verification actually run (this host)

| Check | Result |
|---|---|
| `tests/finalbeta-routes-actions-f21-f10-f22.test.mjs` | PASS |

### Consciously deferred (T9 slice)

- Settings-console “Uitvoeren” remains non-API (no durable console RPC).
- `mission-control-page.tsx` / `system-page.tsx` files kept on disk but unexported.

## Previous — Fase 2 T8/F-14+F-15 (atomic knowledge + retention)


- `upsert_knowledge_with_chunks` writes source+chunks in one transaction
  (`pending` → `ready` only with chunks).
- Retention job prunes messages/task_events/research_events/agent_usage/tool_calls
  when `log_retention_days` / `logging.retention_days` is set; runs at startup.
- `idx_research_events_project` added.

| Task | Finding | Result |
|---|---|---|
| T8 | F-14+F-15 | Atomic ingest; retention job + research_events index |

### Verification actually run (this host)

| Check | Result |
|---|---|
| `tests.test_knowledge_retention_f14_f15` | PASS |

## Previous — Fase 2 T7/F-05+F-16 (cancel + offload)

- `TaskRunner.cancel` fences + schedules `cancel_lm_run(task_id)` (Work uses
  `run_id=task_id`); HTTP cancel awaits it.
- Sync specialist handlers and Gen2 mission start run via `asyncio.to_thread`.
- Step-start SQLite writes offloaded; Work queue is bounded.

| Task | Finding | Result |
|---|---|---|
| T7 | F-05+F-16 | Cancel stops LM; blocking work off the loop |

### Verification actually run (this host)

| Check | Result |
|---|---|
| `tests.test_work_cancel_offload_f05_f16` | PASS |

### Consciously deferred (T7 slice)

- Full chat-request `schedule + stream` for `_execute_work` (needs budget plumbing
  on the scheduled path).
- Dedicated p95 `/health/live` load test during a live work step.

## Previous — Fase 2 T6/F-03 (per-kind approvals)

Per-capability approval flags (`approved_subprocess`, `approved_network`, …) are
enforced at the PluginManager boundary. `approved_by_user` is audit-only for
side-effect `ask` policies. HTTP/MCP/broker pass flags through; durable
`ApprovalService` decisions grant the kinds required by the tool contract.

| Task | Finding | Result |
|---|---|---|
| T6 | F-03 | One authorization layer at PM; per call-path tests |

### Verification actually run (this host)

| Check | Result |
|---|---|
| `tests.test_capability_approvals_f03` | PASS |

## Previous — Fase 1 stabilize (T1–T5)

Audit remediation on branch `cursor/fase1-stabilize-t1-t5-bf8f`:

| Task | Finding | Result |
|---|---|---|
| T1 | F-01 | Missions schedule Work Runtime; status `dispatched` until task runs |
| T2 | F-02 | `tool_orchestrator` invoke falls through (no canned args / forged approval) |
| T3 | F-08+F-09 | FINALBETA shell live health; shared settings event constant |
| T4 | F-04 | Domain allow/deny + redirect_limit enforced in URL security / web research |
| T5 | F-06+F-07 | Neural READ refused as primary; honest `docs/neural/STATUS.md` |

### Verification actually run (this host)

| Check | Result |
|---|---|
| `tests.test_mission_dispatch_f01` | PASS |
| `tests.test_tool_orchestrator_f02` (+ related agent e2e/routing) | PASS |
| `tests/finalbeta-shell-health-f08-f09.test.mjs` | PASS |
| `tests.test_network_domain_policy_f04` | PASS |
| `tests.test_neural_read_f06` + gateway/acceptance/real_integration READ cases | PASS |

## Previous — Neural V2: production encoder + Chat dual retrieval

Associative Neural Memory (not an LLM) moves off the toy hash encoder for
production:

- Production encoder = frozen LM Studio embeddings (`neural.encoder`);
  `encoder=toy` remains test-only.
- Checkpoint schema_version **2**; legacy dim=32 toy checkpoints fail closed.
- Chat dual retrieval wires Exact + Neural when `neural_allow` + READ/SHADOW;
  SHADOW scores without injecting `neural_association` items.
- Verified failures → negative Slow samples; secrets still rejected.
- Eval artifact `docs/neural/v2_eval.json` is **UNMEASURED** (no embedding
  provider on this host). **Not COMPLETE.**
- Defaults unchanged: `neural_allow=false`, `neural_mode=off`, LEARN disabled.
- **Update (T5/F-06):** READ is also refused as ModelGateway primary until real
  LM fusion exists; API labels it `research_only`.


### Verification actually run (this host)

| Check | Result |
|---|---|
| `python3 -m unittest` neural V2 + OFF/gateway/dual/continual/experience/checkpoint/domain/acceptance suites | **PASS** 119/119 |
| `docs/neural/v2_eval.json` | **UNMEASURED** (harness only) |
| Full `verify_hades.py` | **NOT RUN** |

## Previous — Control-plane delta Wave 1+2

Starting SHA: `5808f201203f480d8ba8fc2d6996b8e9148a624f` (`origin/main`).
Ending SHA: `1224228adb6f5293baf0c783df2168f7e8e43209` (branch tip).

### Wave 1 — Protect the execution spine

- Actionable NL for PDF/document conversion, attachment read/save, file edit, and
  download→Knowledge no longer collapses to `direct_chat` with `max_tool_rounds=0`.
  Explicit “gebruik geen tools” still zeros the tool plane. Trivial chat (`Wat is 2+2?`)
  remains schema-free.
- Plugin **service start** fails closed for `isolation=container` and `isolation=secured`
  (no silent `subprocess.Popen` host fallback).

Prior #179/#180 honesty invariants remain (approval_id, linked Work, working_state
persist flags, one-shot container/secured/native-required).

### Wave 2 — Connect surfaces to the same truth

- Chat stamps `research_blocked_network` when research intent meets blocked network
  (local answer allowed; not represented as fresh research).
- Empty product workflow IR fails with `empty_workflow` (not default `completed`).
  Sandbox empty IR remains refused at validate (also not completed).
- Classic/Lux `chat-page.tsx` reconciles live tools/events by `call_id` /
  sequence via shared `mergeChatToolCalls` / `mergeLiveExecutionEvents`.

### Verification actually run (this host)

| Check | Result |
|---|---|
| Wave 1 gate (`test_chat_budget_tool_routing` + honesty + core tools + intent + tool kernel + frontier isolation + plugin bugfixes + mcp hardening) | **PASS** 124/124 |
| Wave 2 (`tests.test_control_plane_wave2_honesty`) | **PASS** 5/5 |
| Combined with `test_audit_a06_workflows` | **PASS** 62/62 |
| `node --test tests/live-execution-merge.test.mjs` | **UNVERIFIED_ON_HOST** (no `node_modules`/vite) |
| Live LM Studio | **UNMEASURED** |
| Full `verify_hades.py` | Not claimed |

### Residual risks / next action

- Core first-party tools still lack EffectLedger `effect_applied` (plugin path has it).
- Work still uses a separate context clip vs Chat `assemble_chat_context_messages`.
- Pre-existing on main: `test_chat_plugin_invoke_timeout.test_run_model_invoke_does_not_hardcode_120`.
- Wave 3 (memory/retrieval/critic/trading PAPER static polish) not fully executed this run.

## Previous — Honesty, authorization & execution-truth hardening

Trust-boundary repair (not a rewrite):

- Linked Work in conversation `open_work` is owned by Work Runtime + verified
  checkpoint (`resolve_linked_work_truth`); chat completion cannot invent completion.
- Working-state persistence failures set `working_state_persist_failed` and a
    human-readable note — no silent success claim.
- MCP/workflow `approved_by_user` / `preapproved` are audit-only; authorization
  requires a scoped persisted `ApprovalService` `approval_id`.
- Native `enabled` mode fails closed on executor failure (`native_executor_failed`);
  `isolation=container` refuses host execution (`container_not_implemented`);
  secured remains fail-closed.
- Supplemental isolation truth: requested vs effective isolation stamped for all
  tiers; `restricted_env`/`plugin_cwd` never claim FS sandbox; native `auto`
  fallback is observable (`native_fallback`, executor_requested/effective).

### Verification actually run (this host)

| Check | Result |
|---|---|
| `python3 -m unittest tests.test_honesty_authorization_execution_truth tests.test_frontier_plugin_isolation tests.test_plugin_runtime_bugfixes.PluginRuntimeBugfixTests -v` | **PASS** 46/46 |
| `python3 -m unittest tests.test_honesty_authorization_execution_truth tests.test_mcp_host_hardening_regressions tests.test_mcp_host_management tests.test_frontier_plugin_isolation tests.test_audit_a12_lifecycle tests.test_plugin_runtime_bugfixes.PluginRuntimeBugfixTests` | **PASS** 80/80 |
| `python3 -m unittest tests.test_audit_a06_workflows` | **PASS** 10/10 (prior turn) |
| Full `verify_hades.py` / entire backend suite | Not claimed green here — focused suites only |

## Previous — FINALBETA live tool / event execution truth

FINALBETA Chat no longer appends every `tool_status` update as a new tool row.
`useHadesChatRuntime` (sole FINALBETA consumer via `useChatLive`) reconciles by
`call_id` and dedupes live events by backend `sequence` before applying the
existing 30 / 40 presentation caps. Classic/Lux `chat-page.tsx` now uses the same
`mergeChatToolCalls` / `mergeLiveExecutionEvents` helpers (Wave 2 of control-plane delta).

### Verification actually run (this host)

| Check | Result |
|---|---|
| `node --test tests/live-execution-merge.test.mjs tests/finalbeta-chat-live.test.mjs` | **PASS** 11/11 |

## Previous — Tool Kernel + Capability Broker

Chat no longer injects plugin/MCP tool schemas into the model-visible payload.
Stable first-party `hades.*` tools (≤ 12) remain; dynamic extras go through
`hades.capabilities.search|inspect|invoke` (`capability_intel.broker`).

Branch: `cursor/tool-kernel-capability-broker-2826` @ `ad20203`
PR: https://github.com/syneyexx/HADES/pull/177
Baseline `origin/main`: `9b6bd68`

See `docs/architecture/HADES_TOOL_KERNEL_AND_CAPABILITY_BROKER.md`.

### Verification actually run (this host)

| Check | Result |
|---|---|
| `python3 -m unittest tests.test_tool_kernel_capability_broker` | **PASS** 24/24 |
| Related: chat_core_tools, budget routing, reasoning, capability_*, one_brain, settings drift | **PASS** 63/63 |
| Scale proof: 500 plugin + 120 MCP tools indexed → model-visible ≤ 12 | **PASS** (10–11) |
| `npm run typecheck` / `npm run lint` | Pre-existing FINALBETA TS/lint failures on main (#176); not introduced by this PR |
| Full `verify_hades.py --python-only` | Not completed here (unittest discover hung on unrelated API fixture); CI subscribed |

## Previous — FINALBETA Media/Trading subpage live wiring

Media viral/calendar/analytics and Trading marketdata/portfolio now use shared
live hooks. Broker page is an honest opt-in gate (no fake balances).
llm-stats and performance were already live.

Remaining: media-channels pixel page, trading-simulation stub, model-training,
settings stubs.

### Verification actually run (this host)

| Check | Result |
|---|---|
| `node --test tests/finalbeta-live-wiring-contracts.test.mjs` | **PASS** 21/21 |

## Previous — Coding Agent A–Z model runtime / cancellation hardening

Production hardening of the complete Coding model-call lifecycle: request →
Task ownership → timeout/cancel → HTTP unwind → cleanup → honest job status.

### Root causes addressed
- `_invoke_chat_fn` stranded ThreadPoolExecutor workers after timeout (`stranded_best_effort_cancel`)
- Investigate selector called async `chat_fn` without awaiting (coroutine leak → heuristic fallback)
- OmniRoute `_default_complete` used blocking `urllib` (uncancellable during read)
- Job cancel fenced status but did not cancel the active asyncio model Task
- LM Studio `_RUN_CLIENTS` lacked detach / lock; cross-loop `aclose` risk
- Cancel-before-register race could still start a provider call
- Timeout/cancel could be blurred into malformed structured output

### Architecture after
- `coding_model_runtime.py`: single broker loop + active-call registry keyed by
  `job_id` / ephemeral sync run id; timeout and cancel cancel the real Task on
  the owner loop and await unwind
- All Coding `chat_fn` paths (propose/repair/report/investigate/OmniRoute) use it
- OmniRoute completions use `httpx.AsyncClient`
- `/build/jobs/{id}/cancel` fences + cancels active model Tasks before/with job cancel

### Verification actually run (this host)

| Check | Result |
|---|---|
| `pytest backend/tests/test_coding_model_runtime_a_to_z.py` | **PASS** 16/16 |
| Coding suite (omniroute, a_to_z_repair, jobs, lm_studio, investigate, …) | **PASS** 126+27 |

## Previous — FINALBETA Performance + Brain/Evidence/Files/Research live wiring

Performance page now uses `useDashboardLive` (CPU/RAM/GPU/health). Disk/network charts stay honestly empty until APIs exist.

### Also in this pass — Brain / Evidence / Files / Research

FINALBETA Onderzoek & Kennis pages now use shared live hooks instead of mock
runtime data:

| Page | Hook | Backend |
|---|---|---|
| Brain | `useHadesBrain` | `/brain`, `/brain/layout` |
| Evidence | `useHadesEvidence` | `/claims`, `/knowledge/pack` |
| Files | `useHadesFiles` | `/files` |
| Research | `useHadesResearch` | `/research` |

Hardcoded Brain `CLUSTERS` removed. Empty/loading/error states are honest.
Claim confidence is withheld when no observable signals exist.

### Verification actually run (this host)

| Check | Result |
|---|---|
| `node --test` brain + live-wiring + files + research + evidence | **PASS** 15/15 |

## Previous — FINALBETA Files live wiring

FINALBETA Bestanden (`#/fb/files`) now reads live `/files` data via
`useHadesFiles` (workspaces, indexed files, knowledge stats). Fake folder tree,
storage TB totals, and `mockFileRows` are out of the production page path.
Empty / loading / error states are honest; upload, refresh/rescan, and index
delete are wired.

### Verification actually run (this host)

| Check | Result |
|---|---|
| `node --test tests/finalbeta-files-page.test.mjs` (+ Files contract in live-wiring) | **PASS** |

## Previous — Coding Agent A-to-Z repair (no-op elimination)

Production repair of the natural-language Coding path so FINALBETA Coding can
reliably turn a goal into isolated worktree edits, verification, and explicit apply.

### Root causes addressed
- UI selected model was not passed into `buildFromGoal` / `buildFromGoalAsync`
- Fragile `json.loads` discarded fenced/prose JSON as empty edits
- Investigation language misclassified mutation goals as report-only
- Missing CSS/config discovery suffixes; alphabetical 400-file ceiling
- Green baseline with zero edits could still look verified
- Async review model path stringified coroutines
- Default verification was Python unittest; no Coding preflight

### Layers touched
- Shared Coding runtime + FINALBETA Coding UI (model_id, preflight, failure banners)
- Backend: structured-output parser, intent, source policy, model resolve, verification auto-select, job terminals, delivery honesty

### Verification actually run (this host)

| Check | Result |
|---|---|
| `python3 -m unittest tests.test_coding_agent_a_to_z_repair` | **PASS** |
| `python3 -m unittest tests.test_coding_job_recovery_model_autonomy` | **PASS** |
| `python3 -m unittest tests.test_coding_agent_goal tests.test_coding_job_unknown_terminal_status_honesty` | **PASS** |
| `node --test tests/coding-a-to-z-repair.test.mjs` | **PASS** 6/6 |

## Previous — FINALBETA Taken + Model Training submenu pixel lock

Pixel-locked FINALBETA submenu tabs for **Taken** (Lijst, Mijn taken, Kalender,
Tijdlijn) and **Model Training** (Datasets, Model, Framework, Runs) to the
supplied mockup layouts. Analytics on Taken stays a light placeholder; Kanban
and Training Overzicht remain available.

### Taken
- Tab panels: `finalbeta/pages/tasks/{tab-lijst,tab-mijn-taken,tab-kalender,tab-tijdlijn}.tsx`
- Extended mocks: list project helpers, mijn summary/chips, calendar deadlines,
  Gantt timeline groups (`mocks/tasks.ts`)
- Styles: `styles/finalbeta/v2/tasks.css`

### Model Training
- Interactive tabs via `FinalBetaShell` (removed from plain `pageRenderers`)
- Tab panels: `finalbeta/pages/model-training/{tab-overzicht,tab-datasets,tab-model,tab-framework,tab-runs}.tsx`
- Mocks: `mocks/model-training.ts`
- Styles: `styles/finalbeta/v2/model-training.css`

### Verification actually run (this host)

| Check | Result |
|---|---|
| `npm run typecheck` | **PASS** |
| `node --test tests/finalbeta-tasks-page.test.mjs tests/finalbeta-model-training-page.test.mjs` | **PASS** 4/4 |

## Previous — FINALBETA pixel-lock: Instellingen, Research, Knowledge, Evidence, Bestanden, Geheugen

Six FINALBETA pages are pixel-locked to the supplied high-fidelity mockups
(1672×941 references under `docs/mockups/_ref/`):

| Page | Route | Reference |
|---|---|---|
| Instellingen | `#/fb/settings-general` | `instellingen.png` |
| Research | `#/fb/research` | `research.png` |
| Knowledge Library | `#/fb/knowledge` | `knowledge.png` |
| Evidence Vault | `#/fb/evidence` | `evidence.png` |
| Bestanden | `#/fb/files` | `bestanden.png` |
| Geheugen | `#/fb/memory` | `geheugen.png` (ref refresh; existing page) |

- Presentation: `finalbeta/pages/{finalbeta-settings,research,knowledge,evidence,files,memory}-page.tsx`
- Styles: `styles/finalbeta/v2/{settings,research,knowledge,evidence,files,memory}.css`
- Mocks: `finalbeta/mocks/{settings,research,knowledge,evidence,files,memory}.ts`
- Lux ↔ FINALBETA switch preserved on Instellingen
- Visual-first mock content (FINALBETA Phase 1)

### Verification actually run (this host)

| Check | Result |
|---|---|
| `npx tsc --noEmit` | **PASS** |
| `node --test` page contracts (settings/files/evidence/knowledge/research/memory + interface) | **PASS** 12/12 |

## Previous — FINALBETA Plugin & Runtime pixel-lock

Pixel-locked Plugin & Runtime pages against the user mockup JPGs under
`docs/mockups/_ref/` (FinalBetaShell + `mc-*` chrome + per-page `pr-*.css`):

- Performance (`#/fb/performance`) ← `performance.jpg` + `pr-performance.*`
- Plugins (`#/fb/tools`) ← `plugins.jpg` + `pr-plugins.*`
- MCP (`#/fb/mcp`) ← `mcp.jpg` + `pr-mcp.*`
- Workflows (`#/fb/workflows`) ← `workflows.jpg` + `pr-workflows.*`
- Console (`#/fb/settings-console`) ← `console.jpg` + `pr-console.*`

Mock/prototype UI only (Dutch copy + demo data matching the references).

### Verification actually run (this host)

| Check | Result |
|---|---|
| `npm run typecheck` | **PASS** |
| `node --test tests/finalbeta-plugin-runtime-pages.test.mjs` | **PASS** |

## Previous — Chat per-run budget isolation + direct-chat tool routing

Fixed false “Toolrondes uitgeput” / “runbudget is uitgeput” on trivial Chat turns
and the follow-on failure where a later turn in the same conversation inherited an
exhausted execution budget.

- **Run identity:** `should_restore_execution_budget` restores consumed counters
  only when `resume_run_id == client_request_id` (both non-empty). Prior
  `partial` / `blocked` / `running` status alone no longer poisons a new turn.
- **Direct chat:** simple conversational answers (`direct_answer` / low-risk
  chat-question without tool need) no longer receive tool schemas; Normal/fast
  budgets are not burned by irrelevant tool loops.
- **Tool autonomy preserved** for actionable routes (tool_use, research,
  analysis/debug, workspace actions such as “Lees bestand …”).
- Contract docs: `docs/PLUGIN_RUNTIME_CONTRACT.md` updated to match.

### Verification actually run (this host)

| Check | Result |
|---|---|
| `python3 -m unittest` focused routing/budget/modes/intent batch (75 tests) | **PASS** |
| `python3 -m ruff check` on changed backend files | **PASS** |
| Live LM Studio / end-to-end Chat with a real model | **NOT RUN** — no live model endpoint on this host |
| Full `verify_hades.py --python-only` | **NOT RUN** — orchestration suite can hang without LM Studio; focused gates used instead |

## Previous — FINALBETA Coding complete runtime takeover

FINALBETA Coding is now the canonical live Coding UI over a shared HADES coding
runtime (same migration pattern as FINALBETA Chat).

- Shared pure helpers: `features/coding/coding-runtime-core.ts`
- Shared controller: `features/coding/hooks/useHadesCodingRuntime.ts`
- FINALBETA presentation: `finalbeta/pages/coding-page.tsx` + `finalbeta/pages/coding/*`
- Thin alias: `finalbeta/hooks/use-coding-live.ts`
- Lux Coding Agent page thinned to a compact shared-runtime shell + link to FINALBETA
- Deep links: `#/coding-agent?codingJob=` → `#/fb/coding?codingJob=` under FINALBETA
- CodingCard / Chat Advanced → `#/fb/coding?codingJob=`
- Honest unavailable: Git branch mutation, GitHub PRs, remote deploy (no backends)
- Deploy tab = release confidence + smoke only
- Instellingen = Control Plane Coding keys (no fake `.hades/coding.json`)
- Parity matrix: `docs/architecture/finalbeta-coding-parity-matrix.md`

### Verification actually run (this host)

| Check | Result |
|---|---|
| `npm run typecheck` | **PASS** |
| `npm run lint` | **PASS** |
| `node --test tests/coding-runtime-core.test.mjs tests/coding-runtime-parity.test.mjs tests/finalbeta-coding-live.test.mjs tests/finalbeta-coding-page.test.mjs tests/coding-agent-helpers.test.mjs` | **PASS** 9/9 |

## Previous — FINALBETA Chat complete runtime parity

FINALBETA Chat is now a live presentation over a shared HADES chat runtime
controller (`useHadesChatRuntime`), not a thin send/stream shell.

- Shared pure helpers: `features/chat/chat-runtime-core.ts`
- Shared controller: `features/chat/hooks/useHadesChatRuntime.ts`
- FINALBETA presentation: `finalbeta/pages/chat-page.tsx` (design preserved)
- Thin alias: `finalbeta/hooks/use-chat-live.ts` → re-exports shared runtime
- Lux Chat uses shared `resolveConversationModelId` for model isolation
- Critical fixes: draft `attachment_ids` retention, model cross-conversation
  isolation, Unified Stop (work/coding/research), stream/conversation race
- Runtime cards: approvals, work/coding/research, verification, tools,
  provenance, pins, branches, canvas, voice, telemetry, doctor, handoffs

### Verification actually run (this host)

| Check | Result |
|---|---|
| `npm run typecheck` | **PASS** |
| `npm run lint` | **PASS** |
| `npm run build` | **PASS** |
| `node --test tests/chat-runtime-core.test.mjs tests/finalbeta-chat-live.test.mjs` | **PASS** 13/13 |

## Previous — FINALBETA Coding tabs pixel panels

Wired all Coding submenu tabs to dedicated mockup panels (superseded by live
runtime takeover above).

Mock/prototype UI only — no Coding OmniRoute wiring (historical).
