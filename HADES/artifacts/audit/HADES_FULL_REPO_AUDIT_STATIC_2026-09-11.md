# HADES Repository Audit — Current Main

**Branch:** `cursor/full-repo-audit-static-871d`  
**Date:** 2026-09-10 / 2026-09-11  
**Method:** Static-first analysis only  
**CLI tests / builds / CI:** **NOT EXECUTED** (explicit user override — GitHub billing)  
**Maximum claim for changed code:** `STATICALLY_HARDENED_AWAITING_LOCAL_VALIDATION`

Baseline prior audit (9–10 Sep 2026): `docs/engineering/REPO_AUDIT_REMEDIATION_REPORT.md` — treated as ALREADY_FIXED unless regression proven.

---

## 1. Executive Summary

Current `main` already contains extensive false-success / plugin honesty hardening. This pass **did not re-implement** those fixes; it verified key ones remain present and hunted **new residual defects**.

| Metric | Count |
|---|---:|
| Confirmed new findings | **16** |
| P0 Critical | **4** (SSRF class — core + plugins) |
| P1 High | **7** |
| P2 Medium | **4** |
| P3 Low / docs | **1** (+ docs drift pack) |
| Fixed statically this branch | **16** |
| Deferred (safe without runtime) | **3** (generator overlay regen risk residual; browser redirect hop DNS rebinding; multi-DB atomic forget) |
| Runtime-unverified (all changes) | **all** — `UNVERIFIED_PENDING_LOCAL_VALIDATION` |
| ALREADY_FIXED (prior audit) reconfirmed | **20+** cross-checks |

**Top risks closed statically:** WebResearch redirect SSRF; news/browser/deep-web private-host SSRF; Gen2 compute lease overwrite; explain-only tool side effects; paper-bot silent re-enable; incomplete workspace backup categories.

**Do not claim production readiness.** No release gate ran.

---

## 2. Repository Coverage

| Subsystem | Reviewed | Findings | Changes | Runtime verification |
|---|---|---|---|---|
| Startup / lifespan / config | Yes (map + lifecycle symbols) | 0 new | Docs only | BLOCKED_BY_NO_CLI |
| Chat / reasoning / understanding | Yes | 1 (explain+high tools) | Fixed | UNVERIFIED_PENDING_LOCAL_VALIDATION |
| LM Studio / streaming | Yes | Docs drift (streaming IS wired) | README fixed | STATIC review only |
| Work Runtime / lifecycle | Yes (ownership cross-check) | 0 new (prior blocked-step OK) | — | ALREADY_FIXED |
| Approvals / policy / trust | Yes | 0 new | — | ALREADY_FIXED |
| Plugin Manager / invoke | Yes | Git import SSRF | Fixed | UNVERIFIED… |
| Plugin dependency runtime | Yes | Secret redaction gaps | Fixed | UNVERIFIED… |
| Plugins (46 + `_shared`) | Yes (inventory + SSRF/honesty hotspots) | News/browser/deep-web/template | Fixed | RUNTIME_UNVERIFIED |
| Research / WebResearch | Yes | Redirect SSRF + robots fail-open | Fixed | UNVERIFIED… |
| Knowledge / Memory / Evidence | Yes | Forget delete honesty | Fixed | UNVERIFIED… |
| Gen2 (Mission/Eval/Compute/…) | Yes | Lease overwrite; A/B meta `pass` | Fixed | UNVERIFIED… |
| Workflows HITL FE | Yes | Success toast on failed resume | Fixed | UNVERIFIED… |
| Persistence / backup | Yes | Incomplete core categories; zip bomb | Fixed | UNVERIFIED… |
| Frontend Classic + Obsidian | Yes (shared pages) | Toasts; TaskStatus blocked; SSE poll | Fixed | UNVERIFIED… |
| Voice / speech | Yes | Delete ignore_errors | Fixed | UNVERIFIED… |
| Trading (PAPER) | Yes | Paper-bot auto-enable | Fixed | UNVERIFIED… |
| Native C++ | Static contracts only | 0 new protocol drift | — | UNVERIFIED_ON_HOST |
| Docs / gates / map | Yes | lint≡typecheck; gap analysis stale | Fixed | N/A |
| Tests (as contracts) | Read + new regressions written | — | ADDED_NOT_EXECUTED | NOT_EXECUTED_BY_USER_CONSTRAINT |
| GitHub Actions | Not triggered | BLOCKED_EXTERNAL | — | BLOCKED_EXTERNAL |

