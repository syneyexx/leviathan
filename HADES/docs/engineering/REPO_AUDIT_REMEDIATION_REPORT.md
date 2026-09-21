# HADES repository audit — engineering report

Branch: `cursor/repo-audit-hardening-943b`  
Date: 2026-09-09  
Host: Linux cloud agent (Windows Job Objects / live LM Studio: **UNVERIFIED_ON_HOST**)

## Executive Summary

Systematic audit of HADES found multiple **false-success** defects on `main` (14 failing baseline tests). This branch remediates the highest-impact ones: chat tool routing, Work Runtime blocked-step honesty, PDF harvester resume/empty downloads + download redirect SSRF, coding delivery demotion, shared plugin-bridge empty-result exits, and cross-plugin CLI/MCP exit honesty (ghosttrack, searxng, agent-reach, rtk, …). Focused regressions pass; full release gate and Windows/live-provider axes remain host-gated.

## Baseline

| Gate | Result |
|---|---|
| `python verify_hades.py --python-only` (pre-fix) | **FAILED** — 1060 tests, 11 failures, 3 errors, 12 skipped |
| Evidence | `artifacts/audit/BASELINE_SUMMARY.md` |

Primary baseline failure classes: tool routing (`max_tool_rounds=0`), Work verification checklist fixtures lagging #59, Humanizer shortlist, Gen2 contract drift, investigate delivery demotion.

## Repository Areas Audited

Frontend, FastAPI backend, Work Runtime / agents, Gen2, research/knowledge, persistence, PluginManager, 46 plugins (+ `_shared`), native runtime (docs/contracts only), CI/verify scripts, release docs.

## Critical Bugs Fixed

### 1. Chat “Gebruik plugin” disabled tools (P0)
- **Files:** `backend/reasoning/understanding.py`
- **Symptom:** Multi-tool / autonomous plugin chats returned empty `tools[]` and “Toolrondes uitgeput (0)”.
- **Root cause:** #59 tightened markers to `gebruik de plugin` only; Dutch `Gebruik multi-echo` classified as `question` → `allow_tools=False`.
- **Fix:** Broader execute markers + multi-step tool wording; preserve “geen tools” / explain paths.
- **Regression:** `tests.test_intent_understanding.ExplainVsExecuteTests.test_gebruik_named_plugin_is_tool_use`
- **Verification:** API multi-tool + Humanizer e2e PASS

### 2. Policy-blocked Work steps marked completed (P0)
- **Files:** `backend/main.py`, `backend/run_lifecycle.py`
- **Symptom:** `mode=blocked` steps stored as `status=completed` with `error=blocked`; completion gate ignored blocked.
- **Root cause:** Intentional comment treated blocks as terminal-but-completed; gate only checked failed/pending.
- **Fix:** Persist `blocked`; early-return; completion rejects `blocked_steps`.
- **Regression:** `tests.test_audit_a12_lifecycle.test_blocked_steps_block_completion`

### 3. Coding investigate demoted after green tests (P0)
- **Files:** `backend/coding_delivery.py`
- **Symptom:** Investigate repaired + tests passed → status `incomplete` / `demoted_incomplete`.
- **Root cause:** `not []` treated empty `uncertainties` as missing required field.
- **Fix:** Empty uncertainties list is valid; only `None` is missing.
- **Regression:** `tests.test_coding_delivery_empty_uncertainties` + milestone1 investigate/hard benchmark PASS

## High Priority Bugs Fixed

### Tool orchestrator “registry.” false miss
- `work_intents.extract_plugin_name_hint` matched `plugin registry.`; stopwords + quoted names; invoke via shortlist when registry miss but eligible tools exist; denied tools return `eligible_tools: []`.

### Web PDF Harvester silent resume / empty download success
- Default `resume=false`; empty-queue resume → `success=false`; zero progress resume → fail; empty index download → `no_work` fail; strengthened tests.

### Gen2 mission gate resume swallow
- Resume exceptions surface as `resume_ok=false` / `resume_error` instead of silent `pass`.

### Gen2 FE contract drift
- `gen2EvalHumanRating` → `HumanUsabilityRatingInput` mapping.

