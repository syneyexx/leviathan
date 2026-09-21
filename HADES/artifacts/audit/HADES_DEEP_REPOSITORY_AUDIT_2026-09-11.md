# HADES Deep Repository Audit — 2026-09-11

Status of this artifact: **CURRENT FOR PR #84 / NOT A GREEN RELEASE CERTIFICATE**.

## Repository state

- Repository: `syneyexx/HADES`
- Audited baseline branch: `main`
- Exact baseline SHA: `852577b0c42ab29fcd426df10d4437464d6fe0b4`
- Baseline commit date: `2026-09-11T19:07:34Z`
- Baseline commit: `Merge pull request #83 from syneyexx/fix/deep-repo-audit-20260911`
- Implementation branch: `fix/release-integrity-audit-20260911`
- PR: #84 (draft)
- Main was not modified.
- Exact current branch head: use the live PR/Git ref; this audit remains active and subsequent evidence commits advance the head.

Audit host/tooling observed outside a repository checkout:
- Debian GNU/Linux 13 (trixie)
- Python 3.13.5
- Node.js 22.16.0
- npm 10.9.2
- CMake 3.31.6
- Git 2.47.3

Repository/CI contract:
- `package-lock.json` is present; npm remains the package manager.
- workflow pins Node 22.13 and Python 3.12.
- no unrelated dependency upgrade or lockfile regeneration was performed.

## Truth vocabulary

- `IMPLEMENTED`: code exists on the audit branch.
- `VERIFIED`: the applicable deterministic validation actually executed successfully.
- `UNVERIFIED_BY_REPO_SUITE`: implementation exists but repository-defined gates did not execute.
- `VERIFIED_BY_STATIC_CODE`: implementation/property was inspected in code, not demonstrated live.
- `REGRESSION_PRESENT`: a targeted regression test exists; this does not imply it has executed.
- `BLOCKED_EXTERNAL`: external account/infrastructure/permission prevents the requested property from being established or tested.
- `DEFERRED`: deliberately not changed without enough regression/risk evidence.

## Executive summary

Confirmed release-integrity problems were addressed before frontier-architecture work. Material changes on the audit branch now include:

1. One canonical frontend release-test inventory used by both `npm test` and `verify_hades.py`.
2. A regression test preventing silent frontend release-test drift.
3. GitHub Actions least-privilege permissions and immutable action revisions matching the prior tags.
4. A stable `release-gates-required` aggregate check for future branch protection.
5. A fail-closed full-workspace backup invariant: a requested missing primary HADES DB can no longer be reported as a completed archive.
6. Worker-thread event fan-out now returns to the subscriber's owning asyncio loop rather than mutating `asyncio.Queue` cross-thread.

The branch is deliberately **not release green**. GitHub Actions still fails before runner allocation, `main` remains unprotected, the Python release dependency graph is not reproducibly locked, the newly changed backup/event paths have not executed through the current repository suite, and a VoiceStudio async/sync boundary defect remains open.

## Findings