---

## 3. Architecture Map (current ownership)

### Startup
Windows `HADES.bat` / `HADES_LAUNCHER.py` → FastAPI lifespan (`app_lifecycle.py`) → DB migrations (`database.py`, `platform_db.py`) → plugin reconcile → optional native companion → LM Studio discovery (loopback allowed).

### Chat path
FE (`chat-page` / Obsidian wrap) → `hades-api.ts` → `send_message` → settings → `build_request_spec` / `build_route_decision` → retrieval → optional web refresh → model (+ optional `chat_stream` provisional deltas) → plugin shortlist/`PluginManager.invoke` → verification / execution truth → persist → SSE `stream_delta` / run events → FE `useChatRun`.

**Streaming:** production-wired for **text-only provisional** chat (`lm_studio.chat_stream` → `stream_delta` → SSE → UI). Tool rounds remain non-stream. README previously claimed “not implemented” — corrected.

### Work Runtime
Task create → plan/DAG → capability routing → budgets → tools → approvals → checkpoints → `decide_work_task_completion` (**sole Work completion owner**). Mission Control mirrors; Workflows own only workflow-run status.

### Gen2
Mission Control / Compiler / Eval Lab / Context Compiler (opt-in) / Flight Recorder (durable sink) / Committee / Factory / Sandbox / Temporal Graph / Finance Fusion / Compute Fabric — implemented + UI-integrated to varying depth; host axes remain UNVERIFIED_ON_HOST. Gap analysis 2026-09-08 is **historical/superseded**.

### Plugins
package → manifest → trust normalize (legacy → untrusted) → deps → register → eligibility (deterministic) → approve/policy (**block wins**) → `PluginManager.invoke` (manual ≡ autonomous engine) → result honesty → ledger.

### Persistence roles
- **Memory:** durable facts/preferences (`database.py`)
- **Knowledge:** chunked bulk (`platform_db` + KnowledgeService)
- **Evidence:** provenance snapshots  
Sibling stores: embeddings, effect ledger, claims, leases, voice, coding_jobs — now included in workspace backup core categories.

---

## 4. Confirmed Bugs

### HADES-AUDIT-2026-001 — WebResearch redirect SSRF
- **Severity:** P0 | **Confidence:** Confirmed static | **Status:** FIXED_STATICALLY
- **File:** `backend/platform_services_core.py` `WebResearchService._get` / `allowed_by_robots`
- **Problem:** `follow_redirects=True` with only scheme checks; open redirect → private/metadata.
- **Fix:** Shared `backend/url_security.py`; hop-validate; robots fail-closed on errors / private hops.
- **Regression:** `test_audit_full_repo_static_2026.py` — ADDED_NOT_EXECUTED

### HADES-AUDIT-2026-002 — Workspace backup omitted durable stores
- **Severity:** P1 | **Status:** FIXED_STATICALLY
- **File:** `backend/workspace_backup.py`
- **Fix:** Core categories + roots for embeddings, effect_ledger, claims, leases, voice, coding_jobs.

### HADES-AUDIT-2026-003 — Compute fabric lease overwrite
- **Severity:** P1 | **Status:** FIXED_STATICALLY
- **File:** `backend/gen2/compute_fabric.py` `lease_remote_job`
- **Fix:** Refuse unexpired lease held by another node (`lease_held`).