### Plugin empty-result / exit honesty
- `_shared/skill_bridge` + `catalog_bridge` (synced to plugin copies)
- `scrapling`, `markitdown`, `puppeteer`, `deep-web-downloader` (empty crawl exit 2; robots fail-closed except 404/410)
- ghosttrack / sinwindie all-probe network failure; searxng dead engines; agent-reach/rtk/graphrag nested exit; MCP wrapper `isError`; composio/vibe-trading/dspy/headroom/patchright

### PDF download redirect SSRF (P0)
- Downloader used `follow_redirects=True` after only validating the seed URL; open redirects could reach private/loopback. Now hop-validates like crawl `HttpClient`.

### Plugin HTTP healthcheck redirect SSRF (P1)
- Loopback healthchecks followed redirects off-host. Redirects now refused.

### Mission budget consume swallow (P1)
- Tool steps could complete after `consume_mission_budget` failed. Now fail the step with `budget_consume_failed:…`.

### Research adapter false `passed` on DB persist failure (P1)
- Local fixture pack set in-memory `completed` then swallowed `update_research_project` errors. Persist failure now sets `status=failed` so `passed` cannot be true without durable write.

### Effect ledger finalize silence (P1)
- Finalize exceptions are logged; fallback `mark_unknown` attempted so restart classification is not left blank.

### Research crawl / auto web-refresh empty honesty (P1)
- `crawl_site` no longer silently returns `[]` when every page fetch fails (raises; PDF-only seeds still empty for ingest fallback).
- `maybe_refresh_web_knowledge` returns `ok`/`error` instead of `{attempted:true, indexed:0}` on total failure.

### Frontend false-success toasts (P1)
- Voice setup awaits settings save before success toast; spoken-answers toggle reverts on save failure.
- Knowledge search and Memory history errors are no longer presented as empty success.

## Medium/Low Priority Improvements