| ID | Severity | Confidence | Location | Root cause / impact | Fix / test | Status |
|---|---|---|---|---|---|---|
| HADES-RG-001 | P1 High | CONFIRMED | `package.json`, `verify_hades.py` | Two hand-maintained frontend release inventories had drifted; required regressions could silently miss one release path. | Added `tools/run_frontend_release_tests.mjs`; both release entrypoints invoke it; added `tests/release-gate-inventory.test.mjs`. | IMPLEMENTED / UNVERIFIED_BY_REPO_SUITE |
| HADES-CI-001 | P1 High | CONFIRMED | `.github/workflows/release-gates.yml` | Mutable third-party action tags and no explicit workflow token permissions weakened release-chain integrity. | Exact existing tag targets pinned by immutable SHA; `permissions: contents: read`. | IMPLEMENTED / UNVERIFIED_BY_REPO_SUITE |
| HADES-CI-002 | P1 High | CONFIRMED | GitHub release workflow / repository settings | Matrix check names are unsuitable as a long-term admin contract and `main` has no required checks. | Added stable `release-gates-required`; GitHub now emits that exact context. | IMPLEMENTED IN WORKFLOW / BRANCH PROTECTION BLOCKED_EXTERNAL |
| HADES-CI-003 | P1 High | CONFIRMED | GitHub Actions runs | Release runs terminate before runner allocation. Jobs show no runner and no executed steps. | No software PASS/FAIL inference made from absent execution. | BLOCKED_EXTERNAL |
| HADES-DEP-001 | P1 High | CONFIRMED | `backend/requirements.txt` | `ruff`, `keyring`, `jsonschema` use `>=`; transitive graph is not locked while release documentation implied pinned requirements. | No guessed freeze was introduced. Reproducible cross-platform resolver/lock generation still required. | UNRESOLVED |
| HADES-BACKUP-001 | P1 High | CONFIRMED | `backend/workspace_backup.py::inventory/create_archive` | Missing requested primary DB was skipped during inventory and could lead to a false `completed` full-workspace backup. | Primary DB is a mandatory category; missing mandatory sources fail before ZIP creation; semantic regression present. | IMPLEMENTED / REGRESSION_PRESENT / UNVERIFIED_BY_REPO_SUITE |
| HADES-EVENT-001 | P2 Medium | HIGH | `backend/reasoning/events.py::RunEventBus.emit_sync` | Worker-thread path directly mutated event-loop-owned `asyncio.Queue`. | Subscriber loop ownership is retained and cross-thread fan-out uses `call_soon_threadsafe`; real worker-thread regression present. | IMPLEMENTED / REGRESSION_PRESENT / UNVERIFIED_BY_REPO_SUITE |
| HADES-VOICE-001 | P2 Medium | CONFIRMED | `backend/voice/providers/voicestudio_tts.py`, async voice callsites | Sync VoiceStudio methods use `asyncio.run()` and are called directly from async paths, causing un-awaited-coroutine warnings/degraded probes when a loop is already running. | Targeted async-boundary fix still required; broad threading refactor intentionally avoided. | UNRESOLVED |
| HADES-BP-001 | P1 High | CONFIRMED | GitHub `main` | `main` reports `protected: false`, no required status checks. Rulesets endpoint requires plan capability and classic protection endpoint is unavailable to this app's permissions. | Admin must enable PR requirement, stale-approval handling, force-push/deletion restrictions and require `release-gates-required`. | BLOCKED_EXTERNAL |

## HADES-RG-001 — canonical frontend release inventory

### Root cause

Two separate manually maintained lists defined what counted as required frontend release coverage. A test could be added to one gate but silently omitted from the other.

### Implemented fix

`tools/run_frontend_release_tests.mjs` is the canonical top-level frontend release test runner and discovers every `tests/*.test.mjs` file deterministically. `npm test` and the Python release verifier both delegate to that runner. `tests/release-gate-inventory.test.mjs` guards against reintroducing a second hard-coded inventory.

### Validation

Code/diff reviewed. Hosted repository gates have not executed because GitHub has not allocated a runner. No PASS is claimed.

## HADES-CI-001 / HADES-CI-002 — release workflow hardening

Implemented:

- workflow-level `contents: read`
- third-party actions pinned to immutable commits corresponding to the pre-existing tags rather than upgrading behavior during hardening
- stable aggregate job `release-gates-required`
- aggregate job depends on both mandatory quick and release matrices

Pinned action revisions:

- checkout: `11d5960a326750d5838078e36cf38b85af677262`
- setup-node: `49933ea5288caeca8642d1e84afbd3f7d6820020`
- setup-python: `a26af69be951a213d495a4c3e4e4022e16d87065`
- upload-artifact: `ea165f8d65b6e75b540449e92b4886f43607fa02`

GitHub subsequently created all expected contexts including `release-gates-required`, proving the context name exists. Current jobs still terminate before runner allocation and execute no repository steps.

## HADES-BACKUP-001 — full workspace backup truthfulness

### Reproduction/root cause

`WorkspaceBackupService.inventory()` skipped non-existent category roots. If `database` was requested but `self.db_path` did not exist, no database entry was produced. `create_archive()` therefore saw no `missing_at_pack` entry and could reach `phase="completed"` with an archive that did not contain the primary HADES database.

### Safest fix implemented

Only the primary database is unconditional mandatory state for a full workspace archive; other feature-owned categories may legitimately not exist on a given installation.

- `MANDATORY_CATEGORIES = {"database"}`
- inventory explicitly records missing requested mandatory sources
- archive creation fails before hashing/ZIP creation when `missing_required` is non-empty
- existing exception handling returns `phase="failed"`; no archive path is claimed
- existing `completed_with_warnings` semantics for files disappearing/changing during packing remain intact