### HADES-AUDIT-2026-004 — Deep-web redirect / inspect SSRF
- **Severity:** P0/P1 | **Status:** FIXED_STATICALLY
- **Files:** `plugins/deep-web-downloader/{deep_utils,deep_engine,crawler}.py`
- **Fix:** Manual redirects + `assert_public_crawl_url`.

### HADES-AUDIT-2026-005 — Eval A/B meta invents `pass: 1.0`
- **Severity:** P2 | **Status:** FIXED_STATICALLY
- **File:** `backend/gen2/eval_lab.py`
- **Fix:** Meta metrics use `experiment_completed` / `not_model_quality` (no quality `pass: 1.0`).

### HADES-AUDIT-2026-006 — Plugin git import private hosts
- **Severity:** P1 | **Status:** FIXED_STATICALLY
- **File:** `PluginManager.import_git`
- **Fix:** `assert_public_http_url(..., purpose="git_import")`.

### HADES-AUDIT-2026-007 — Explain + high/maximum enables tools
- **Severity:** P1 | **Status:** FIXED_STATICALLY
- **File:** `backend/reasoning/understanding.py`
- **Fix:** `speech_act==explain` and not `needs_tools` ⇒ `allow_tools=False`.

### HADES-AUDIT-2026-008 — Paper bot silently re-enables trading
- **Severity:** P1 | **Status:** FIXED_STATICALLY
- **File:** `backend/trading_service.py`
- **Fix:** Raise `paper_trading_disabled` (no auto `set_enabled(True)`).

### HADES-AUDIT-2026-009 — News plugins urllib SSRF
- **Severity:** P0 | **Status:** FIXED_STATICALLY
- **Files:** ultimate-news-feeder (`ssrf.py`, fetch/crawl/_fetch); financial-news-intelligence `fetch_bytes`
- **Fix:** Public URL + hop validation.

### HADES-AUDIT-2026-010 — Browser plugin private navigation
- **Severity:** P0/P1 | **Status:** FIXED_STATICALLY
- **Files:** patchright, puppeteer, scrapling bridges
- **Fix:** Block private/loopback/link-local hosts before goto/fetch.

### HADES-AUDIT-2026-011 — Workflow HITL toast ignores failed resume
- **Severity:** P2 | **Status:** FIXED_STATICALLY
- **File:** `workflows-page.tsx`

### HADES-AUDIT-2026-012 — Dependency secret redaction gaps
- **Severity:** P1 | **Status:** FIXED_STATICALLY
- **File:** `plugin_dependency_runtime.py`
- **Fix:** authToken, Basic auth, URL userinfo, npm `_authToken`.

### HADES-AUDIT-2026-013 — Voice recordings delete false success
- **Severity:** P2 | **Status:** FIXED_STATICALLY
- **Files:** `voice/routes.py`, voice-settings-panel

### HADES-AUDIT-2026-014 — TaskStatus missing `blocked`
- **Severity:** P2 | **Status:** FIXED_STATICALLY
- **Files:** `lib/hades-api.ts`, `tasks-page.tsx`

### HADES-AUDIT-2026-015 — SSE poll not stopped when stream healthy
- **Severity:** P2 | **Status:** FIXED_STATICALLY
- **File:** `useChatRun.ts`

### HADES-AUDIT-2026-016 — Docs drift (lint/streaming/map/gap)
- **Severity:** P3 | **Status:** FIXED_STATICALLY
- **Files:** README, HADES_CODEBASE_MAP, ARCHITECTURE_GAP_ANALYSIS_GEN2 (historical banner)

### Also fixed
- Memory/trading/project-continuity empty success toasts
- Conversation forget reports `not_found` when delete fails
- Workspace zip extract archive size/file ceilings
- SearXNG bridge **template** doctor fail-closed (regen safety)

---

## 5. Security Findings