- Stale docs claiming `lint ≡ typecheck` corrected.
- Agent e2e / Fake LM critics emit full `criteria_checklist` from verification prompts (test honesty after #59).
- `agent_runtimes` no longer swallows plugin list DB errors as `[]`.

## Plugin Audit Results

| Plugin / area | Verdict | Notes |
|---|---|---|
| web-pdf-harvester | **FIXED** | Resume/download honesty; redirect-hop SSRF; 23/23 tests |
| deep-web-downloader | **FIXED** | Empty crawl + robots fail-closed |
| scrapling / markitdown / puppeteer | **FIXED** | Exit/empty content |
| patchright | **FIXED** | Empty fetch/screenshot exit honesty |
| skill/catalog `_shared` (+ copies) | **FIXED** | Empty list/get honesty |
| ghosttrack | **FIXED** | All-probe network failure → `ok:false` + nonzero exit |
| sinwindie-osint | **FIXED** | Same all-probe failure class |
| searxng | **FIXED** | Empty + unresponsive engines → exit 2; connection errors → exit 1 |
| agent-reach / rtk / graphrag | **FIXED** | Nested CLI `exit_code` propagated to process exit |
| chrome-devtools-mcp / desktop-commander-mcp | **FIXED** | `isError`/`error` → nonzero exit; fail-closed `doctor` requires node+npx |
| patchright / scrapling / markitdown | **FIXED** | Doctor exit follows `cli_bridge.doctor` ok (was always 0) |
| vibe-trading | **FIXED** | Doctor no longer echoes unresolved CLI fallbacks; exit 2 when module/CLI missing; empty research stdout → exit 2 |
| puppeteer | **FIXED** | Doctor emits `ok` + exit 2 when puppeteer not importable |
| composio list_toolkits | **FIXED** | Empty CLI toolkit list → ok:false (doctor already fail-closed) |
| composio / vibe-trading / dspy / headroom | **FIXED** | CLI/MCP/empty-result honesty; shared `cli_bridge.doctor` now sets `ok`/`exit 2` when required modules missing |
| scrapling / dspy / unsloth / graphrag / headroom | **FIXED** | Soft-bridge empty/false-success exits + honesty tests |
| Shared MCP `call_tool` empty payload | **FIXED** | Empty content/structuredContent → isError + nonzero exit |
| Sinwindie filtered-empty lists / empty doctor catalogs | **FIXED** | `ok=false` + exit 2 |
| Financial/ultimate news feed ingest | **FIXED** | Require ingest evidence before ok=true |
| Deep-web crawl partial errors | **FIXED** | Seed failure or error flood → ok=false |
| PluginManager start after process exit | **FIXED** | Dead post-health process → failed/unhealthy |
| Patchright/Scrapling HTTP ≥400 | **FIXED** | ok=false (Puppeteer parity) |
| Fincept catalog/batch honesty | **FIXED** | Empty query matches / child failures → ok=false |
| MoneyPrinter/Kotaemon soft doctors | **FIXED** | Require ffmpeg / gradio, not layout-only |
| PluginManager empty stdout | **FIXED** | Exit 0 + empty stdout → failed (`empty command stdout`) |
| Approvals decide resume | **FIXED** | Resume failures surface as `resume_ok=false` / `resume_error` |
| Coding delivery persist | **FIXED** | `delivery_artifact` phase only after successful write; persist fail demotes |
| PluginManager structured stdout | **FIXED** | Top-level / nested `ok:false` forces failed invocation |
| preview `run_user_flow` | **FIXED** | Requires open + all actionable steps |
| control config import | **FIXED** | Bad overrides raise validation error (no silent skip) |
| agent-reach doctor | **FIXED** | Module-level `ok:false` → nonzero process exit |
| ghosttrack track_phone | **FIXED** | Invalid numbers → `ok:false` + nonzero exit |
| rtk gain | **FIXED** | Empty stdout → `ok:false` |
| puppeteer screenshot | **FIXED** | HTTP ≥400 → `ok:false` (parity with fetch) |
| Shared `cli_bridge.doctor` | **FIXED** | Missing modules / all-binaries-absent → `ok:false` + exit 2 (was always exit 0) |
| Inventory of 46 plugins | **PARTIAL** | Static inventory in `artifacts/audit/PLUGIN_INVENTORY.md`; many skill/catalog packages share bridges |
| gpt-crawler | **FIXED** | Stub `start` / missing package no longer doctor-green (exit 2) |
| project-nomad / activepieces | **FIXED** | Doctor fails closed when compose layout missing |
| netstriker-ai | **FIXED** | Doctor `ok` tied to backend layout; missing layout → exit 2 |
| kotaemon / moneyprinter-turbo | **FIXED** | Doctor green only when required layout present |
| financial-news-intelligence / ultimate-news-feeder / fincept-data | **FIXED** | Empty fetch / missing API key → nonzero exit |
| voicestudio | **PARTIAL** | Doctor reports `ok` + explicit `ready_to_start` (Docker); live audio **UNVERIFIED_ON_HOST** |
| gods-eye-view | **UNVERIFIED_ON_HOST** | Packaging only (no runtime bridge on host) |

## Web/Crawler Findings

See Critical/High PDF harvester + deep-web sections. Remaining: Playwright browser fallback quality **UNVERIFIED_ON_HOST**; live multi-site harvest **BLOCKED_EXTERNAL** without network allowlist targets.

## Runtime / Agent Findings

Blocked-step honesty + plugin hint extraction + intent routing fixed. Capability routing from #65 retained.

## Persistence Findings

No A/B SQLite path bug proven. Multi-DB layout (`hades.db`, embeddings, claims, effect ledger) documented as intentional split — backup/restore remains a residual risk.

## Frontend Findings

No UI redesign. Network-policy / Obsidian preset issues were already fixed on `main` (#61/#62). Lint≡typecheck docs were stale.

## Security Findings

- Deep-web robots fail-open → fail-closed (except missing robots).
- **PDF harvester download path SSRF:** auto-follow redirects could land on private/loopback after a public seed. Now mirrors crawl `HttpClient` hop validation (`follow_redirects=False` + `safe_normalize` per hop). Regression: `DownloadRedirectSsrfTests`.
- **Plugin HTTP healthcheck redirects disabled** so loopback healthchecks cannot open-redirect to metadata/private hosts. Regression: `test_http_healthcheck_does_not_follow_redirects`.
- No permission widening.

## Dead / Obsolete Code Removed

- Removed unused `run_argv` helper from `plugins/_shared/cli_bridge.py` and 16 packaged copies after repo-wide proof of **zero call sites** (only `doctor` / `module_status` / `which_many` remain used).

## Refactors Performed

Minimal; `generate_batch2` now loads agent-reach/searxng/rtk bridges from `_shared/bridge_templates/` so regenerating cannot silently revert honesty fixes.

## Tests Added

- Intent `Gebruik <plugin>` routing
- A12 blocked-step completion gate
- Coding delivery empty uncertainties
- Harvester resume no-op + empty download + download redirect SSRF
- Ghosttrack / sinwindie all-probe failure
- SearXNG dead-engine / genuine-empty / connection-error
- Agent-reach nested exit propagation
- PluginManager HTTP healthcheck redirect refusal

## Tests Modified

- Fake/Specialist LM critics now emit per-criterion checklists (align with #59 verification integrity — not assertion weakening).

## Verification Results

| Suite | Status |
|---|---|
| Focused intent/A12/API/agent e2e/work-plan/Humanizer | **PASS** |
| Milestone1 investigate + hard benchmark | **PASS** |
| Harvester plugin suite | **PASS** (23) |
| Ghosttrack / searxng / agent-reach / sinwindie bridge suites | **PASS** |
| `python verify_hades.py --python-only` (post fail-closed + plugin doctor batch) | **PASS** — 1069 OK, 12 skipped |
| `python3 verify_hades.py --python-only` (post ok=false / preview / control / plugin honesty) | **PASS** — **1083 ran / 10 skipped** |
| `python3 verify_hades.py --python-only` (post empty-stdout / resume / delivery honesty) | **PASS** — **1087 ran / 10 skipped** |
| Empty stdout + approval resume + delivery persist honesty | **PASS** (focused) |
| Policy settings fail-closed + schedule dispatch honesty | **PASS** (focused) |
| Plugin doctor honesty (kotaemon/moneyprinter/gpt-crawler/nomad/activepieces/netstriker/fincept/financial-news) | **PASS** (focused) |
| PluginManager `ok:false` + preview flow + control import override honesty | **PASS** (focused) |
| agent-reach / ghosttrack / rtk / puppeteer honesty regressions | **PASS** (focused) |
| Frontend typecheck (`tsc --noEmit`) after UI honesty | **PASS** |
| Focused crawl_site honesty | **PASS** |
| Frontend typecheck + ESLint + build + node tests (earlier) | **PASS** (55 node tests) |
| `verify_hades.py --quick` native CMake | **UNVERIFIED_ON_HOST** — missing `libstdc++` linker on this image |
| Windows Job Objects / live LM / browser | **UNVERIFIED_ON_HOST** |
| GitHub Actions `quick-gates` / `release-gates` | **BLOCKED_EXTERNAL** — tip `bf44950` run `34435020177`: empty `steps: []` / no runner (same on recent `main`) |

## Performance / Reliability Improvements

Fewer silent no-ops in crawl/resume; fewer false tool-budget zeros; mission budget consume failures no longer mark steps completed.

## Files Changed

See PR diff: backend reasoning/runtime/delivery/PluginManager/Gen2 adapters, plugin bridges + harvester downloader, docs status/audit hygiene, bridge templates.

## Compatibility Assessment

- API contracts preserved; Gen2 mapping added.
- Harvester default `resume` changed **false** (safer; callers can still pass `true`).
- Skill/catalog empty-list now exit 2 — PluginManager will treat as failure (intended honesty).
- OSINT username all-network-failure now fails (HTTP 404-only empty finds still succeed).

## Remaining Risks

- Not every plugin executed end-to-end via PluginManager on this host.
- Some skill packages legitimately empty until git/LFS content is present — exit 2 may mark them not Ready until packed.
- Investigate/coding still has broader autonomy edge cases.
- Silent `except: pass` density in `main.py` / Gen2 remains only partially addressed (budget consume, research persist, ledger finalize remediated).
- Mission↔task sync swallows and envelope-gate attach failures still need careful follow-up.

## UNVERIFIED_ON_HOST Items

Windows Job Objects/AppContainer, live LM Studio inference quality, Playwright browser escalation, VoiceStudio physical audio, native C++ binary integration.

## BLOCKED_EXTERNAL Items

### GitHub Actions (release-gates / quick-gates) — not a code regression
Reconfirmed on tip **`bf44950`** (and parents `e499845` / `d9e026d`) and on recent `main` (#61–#65):

- Jobs complete in ~2–7s with **empty `steps: []`**, **empty `runner_name`**, and **no logs**.
- Tip example: run `34435020177` (push `bf44950`) — `quick-gates` ubuntu+windows fail with `steps=0` / `runner_name=""`.
- Same signature on `main` (e.g. run `34406051963` for #65).

**Classification:** `BLOCKED_EXTERNAL` (Actions minutes/billing or org runner assignment). Local `python3 verify_hades.py --python-only` on this tip remains **PASS** (**1182 ran / 10 skipped**). Re-run GH gates after minutes are restored; do not treat these red checks as evidence of a product code failure.

### Other
Live third-party crawl targets behind bot protection.

## Audit closure (2026-09-10)

| Class | Verdict |
|---|---|
| **VERIFIED** | Inventory of 46 plugins (`artifacts/audit/PLUGIN_INVENTORY.md`); baseline fail → remediate → `python3 verify_hades.py --python-only` **1182/10 PASS**; focused honesty regressions for P0/P1 false-success sinks listed in FIXED table below |
| **UNVERIFIED_ON_HOST** | Windows Job Objects/AppContainer; live LM Studio quality; native CMake/`libstdc++`; Playwright live browser; VoiceStudio physical audio; gods-eye-view runtime |
| **BLOCKED_EXTERNAL** | GitHub Actions quick/release gates (`steps=[]` / no runner on tip + `main`); live bot-protected crawl targets |

High-value false-success sinks on this tip are largely exhausted. Residual polish (not claimed fixed): Gen2 `run_ab_experiment` always records `ab_summary.passed=True` / `pass=1.0` as a meta “experiment completed” score (stats in summary remain honest; not aggregated as model quality). Host-gated axes and GH Actions remain as classified above.

## Recommended Follow-up

1. Restore GitHub Actions minutes / runner assignment; re-run quick + release gates on this tip.
2. PluginManager integration smoke for harvester/scrapling/markitdown/ghosttrack/searxng on a Windows host.
3. Host with `libstdc++` for native CMake release gate; live LM / Playwright / Job Objects verification.
4. Optional: demote Gen2 A/B meta-score `pass: 1.0` inventing if consumers start aggregating it as quality.

### Silent false-success sinks (mission / harvest / research / adapters / FE)

- Chat Work Runtime + TaskRunner terminal mission sync: `_sync_mission_from_task_safe` logs `mission_sync_failed` (geen bare `pass`).
- `/harvest`: `harvest_succeeded()` — `ok` alleen bij ingest of crawl zonder failures.
- Research LLM-synthese failure: status `needs_more_evidence`, metrics `synthesis=fallback_no_llm`, warning event (geen success “afgerond”).
- Gen2 coding/research adapters: artifact persist exception → `passed=False` + `artifact_persist_failed`.
- FE: tasks approvals/inbox/events, chat transcript/canvas, plugins observability — preserve last-good + error surface.

Regressions: `backend/tests/test_audit_silent_sinks_honesty.py`.

### Plugin/FE/control honesty follow-up

- SearXNG + VoiceStudio doctors require Docker (and SearXNG compose); exit non-zero when not ready.
- NetStriker: `ok = layout_ok and modules_ok` (root + overlay).
- `_shared` skill/catalog bridges: empty search → `ok:false`, exit 2; overlays synced from shared.
- `DELETE /api/conversations/{id}`: knowledge-forget failure → HTTP 500 (not silent 204).
- Control Center settings mutations return `side_effects` honesty metadata.
- Chat branch load: preserve last-good + surface `branchesError`.

Regressions: `plugins/*/tests/test_doctor_honesty.py`, `backend/tests/test_shared_bridge_search_honesty.py`, `backend/tests/test_delete_conversation_forget_honesty.py`.


| `python3 verify_hades.py --python-only` (post preview/voice/news + dead-code) | **PASS** — **1094 ran / 10 skipped** |
| `python3 verify_hades.py --python-only` (post approval/web-ingest/GeoLibre + dead-code) | **PASS** — **1099 ran / 10 skipped** |
| `python3 verify_hades.py --python-only` (post ingest-verification honesty + FE toast gates) | **PASS** — **1115 ran / 10 skipped** |
| `python3 verify_hades.py --python-only` (post empty-success honesty: mission/voice/geo/IP/seed) | **PASS** — **1124 ran / 10 skipped** |
| `python3 verify_hades.py --python-only` (post empty ingest/speech/geo/MCP/install) | **PASS** — **1134 ran / 10 skipped** |
| `python3 verify_hades.py --python-only` (post LM/FE/Piper empty-success) | **PASS** — **1142 ran / 10 skipped** |
| `python3 verify_hades.py --python-only` (post flight ingest + MC toast honesty) | **PASS** — **1145 ran / 10 skipped** |
| `python3 verify_hades.py --python-only` (post coding/HITL/PR-help/speak-response honesty) | **PASS** — **1152 ran / 10 skipped** |
| `python3 verify_hades.py --python-only` (post restore/compare/fuse/pack toast honesty) | **PASS** — **1158 ran / 10 skipped** |
| `python3 verify_hades.py --python-only` (post MC empty toasts + agent-reach install) | **PASS** — **1161 ran / 10 skipped** |
| `python3 verify_hades.py --python-only` (post empty chunk/as-of/trends/JIT/metrics) | **PASS** — **1166 ran / 10 skipped** |
| `python3 verify_hades.py --python-only` (post backup/sandbox/catalog/resume/reindex) | **PASS** — **1172 ran / 10 skipped** |
| `python3 verify_hades.py --python-only` (post job/plugin/mic/tasks/queue/netstriker) | **PASS** — **1178 ran / 10 skipped** |
| `python3 verify_hades.py --python-only` (post repair/marketplace/export/bench/logs) | **PASS** — **1182 ran / 10 skipped** |
| Repair/marketplace/export/bench/logs honesty | **PASS** (focused, 4) |
| Job/plugin/mic/tasks/queue/netstriker honesty | **PASS** (focused, 6) |
| Backup/sandbox/catalog/resume/reindex/skill honesty | **PASS** (focused, 6) |
| Empty chunk / as-of / trends / JIT / metrics / graphrag honesty | **PASS** (focused, 5) |
| MC empty toasts / flaky ok / agent-reach install honesty | **PASS** (focused, 3) |
| Restore/compare/fuse/pack toast honesty | **PASS** (focused, 6) |
| Coding/HITL/PR-help/speak-response toast honesty | **PASS** (focused, 7) |
| Flight ingest / Mission Control toast honesty | **PASS** (focused, 3) |
| LM empty-models / FE toast / Piper empty-artifact honesty | **PASS** (focused, 8) |
| Empty ingest/speech/geo/MCP/install honesty | **PASS** (focused, 10) |
| Ingest verification honesty (file/web/scout/builder/FE) | **PASS** (focused, 6) |
| Discovery/harvest/PDF/trading verification honesty | **PASS** (focused) |
| Empty-success honesty (mission sync / VoiceStudio / GhostTrack / GeoLibre / MoneyPrinter) | **PASS** (focused, 9) |
| Preview assert_visible/console/capability honesty | **PASS** (focused) |
| Voice install doctor-ready gate | **PASS** (focused) |
| Dead-code removal usage-proof regressions | **PASS** (focused) |
| Web-refresh unverified ingest / batch approval resume / research folder events / GeoLibre empty query | **PASS** (focused) |

| Preview assert_visible / console / capabilities | **FIXED** | No screenshot greenwash; console unavailable; tools-gated caps |
| Voice install vs doctor | **FIXED** | ok requires doctor.ready |
| Chat auto web-refresh empty discovery | **FIXED** | no_urls → ok=false |
| Chat auto web-refresh unverified ingest | **FIXED** | verification_failed does not increment indexed |
| Plugin approvals batch resume | **FIXED** | resumes task + surfaces resume_ok/resume_error |
| Tasks FE approval toast | **FIXED** | checks resume_ok before success toast |
| Research folder ingest events | **FIXED** | ready=0 / partial fail → warning (not unconditional success) |
| GeoLibre filtered empty query | **FIXED** | ok=false + exit 2 |
| Mission sync safe wrapper inventing ok=true | **FIXED** | None/refused → ok=false; callers require ok is True |
| VoiceStudio empty voices/engines probe | **FIXED** | HTTP 200 empty → ok=false |
| GhostTrack empty show_ip | **FIXED** | whitespace body → ok=false + exit 1 |
| GeoLibre empty FeatureCollection inspect/analyze/load | **FIXED** | ok=false; load skips write |
| MoneyPrinter blank LM Studio seed | **FIXED** | model/base_url required + read-back verify |
| Empty knowledge ingest (0 chunks) | **FIXED** | blank/0 chunks → verification_failed |
| VoiceStudio empty TTS/STT body | **FIXED** | empty audio raises; empty transcript ok=false |
| GhostTrack empty track_ip geo | **FIXED** | empty_geolocation → ok=false |
| MCP expand zero remote tools | **FIXED** | ok=false + HTTP 400; FE error toast |
| Scrapling/Patchright install_browsers | **FIXED** | explicit ok from exit_code |
| LM Studio empty models connected/ok | **FIXED** | 0 models → not connected / connected_empty warn |
| Mission skill execute failure toast | **FIXED** | toast.error on passed=false |
| Files add/rescan ready=0 success toast | **FIXED** | ready<=0 no longer green success |
| Native restart disconnected success toast | **FIXED** | toast.error when disconnected |
| Piper empty voice artifacts ok=true | **FIXED** | empty onnx/json → ok=false |
| Flight ingest missing/empty events | **FIXED** | ok=false + error=no_events |
| Mission Control flight/replay/selftest/eval toasts | **FIXED** | gated on ok/PASS/failed |
| ingest_file ready+empty chunks short-circuit | **FIXED** | falls through to re-ingest/verify |
| Coding Agent job/build-run green toast on failure | **FIXED** | success only for verified/completed |
| Build apply empty files as applied | **FIXED** | noop + applied=false + no_files_applied |
| PR-help toast ignores ok=false | **FIXED** | toast gated on result.ok |
| Workflow HITL reject green toast | **FIXED** | reject/failed → toast.error |
| Voice speak-response ok with 0 segments | **FIXED** | ok=false unless already_spoken skip |
| Build restore empty files as restored | **FIXED** | noop + restored=false + no_files_restored |
| Flight compare/audit empty runs | **FIXED** | ok=false; FE toasts gated |
| Flight timeline 0 events success toast | **FIXED** | message toast when empty |
| Finance fuse empty ok missing | **FIXED** | ok=false + error=no_articles_to_fuse |
| Knowledge pack import 0/0 success | **FIXED** | reject empty pack; gate imported total |
| Compute ping invents status ok | **FIXED** | no default "ok"; known statuses only |
| Agents cancel no-op green toast | **FIXED** | toast.message when nothing cancelled |
| Mission Control empty matrix/reports/etc toasts | **FIXED** | toast.message when counts are 0 |
| Flaky detect with 0 eval runs | **FIXED** | ok=false + error=no_eval_runs |
| agent-reach install_check empty stdout | **FIXED** | ok=false + exit 2 (root+overlay) |
| document_chunk empty text ok=true | **FIXED** | ok=false + empty_document_text |
| As-of beliefs count=0 success | **FIXED** | ok=false + FE message toast |
| Trends/JIT/metrics empty green toasts | **FIXED** | toast.message when samples/grants/runs=0 |
| GraphRAG init/index empty stdout ok | **FIXED** | empty stdout fails for all cmds |
| Workspace backup cancelled/empty path success | **FIXED** | phase+path gated; API 409/500 |
| Sandbox apply unknown plugin | **FIXED** | unknown_plugin rejected; FE envelope gate |
| Eval catalog empty green toast | **FIXED** | usable suites required |
| Coding resume any-status success | **FIXED** | success only queued/running/paused/interrupted |
| Files reindex 0 chunks success | **FIXED** | ready+0 chunks → error (unless unchanged message) |
| Workflow→skill missing id success | **FIXED** | require skill id |
| Coding background job empty/failed start toast | **FIXED** | require job_id; gate attach status |
| Plugin convert/import/update error status success | **FIXED** | error statuses → toast.error |
| Mic test success without level | **FIXED** | require peak > 0.01 |
| Tasks create "gestart" from form only | **FIXED** | toast from item.status |
| process_local_queue always ok=true | **FIXED** | ok=false when jobs failed |
| NetStriker remediation empty ok exit 0 | **FIXED** | ok field + exit 2 when empty |
| Plugin repair/marketplace/build non-ready success | **FIXED** | error/message toasts for non-ready |
| Knowledge pack export 0/0 success | **FIXED** | message when total items = 0 |
| Native bench available without timings | **FIXED** | require numeric echo ms |
| Plugin service logs empty completed | **FIXED** | failed + empty_service_logs |
| Financial-news audit / deep-web inspect | **FIXED** | zero items / HTTP errors fail closed |
| Kotaemon overlay doctor | **FIXED** | synced to require gradio |
| Unused helpers (7 + 5) | **REMOVED** | Call-site proof + regression test |