Regression: `backend/tests/test_workspace_backup_invariants.py` requires a missing requested primary DB never to produce `completed` or `completed_with_warnings` and requires no archive path.

Validation: diff reviewed. Repository suite did not execute because no GitHub runner was allocated. Status is not `VERIFIED` yet.

## HADES-EVENT-001 — worker-thread event fan-out

### Reproduction/root cause

`RunEventBus.emit_sync()` is explicitly used by worker-thread paths but wrote directly to `asyncio.Queue`. In an isolated asyncio debug-loop reproduction this raises `RuntimeError: Non-thread-safe operation invoked on an event loop other than the current one`. The pre-existing event regression only called `emit_sync()` from the loop thread and therefore did not exercise the actual boundary.

### Safest fix implemented

- each subscriber stores its queue and owning event loop
- same-loop fan-out stays direct
- worker-thread fan-out uses `owner_loop.call_soon_threadsafe(...)`
- closed-loop races fail soft
- queue-full resync signaling is executed on the owning loop
- existing `event_id`, per-run `sequence`, history and reconnect semantics are retained

A first patch draft attempted to pass a keyword callback argument through `call_soon_threadsafe`; immediate API/diff review caught that before any green or merge claim, and the current branch uses positional callback arguments.

Regression: `backend/tests/test_events_and_voice_p0.py` now creates an actual pending async subscriber and calls `emit_sync()` through `asyncio.to_thread()` with asyncio debug mode enabled.

Validation: implementation and diff reviewed. Repository suite did not execute because no runner was allocated.

## HADES-DEP-001 — Python dependency determinism

Current open ranges include:

- `ruff>=0.11.0`
- `keyring>=25.0.0`
- `jsonschema>=4.22.0`

The last known successful release workflow predates the MCP/keyring/jsonschema additions. It gives historical resolver evidence for the older runtime graph but cannot prove compatible exact versions for the new dependencies. PR #73, which introduced MCP/keyring, explicitly recorded that CI/host keyring validation was not executed; its workflow also failed before runner allocation.

This audit therefore deliberately does **not** choose arbitrary exact versions merely to make the file appear pinned. A reproducible cross-platform resolver/lock strategy remains required before this finding can be closed.

## HADES-VOICE-001 — VoiceStudio async/sync boundary

A historical successful Windows release log emitted `RuntimeWarning: coroutine 'VoiceStudioTts.availability.<locals>._probe' was never awaited`. Current code still explains it:

- synchronous `VoiceStudioTts.availability()` creates `_probe()` and calls `asyncio.run(...)`
- synchronous `list_voices()` and `synthesize()` use the same bridge pattern
- `run_voice_specialist()` calls synchronous `doctor()` from async `try_run_agent_step()`
- async voice status/doctor/voices routes also call synchronous probe/list methods directly

Creating the coroutine before `asyncio.run()` discovers an already-running loop can leave it un-awaited, while the provider can be reported degraded because of call context rather than actual service health.

This is confirmed but not yet modified. Moving every synchronous specialist runtime into a worker thread would broaden the concurrency contract for DB/plugin code without proof; the preferred fix remains a targeted voice async-boundary change.

## Security and correctness re-verification

### URL / SSRF boundary

`backend/url_security.py` currently enforces http/https, rejects URL credentials, applies hostname/DNS checks, and rejects resolved non-global addresses including local/internal destinations. No weakening was introduced. Live-browser proof was not available in this run.

### MCP / OAuth boundary

`backend/mcp_host/manager.py` remains a deliberately thin hardened layer over `manager_core.py`, introduced by PR #83 as change-risk containment. Disposition: `KEEP_INTENTIONAL`.

### Conversation forget

PR #83's atomic forget hardening remains present. Shared production SQLite performs derived retrieval-state cleanup at the primary deletion boundary, and the regression suite injects cleanup failure to require rollback. Status: `VERIFIED_BY_STATIC_CODE + REGRESSION_PRESENT`; current runtime suite did not execute.

### Work Runtime completion truth

The inspected completion paths require verification evidence and pass through the central task-completion decision owner. No simple current false-green bypass was found in those paths. This is static/read-path evidence, not exhaustive proof of every entry path.