### Threat model (summary)
| Boundary | Verdict |
|---|---|
| Local API | Trusted-local operator model; not multi-tenant hardened |
| Plugin ZIP / .HadesPlugin | Zip-slip guards present (prior); workspace extract now size-capped |
| Outbound HTTP research/plugins | **Hardened this pass** (hop SSRF); LM Studio loopback intentionally separate |
| Git plugin import | Private hosts blocked |
| Subprocess | No `shell=True` confirmed in backend/plugins |
| LLM as security oracle | Still must not promote trust / invent verification — preserved |
| Dependency logs | Redaction broadened; EXTERNAL_SECURITY_VERIFICATION_REQUIRED for CVE scan |

### Residual security
- Browser plugins: private **literal** hosts blocked; full DNS-rebinding / redirect-hop in Chromium still **SUSPECTED_REQUIRES_RUNTIME_VALIDATION**
- Generator templates for agent-reach/rtk/kotaemon may still drift on regen — partial; searxng template fixed
- No paid CVE database consulted → `EXTERNAL_SECURITY_VERIFICATION_REQUIRED`

---

## 6. Plugin Audit

Inventory: **46** plugins + `_shared` (matches prior inventory). Status vocabulary: no “WORKING” without runtime.

| Plugin | Manifest | Registration | Static execution path | Permissions | Trust | Tests present | Runtime status | Findings |
|---|---|---|---|---|---|---|---|---|
| activepieces | Y | Y | PARTIAL_STATIC | service | legacy→untrusted | Y | RUNTIME_UNVERIFIED | — |
| agent-reach | Y | Y | PARTIAL_STATIC | subprocess | … | Y | RUNTIME_UNVERIFIED | template regen risk |
| agentic-awesome-skills … skill packs (many) | Y | catalog | skill bridge | low | … | N/limited | RUNTIME_UNVERIFIED | ALREADY_FIXED empty exits |
| chrome-devtools-mcp | Y | Y | MCP | mcp | … | N | RUNTIME_UNVERIFIED | ALREADY_FIXED |
| composio | Y | Y | CLI | … | … | N | RUNTIME_UNVERIFIED | ALREADY_FIXED |
| deep-web-downloader | Y | Y | STATICALLY_VERIFIED path | network | … | Y | RUNTIME_UNVERIFIED | **FIXED SSRF** |
| desktop-commander-mcp | Y | Y | MCP | … | … | N | RUNTIME_UNVERIFIED | ALREADY_FIXED |
| dspy / headroom / unsloth / graphrag / rtk | Y | Y | soft-bridge | … | … | N | RUNTIME_UNVERIFIED | ALREADY_FIXED / template risk |
| financial-news-intelligence | Y | Y | STATICALLY_VERIFIED path | network | … | Y | RUNTIME_UNVERIFIED | **FIXED SSRF** |
| fincept-data | Y | Y | PARTIAL_STATIC | network | … | Y | RUNTIME_UNVERIFIED | ALREADY_FIXED empty |
| geolibre | Y | Y | PARTIAL_STATIC | … | … | Y | RUNTIME_UNVERIFIED | ALREADY_FIXED empty FC |
| ghosttrack / sinwindie-osint | Y | Y | PARTIAL_STATIC | network | … | Y | RUNTIME_UNVERIFIED | ALREADY_FIXED |
| gods-eye-view | Y | Y | packaging | … | … | N | RUNTIME_UNVERIFIED | UNVERIFIED_ON_HOST |
| gpt-crawler | Y | Y | PARTIAL_STATIC | … | … | Y | RUNTIME_UNVERIFIED | ALREADY_FIXED doctor |
| kotaemon / moneyprinter-turbo / project-nomad / netstriker-ai / activepieces | Y | Y | service | … | … | Y | RUNTIME_UNVERIFIED | ALREADY_FIXED doctors |
| markitdown / patchright / puppeteer / scrapling | Y | Y | STATIC path | network/subprocess | … | N | RUNTIME_UNVERIFIED | **FIXED private host** (patchright/puppeteer/scrapling) |
| searxng | Y | Y | PARTIAL_STATIC | service | … | Y | RUNTIME_UNVERIFIED | template doctor **FIXED** |
| ultimate-news-feeder | Y | Y | STATIC path | network | … | Y | RUNTIME_UNVERIFIED | **FIXED SSRF** |
| vibe-trading | Y | Y | PARTIAL_STATIC | … | … | N | RUNTIME_UNVERIFIED | ALREADY_FIXED; PAPER only |
| voicestudio | Y | Y | PARTIAL_STATIC | service | … | N | RUNTIME_UNVERIFIED | ALREADY_FIXED empty probes |
| web-pdf-harvester | Y | Y | STATIC path | network | … | Y | RUNTIME_UNVERIFIED | ALREADY_FIXED redirect SSRF |
| humanizer / local-stt-paste / others | Y | Y | PARTIAL_STATIC | … | … | varies | RUNTIME_UNVERIFIED | prior honesty |

---

## 7. Reasoning / Agent Findings

- Explain-only bypass via high/maximum profile **fixed**.
- Prior tool-routing / max_tool_rounds=0 / Humanizer shortlist: **ALREADY_FIXED**.
- No hidden CoT storage introduced.

## 8. Work Runtime / Lifecycle Findings

- Work owns completion; Mission mirrors; Workflows separate — **ALREADY_FIXED**.
- Blocked ≠ completed — **ALREADY_FIXED**.
- Gen2 remote job leases now refuse foreign overwrite — **FIXED**.

## 9. Gen2 Findings

- A/B meta quality score honesty **fixed**.
- Gap analysis marked historical/superseded.
- Compute lease race **fixed**.
- Context Compiler remains opt-in (product decision, not bug).

## 10. Database / Persistence Findings

- Multi-DB layout intentional; backup completeness **improved**.
- Conversation forget delete outcome honesty **improved** (not fully cross-DB transactional — deferred).
- No destructive migration proposed.

## 11. Frontend Findings

- Task `blocked` status typing/labels **fixed**.
- HITL / memory / trading / project / voice toast honesty **fixed**.
- SSE+poll duplication teardown **fixed** (sequence dedupe still partial — deferred polish).
- Classic ≡ Obsidian page sharing confirmed; no redesign.

## 12. Native Runtime Findings

- Protocol v1 alignment appears consistent statically.
- Windows Job Objects / CMake / live binary: **UNVERIFIED_PENDING_LOCAL_VALIDATION**.

## 13. Performance Findings

- No new confirmed P0/P1 perf bugs fixed this pass.
- Unbounded histories remain a residual watch item (prior bounded slices in places).

## 14. Dead Code / Cleanup

| Item | Disposition |
|---|---|
| `coding_candidates.py` tombstone | **retained intentionally** |
| `native_runtime.py` re-export | **retained intentionally** |
| `platform_services.py` wrapper | **retained**; docs corrected |
| Bridge templates | searxng fixed; others **manual review** on regen |

## 15. Dependency Findings

- Static only; no upgrades; no invented CVEs.
- Redaction improved.
- `EXTERNAL_SECURITY_VERIFICATION_REQUIRED` for advisory DB.

## 16. Documentation Drift (corrected)

| Doc | Issue | Action |
|---|---|---|
| README | lint≡typecheck; streaming “not implemented” | Corrected |
| HADES_CODEBASE_MAP | platform_services as megafile | Corrected ownership |
| ARCHITECTURE_GAP_ANALYSIS_GEN2 | Stale as current truth | Historical banner |
| TESTING_RELEASE_GATES | Already correct on lint | Left as source of truth |
| CURRENT_STATUS | Updated this tip | See below |

## 17. Tests Added or Changed

| File | Purpose | Bug ID | Execution |
|---|---|---|---|
| `backend/tests/test_audit_full_repo_static_2026.py` | SSRF helpers, explain tools, paper disabled, leases, backup, A/B metrics, news SSRF, redaction | 001–012 | **NOT_EXECUTED_BY_USER_CONSTRAINT** |
| `backend/tests/test_platform.py` | Paper bot disabled raises | 008 | NOT_EXECUTED… |

## 18. Changes Made