## Astra-6 architecture assessment

HADES already contains meaningful foundations and should evolve them rather than create parallel frameworks:

- typed `RequestSpec`
- `Plan` / `PlanStep` DAG
- `VerificationResult` and deterministic completion gating
- `CapabilityDescriptor` / `CapabilityRegistry`
- typed runtime/tool contracts with side-effect/idempotency/timeout/cancellation metadata
- Mission Budget
- Context Compiler
- Flight Recorder
- backend-owned execution truth
- centralized typed failure taxonomy

Recommended integrated sequence after release blockers are resolved:

1. extend RequestSpec/execution policy into an enforceable Intent Contract
2. expand semantic invariants as mandatory deterministic release tests
3. enrich the existing capability descriptors rather than create a second registry
4. add cumulative trust/risk spending alongside Mission Budget
5. extend Flight Recorder metadata/replay without recording secrets
6. enrich Context Compiler and memory provenance/contradiction metadata incrementally

No speculative parallel Astra framework was introduced.

## Dead / stale / obsolete disposition

| Candidate | Disposition | Evidence |
|---|---|---|
| `backend/mcp_host/manager.py` + `manager_core.py` split | KEEP_INTENTIONAL | PR #83 deliberately kept the execution core stable while layering hardened boundary behavior. |
| Compatibility/tombstone/wrapper files generally | NEEDS_RUNTIME_PROOF | No deletion was performed without reference/import/config/history/runtime-registration evidence. |

No code was deleted merely because it looked unused.

## Current files changed on audit branch

Not exhaustive if further audit commits are added. Current material changes include:

- `tools/run_frontend_release_tests.mjs`
- `package.json`
- `verify_hades.py`
- `tests/release-gate-inventory.test.mjs`
- `.github/workflows/release-gates.yml`
- `backend/tests/test_workspace_backup_invariants.py`
- `backend/workspace_backup.py`
- `backend/tests/test_events_and_voice_p0.py`
- `backend/reasoning/events.py`
- this audit artifact

## Test / validation truth

Actually executed or directly observed:

- GitHub baseline/main SHA and branch state checked before write operations.
- Draft PR #84 created from the verified baseline.
- Current branch runs create all five expected GitHub check contexts including `release-gates-required`.
- Current jobs terminate without assigned runners or executed steps; therefore **no current CI command executed**.
- Isolated Python asyncio reproduction demonstrated the pre-fix cross-thread queue mutation error.
- Historical successful Release Gates were inspected only as historical resolver/runtime evidence and are not treated as current validation.

Not executed as current repository gates because no allocated GitHub runner/repository execution environment was available:

- `npm ci`
- `npm run typecheck`
- `npm run lint`
- `npm run build`
- canonical frontend Node tests
- backend unittest/integration suite
- Ruff security-boundary gate
- native CMake build
- CTest
- OpenAPI/TypeScript contract drift
- Gen2 offline release eval
- `python verify_hades.py`
- live LM Studio
- live browser/Puppeteer
- physical voice path
- Windows Job Object host validation

No PASS is claimed for commands that did not execute.

## Branch protection

Actual main state: **unprotected** with no required checks visible on the branch object.

Administrative desired state once available:
- PR required before merge where practical
- stale approvals handled appropriately
- conversation resolution requirement as appropriate
- force pushes disabled
- branch deletion disabled
- require stable `release-gates-required`

This audit cannot truthfully mark those settings fixed.

## Remaining risks

1. Python dependency graph is not reproducibly locked for release.
2. Hosted Ubuntu/Windows deterministic gates execute zero steps due external runner-allocation failure.
3. Main branch remains unprotected.
4. VoiceStudio has a confirmed async/sync boundary defect.
5. Backup/event fixes are implemented but not yet exercised by the current repository-defined suite.
6. Host/live-model/browser/voice claims remain unverified.
7. Wider Astra-6 uplift is architectural follow-on work, not completed by this release-integrity branch.

## Release verdict

**NOT_RELEASE_GREEN**

The remaining deterministic dependency P1 plus external CI/branch-protection blockers are sufficient to prevent a release-green conclusion. Additionally, current backup/event changes have not executed through the repository suite and VoiceStudio still has a confirmed async-boundary defect. Infrastructure failures are not being converted into software PASS.