See git commits on `cursor/full-repo-audit-static-871d` (`68928fa`, `fac1e2b`, plus docs snapshot `d0e8a26`). Key new modules: `backend/url_security.py`, `plugins/ultimate-news-feeder/ssrf.py`.

## 19. Remaining Issues

| Issue | Why not fixed broadly |
|---|---|
| Chromium redirect/DNS-rebinding beyond literal host block | Needs runtime browser harness |
| Full cross-DB atomic forget | Needs careful transaction design + runtime |
| Remaining bridge template honesty (agent-reach/rtk/kotaemon) | Partial; searxng done; regen audit deferred |
| Sequence-level SSE/poll event dedupe | Partial fix (stop poll); full dedupe deferred |
| GitHub Actions | BLOCKED_EXTERNAL (billing) |

## 20. Risk Assessment (1–10)

| Axis | Score | Note |
|---|---:|---|
| Reliability | 7 | Honesty improved; unvalidated |
| Security | 7 | SSRF class closed statically; host/browser residual |
| Code Quality | 7 | Targeted fixes |
| Architecture | 8 | Ownership clear |
| Performance | 6 | Not deeply re-measured |
| Testing | 4 | Suites exist but **this pass did not run them** |
| Plugin System | 7 | Inventory complete; runtime unknown |
| Maintainability | 7 | Docs aligned |
| Observability | 7 | Prior correlation IDs retained |
| Production Readiness | **3** | Conservative — no local/CI validation |

## 21. Engineering Quality Gap

Still needed for very high production engineering quality (not model-frontier marketing):

1. Run Deferred Validation Plan to completion on Windows host.
2. Live LM Studio quality MEASURED axes.
3. Browser plugin SSRF harness with redirect fixtures.
4. Paid CI green (when billing restored).
5. Native Job Object operational proof.
6. Remaining template/generator honesty sync.
7. Optional: transactional multi-store forget/backup activation drills.

## 22. Deferred Validation Plan

**DO NOT RUN DURING THIS AUDIT.** Commands listed for later user permission only.

### Phase A — Focused regression tests
```bash
cd backend && python3 -m unittest tests.test_audit_full_repo_static_2026 -v
cd backend && python3 -m unittest tests.test_platform.PlatformTests.test_trading_bot_discovers_strategies_and_builds_knowledge -v
cd backend && python3 -m unittest tests.test_intent_understanding -v
cd backend && python3 -m unittest tests.test_audit_trading_disabled_honesty -v
```
Goal: prove 001–012 / explain / paper-disabled. Evidence: all PASS.

### Phase B — Backend suite
```bash
python3 verify_hades.py --python-only
```
Goal: no regressions vs ~1182 prior tip. Evidence: ran/skipped PASS, exit 0.

### Phase C — Frontend typecheck/lint/tests
```bash
npm run typecheck
npm run lint
npm test
```
Goal: TaskStatus blocked + toast/SSE TS OK; ESLint clean.

### Phase D — Production build
```bash
npm run build
```

### Phase E — Full HADES release gate
```bash
python3 verify_hades.py
# or VERIFY_HADES.bat on Windows
```

### Phase F — Windows host verification
```bat
PREPARE_HADES.bat
VERIFY_HADES_HOST.bat
```
Evidence: Job Objects / native paths.

### Phase G — Live LM Studio
Manual: Models page connected with models>0; chat provisional streaming visible; tool round non-stream.

### Phase H — Browser/plugins/services
Invoke deep-web / news / patchright / puppeteer / scrapling with private URL fixtures expecting `ok=false`; SearXNG doctor without Docker expects fail.

### Phase I — Native C++
```bat
BUILD_HADES_NATIVE.bat
```
+ CTest — UNVERIFIED_ON_HOST until run.

### Phase J — GitHub Actions
Only after billing resolved — **BLOCKED_EXTERNAL** until then. Do not retrigger paid failures.

---

**Final status:** `STATICALLY_HARDENED_AWAITING_LOCAL_VALIDATION`
