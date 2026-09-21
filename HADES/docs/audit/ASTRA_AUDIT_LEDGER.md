# HADES ASTRA Audit Ledger

> Persistent state for the multi-session full-repository audit, completion and hardening campaign.
>
> Historical test/build results are continuity evidence only. They never count as current validation unless rerun against the current code.

## Campaign rules

- Preserve existing functionality, public contracts and persisted formats unless evidence requires change.
- Do not mass-rewrite working systems for style.
- Category A defects and Category B completion of clearly intended functionality may be fixed after root-cause and regression analysis.
- Category C/new/speculative functionality requires explicit user approval in GitHub issue **#95 `APPROVAL?`** before implementation.
- Never claim PASS/verified/build success/test success unless that validation actually ran.
- Keep campaign work on draft PR **#96** / branch `astra-audit-2026-09-13` unless the user explicitly changes that instruction.
- Re-resolve `origin/main` and compare repository state with this checkpoint at the start of every new work session.
- Large stateful/runtime hotspots are not rewritten through coarse whole-file remote replacement merely to force a fix; when safe atomic editing or host validation is unavailable, record the defect honestly and keep it open.

## Current baseline — 2026-09-13

| Field | State |
|---|---|
| Repository | `syneyexx/HADES` |
| Reference branch | `main` |
| Authoritative remote `main` | `dbe0ed51f46e3c5908a0c5d9edca084bdfaeea25` |
| Baseline tree | `022343dde77dc8c594497d7d7a0efaf0389752c0` |
| Baseline commit | PR #94 merge — `fix: harden system prompts, network presets and Hugging Face dataset refs` |
| Audit branch | `astra-audit-2026-09-13` |
| Audit PR | Draft PR #96 — `ASTRA audit: full-repository hardening campaign` |
| Audit head before this ledger checkpoint | `39bb57f1934af77a8352560578e5813f4a242793` |
| Local checkout / HEAD | **UNOBSERVABLE** — HADES is not mounted in this execution sandbox |
| Local working tree | **UNOBSERVABLE** — do not infer clean/dirty state from GitHub remote state |
| Approval queue | GitHub issue #95, title exactly `APPROVAL?` |
| Latest inspected PR Actions run | `34726311732` on `39bb57f...`: all five jobs completed failure with no steps/logs; therefore **no software test result** |

## Architecture truth currently established

- HADES is a React/TypeScript/Vite browser application backed by FastAPI/Uvicorn; it is **not currently Electron**.
- `main.tsx` + `components/hades/hades-app.tsx` form the frontend entry/shell; `lib/hades-api.ts` is the canonical frontend API/type boundary.
- `backend/main.py`, `backend/database.py`, `backend/platform_db.py`, `backend/platform_services.py` and `backend/platform_services_core.py` are high-risk backend/orchestration boundaries.
- `HADES.bat` / `HADES_LAUNCHER.py` / `START_HADES.bat` are Windows launch paths; `PREPARE_HADES.bat` is setup/preparation; `VERIFY_HADES.bat` + `verify_hades.py` are the canonical full release verification path.
- Native C++20 lives under `native/`; Python/native integration lives under `backend/infrastructure/native/` and compatibility surfaces.
- MCP/plugin boundaries cross network, subprocess, approval, secret and external-data trust boundaries.
- Current deterministic full gate is `verify_hades.py`: TS typecheck, ESLint, production frontend build, canonical frontend tests, native build/CTest/install, backend unittest discovery, targeted Ruff boundary lint, Gen2 offline release eval and OpenAPI/TS drift check. Host/live probes remain separate.

## Master audit phases

1. **Repository, build, release and CI infrastructure** — `IMPLEMENTATION COMPLETE FOR CURRENT FINDINGS / FULL VALIDATION BLOCKED`
2. **Architecture / entry points / lifecycle map** — `DISCOVERY`
3. **Configuration, environment and secrets** — `AUDITING / ISSUES FOUND / PARTIAL HARDENING`
4. **Persistence, database, migrations and durability** — `DISCOVERY VIA SECRET-PERSISTENCE CROSSOVER`
5. **Core utilities / shared contracts / error model** — `NOT STARTED`
6. **Python backend runtime / API composition** — `DISCOVERY`
7. **Native C++ runtime / Python-native boundary** — `NOT STARTED`
8. **Model/provider abstraction and streaming** — `NOT STARTED`
9. **Agent architecture / planning / reasoning / recovery** — `NOT STARTED`
10. **Tool execution / permissions / subprocess / sandbox boundaries** — `DISCOVERY / ISSUES FOUND`
11. **MCP / plugins / integrations / OAuth** — `DISCOVERY / PARTIAL HARDENING`
12. **Browser / web / crawler / networking** — `NOT STARTED`
13. **PDF / document ingestion and extraction** — `NOT STARTED`
14. **RAG / embeddings / indexes / retrieval** — `NOT STARTED`
15. **Memory / brain / knowledge lifecycle** — `DISCOVERY / ISSUE FOUND`
16. **Conversation lifecycle / persistence / forget-delete semantics** — `NOT STARTED`
17. **Backend API contracts / auth / validation / error surfaces** — `DISCOVERY / ISSUES FOUND`
18. **GUI / Classic-Obsidian parity / async state / real bindings** — `NOT STARTED`
19. **Security boundary audit** — `DISCOVERY / ISSUES FOUND / PARTIAL HARDENING`
20. **Networking / IPC / streams / process lifecycle** — `DISCOVERY / PARTIAL HARDENING`
21. **Installer / launcher / packaging / update / migration compatibility** — `DISCOVERY / PARTIAL HARDENING`
22. **Reliability / cancellation / shutdown / recovery / observability** — `DISCOVERY / PARTIAL HARDENING`
23. **Performance / scaling / resource use** — `NOT STARTED`
24. **Test architecture / coverage / false-positive-green review** — `DISCOVERY / PARTIAL HARDENING`
25. **Documentation / setup / operational truthfulness** — `DISCOVERY / PARTIAL HARDENING`
26. **Cross-system integration review** — `DISCOVERY`
27. **Final adversarial pass** — `NOT STARTED`

Every subsystem must eventually move through `DISCOVERY -> AUDIT -> DEFECT ANALYSIS -> IMPLEMENTATION (if needed) -> TESTING -> REGRESSION CHECK -> VERIFIED`. No phase is VERIFIED merely because static/focused checks passed.

## Subsystem ledger

| Subsystem | Status | Current state / remaining evidence |
|---|---|---|
| Remote Git baseline | `VERIFIED` | Remote main repeatedly re-resolved to `dbe0ed51...`; no upstream drift observed this session. |
| Windows preparation | `FIXED / HOST-UNVERIFIED` | Runtime minimums enforced; ESLint added; setup wording honest. |
| Windows one-click/direct launch | `FIXED / HOST-UNVERIFIED` | Startup now fail-closed and verifies HADES identity before success/browser-open. |
| Native Windows build wrapper | `FIXED / HOST-UNVERIFIED` | Generator selection hardened; historical install-prefix error still unreproduced. |
| Canonical release gate | `AUDITED / PARTIAL` | Wrapper cannot label partial modes as full PASS; full execution unavailable. |
| GitHub workflow | `FIXED / CI-BLOCKED` | Duplicate native gate removed; Actions still fail before runner allocation. |
| Branch protection | `BLOCKED_EXTERNAL` | `main` remains unprotected; require stable release check only after Actions are functional. |
| Python dependency reproducibility | `ISSUE OPEN` | Runtime graph lacks a generated/validated transitive cross-platform lock/constraints process. |
| Optional HADES.exe packaging | `FIXED / HOST-UNVERIFIED` | Frozen root corrected; build tooling isolated/pinned; Windows EXE build/run unverified. |
| Bootstrap environment validation | `FIXED / FOCUSED-VALIDATED` | Startup config now rejects non-positive request timeout and concurrency <1. |
| MCP stdio child environment | `FIXED / FULL-SUITE UNVERIFIED` | Ambient credentials scrubbed; manager-explicit per-server env remains the only secret re-entry path. |
| Provider settings / config history | `ISSUES FOUND` | Provider credentials remain ordinary SQLite settings and general settings/control API values; history can persist old/new secret values. |
| Workspace archive secret exclusion | `ISSUE FOUND` | Secret-excluded archive redacts settings tables but not `setting_history`. |
| Plugin command environment | `ISSUE FOUND` | Default `plugin_cwd` inherits ambient credentials; restricted tiers preserve `HADES_*` secret-shaped keys. |
| Plugin dependency installation | `ISSUE FOUND` | pip/npm dependency code inherits parent env; marketplace path lacks main import policy gate. |
| Dataset Brain recovery truth | `ISSUE FOUND` | Job can reconcile to interrupted while stale manifest remains active-looking if manifest compensation fails. |

## Finding register

### F-2026-09-13-001 — Local repository state cannot be established from this execution environment
- **Severity:** OBSERVATION / validation constraint
- **Status:** OPEN CONSTRAINT.

### F-2026-09-13-002 — Historical native install error is not currently proven reproducible
- **Severity:** OBSERVATION
- **Decision:** Do not re-fix a superseded error without current Windows reproduction.
- **Status:** NEEDS WINDOWS HOST VALIDATION.

### F-2026-09-13-003 — PREPARE did not enforce advertised Node/Python minimums
- **Severity:** MEDIUM
- **Fix:** `tools/check_runtime_versions.mjs`; PATH and reused backend venv versions are checked.
- **Regression coverage:** `tests/prepare-runtime-preflight.test.mjs`.
- **Status:** FIXED / HOST-UNVERIFIED.

### F-2026-09-13-004 — CI duplicated the native full-release gate
- **Severity:** LOW
- **Fix:** Removed duplicate manual native workflow stage; `verify_hades.py` owns the canonical native gate.
- **Regression coverage:** `tests/release-gate-inventory.test.mjs`.
- **Status:** FIXED / CI EXECUTION BLOCKED EXTERNALLY.

### F-2026-09-13-005 — `main` lacks branch protection / required release check
- **Severity:** MEDIUM
- **Status:** BLOCKED_EXTERNAL / ADMIN ACTION after Actions works again.

### F-2026-09-13-006 — PyInstaller one-file launcher resolved runtime assets from the temporary bundle directory
- **Severity:** HIGH
- **Fix:** frozen root uses `sys.executable`; source mode uses `__file__`.
- **Regression coverage:** `backend/tests/test_launcher_packaging.py`.
- **Status:** FIXED / WINDOWS PACKAGING UNVERIFIED.

### F-2026-09-13-007 — Optional EXE build polluted runtime/build roots and floated build tooling
- **Severity:** MEDIUM
- **Fix:** isolated `.hades-cache/pyinstaller-venv`, generated outputs moved under cache, HADES.exe ignored, PyInstaller direct build tools pinned.
- **Status:** FIXED / WINDOWS BUILD UNVERIFIED.

### F-2026-09-13-008 — Windows startup paths could report/return success without service readiness
- **Severity:** HIGH
- **Fix:** shared fail-closed startup verifier; backend and frontend must both be reachable and identify as HADES; provider-heavy `/api/health` is deliberately not a launcher dependency.
- **Regression coverage:** `backend/tests/test_startup_readiness.py`, `tests/startup-readiness-contract.test.mjs`.
- **Status:** FIXED / WINDOWS HOST-UNVERIFIED.

### F-2026-09-13-009 — `VERIFY_HADES.bat` could label partial modes as a full release PASS
- **Severity:** HIGH
- **Fix:** release-skipping/unknown modes rejected by the Windows full-verifier wrapper.
- **Status:** FIXED / WINDOWS WRAPPER EXECUTION UNVERIFIED.

### F-2026-09-13-010 — Native wrapper could choose Ninja without an active MSVC environment
- **Severity:** MEDIUM
- **Fix:** Visual Studio generator used unless both active `cl.exe` and Ninja are available.
- **Status:** FIXED / WINDOWS HOST-UNVERIFIED.

### F-2026-09-13-011 — Package contract scripts used Unix-style `python3` on a Windows-first project
- **Severity:** LOW/MEDIUM
- **Fix:** package OpenAPI contract scripts now use `python`.
- **Status:** FIXED / FULL SUITE UNVERIFIED.

### F-2026-09-13-012 — Python runtime dependency graph is not reproducibly locked
- **Severity:** MEDIUM/HIGH RELEASE-REPRODUCIBILITY RISK
- **Decision:** Do not invent a freeze here; generate and validate a supported Windows/Linux/Python constraints/lock process.
- **Status:** OPEN.

### F-2026-09-13-013 — PREPARE release wording/gate inventory drifted from actual behavior
- **Severity:** MEDIUM / release honesty
- **Fix:** ESLint added; PREPARE labeled as preparation/setup; VERIFY documented as canonical full release verification.
- **Status:** FIXED / FULL WINDOWS EXECUTION UNVERIFIED.

### F-2026-09-13-014 — MCP stdio children inherited unrelated ambient host/HADES credentials
- **Severity:** HIGH / secret trust-boundary
- **Root cause:** MCP manager already constructed per-server env/keyring secrets, but legacy `StdioMcpClient` merged that map on top of `os.environ.copy()`.
- **Impact:** An MCP stdio server could see credentials unrelated to that server merely because the HADES process possessed them.
- **Fix:** Public `backend/mcp_host/clients.py` now wraps stdio spawning with `build_stdio_child_environment()`: non-secret runtime variables remain; credential-shaped ambient values are removed; explicit manager-selected server env is applied last.
- **Regression coverage:** `backend/tests/test_mcp_stdio_environment.py` verifies ambient-secret removal, normal runtime env retention and explicit per-server secret re-entry.
- **Status:** FIXED / FULL-SUITE UNVERIFIED.

### F-2026-09-13-015 — Provider secrets are ordinary SQLite settings and are exposed/persisted across generic config surfaces
- **Severity:** HIGH / secret storage and disclosure
- **Evidence:** LM Studio/TTS/STT API keys are normal settings; UI accepts real password values; `app_settings` stores JSON values; Control global/settings responses return general setting maps; `setting_history` serializes old/new values; workspace backup itself classifies these keys as secrets.
- **Contrast:** MCP credentials already use fail-closed OS keyring storage and explicitly avoid plaintext SQLite.
- **Required remediation:** secure-store migration for existing installations, write-path indirection, masked general API responses, compatibility-preserving UI save semantics, history cleanup/redaction and backup compatibility.
- **Safety constraint:** do not perform a partial migration that can lose existing credentials or break provider configuration.
- **Status:** OPEN / SAFE ATOMIC EDIT + MIGRATION TESTS REQUIRED.

### F-2026-09-13-016 — “Secrets excluded” workspace archives can retain provider secrets in `setting_history`
- **Severity:** HIGH
- **Root cause:** `_sqlite_backup_bytes(... redact_secrets=True)` redacts known keys from `app_settings`/`settings`, but does not redact matching rows in `setting_history`; archive metadata claims settings secrets were excluded/redacted.
- **Impact:** Old/new secret values can survive in an archive created with `include_secrets=false`.
- **Required remediation:** redact/delete secret-key history values in the temporary SQLite archive copy and add regression coverage proving raw secret bytes are absent.
- **Status:** OPEN / SAFE ATOMIC EDIT REQUIRED.

### F-2026-09-13-017 — Plugin command processes can inherit unrelated ambient credentials
- **Severity:** HIGH / plugin trust-boundary
- **Root cause:** default plugin isolation is `plugin_cwd`; `_command_environment()` starts from `os.environ.copy()` and only scrubs for restricted/temp/container/secured tiers. `restricted_environment()` additionally preserves all `HADES_*` keys even when they are secret-shaped.
- **Compatibility constraint:** existing catalog plugins legitimately consume env credentials; Fincept declares `required_env/optional_env`, while other integrations such as Composio document credential requirements without a uniform machine-readable authorization contract.
- **Required remediation:** credential access must be explicitly authorized, not granted merely because a manifest asks for an arbitrary host secret; preserve normal runtime env and deliberate provider/plugin credentials.
- **Status:** OPEN / SECURITY CONTRACT DESIGN + REGRESSION MATRIX REQUIRED.

### F-2026-09-13-018 — Plugin dependency installation crosses network/code-execution boundaries with ambient secrets, and marketplace install bypasses the main import policy gate
- **Severity:** HIGH
- **Evidence:** dependency preparation runs ordinary `pip install` / `npm ci|install`; package/build scripts may execute. `platform_services.py` supplies `os.environ.copy()` to the dependency runner. `plugin_auto_install_dependencies` defaults true. Main folder/Git import routes require file/network policy approval, but the local marketplace install route invokes `import_local_folder(..., install_dependencies)` without that `require_policy(...)` path.
- **Impact:** dependency code can inherit unrelated process credentials; marketplace dependency fetching can cross a network side-effect boundary without the same approval contract as normal import.
- **Compatibility constraint:** package-manager/private-registry credentials may be legitimate; blindly removing every token would break valid setups.
- **Required remediation:** policy-gate dependency network execution consistently and provide an explicit minimal/authorized environment for package managers rather than full HADES ambient env.
- **Status:** OPEN.

### F-2026-09-13-019 — Bootstrap environment accepted runtime-impossible timeout/concurrency values
- **Severity:** MEDIUM
- **Root cause:** `backend/config.py` used unconstrained `float`/`int` fields while runtime/API contracts require positive timeout and concurrency >=1.
- **Fix:** Pydantic `Field(default=120.0, gt=0)` for request timeout and `Field(default=2, ge=1)` for max concurrent tasks. No speculative upper bound was added because the Control Registry defines only the lower bound.
- **Regression coverage:** `backend/tests/test_bootstrap_config.py`.
- **Validation:** focused Pydantic cases reject timeout 0 and concurrency 0 and accept timeout 0.5 / concurrency 3.
- **Status:** FIXED / FULL-SUITE UNVERIFIED.

### F-2026-09-13-020 — Dataset Brain recovery can report stale active status after manifest compensation failure
- **Severity:** MEDIUM / state-truth reliability
- **Root cause:** `_reconcile_job()` durably changes the job to `interrupted`, then best-effort updates the dataset manifest and swallows manifest failure. `status()` overlays active latest jobs, but a terminal latest job only adds `latest_job_id`; therefore a stale manifest can continue reporting `running/queued`.
- **Required remediation:** read-side reconciliation should treat the durable latest terminal/interrupted job as authoritative when the manifest still advertises an active status; add a regression that forces manifest update failure.
- **Status:** OPEN / TARGETED STATEFUL FIX + REGRESSION TEST REQUIRED.

## Validation matrix — current checkpoint

| Validation | Result | Classification |
|---|---|---|
| Resolve remote `main` this session | still `dbe0ed51f46e3c5908a0c5d9edca084bdfaeea25` | REMOTE STATE VERIFIED |
| Audit PR continuity | PR #96 / `astra-audit-2026-09-13` | REMOTE STATE VERIFIED |
| Audit head before ledger checkpoint | `39bb57f1934af77a8352560578e5813f4a242793` | REMOTE STATE VERIFIED |
| Runtime version helper/parser boundary checks | passed earlier focused sandbox execution | FOCUSED ONLY |
| Launcher source/frozen root tests | 2/2 passed earlier focused sandbox execution | FOCUSED ONLY |
| Startup helper success/failure/identity cases | passed focused execution | FOCUSED ONLY |
| Bootstrap Pydantic invalid/valid env cases | passed focused execution | FOCUSED ONLY |
| MCP stdio env hardening regression source | added; no canonical suite execution available | STATIC/TEST ADDED, NOT FULLY EXECUTED |
| GitHub Actions run `34726311732` | all 5 jobs failure with `steps=null`, no logs | EXTERNAL BLOCK; **NO SOFTWARE TEST RESULT** |
| Local `git status` | unavailable | NOT EXECUTED |
| Full frontend typecheck/lint/build/release tests on PR head | unavailable | NOT EXECUTED |
| Full backend unittest suite on PR head | unavailable | NOT EXECUTED |
| Native CMake/CTest on PR head | unavailable | NOT EXECUTED |
| `VERIFY_HADES.bat` full Windows gate | unavailable | NOT EXECUTED / HOST-GATED |
| Actual PyInstaller Windows HADES.exe build/run | unavailable | NOT EXECUTED / HOST-GATED |
| Live LM Studio/browser/voice/sandbox probes | unavailable in real HADES host context | NOT EXECUTED / HOST-GATED |

## Static/broad scan state

Broad TODO/FIXME/HACK/XXX/stub/placeholder/NotImplemented/swallowed-exception/unsafe-fallback/false-success scanning is **IN PROGRESS**. Matches are only candidates until traced. High-signal paths already triaged include startup false-success, Dataset Brain interrupted recovery, MCP lifecycle error reporting, application lifecycle best-effort notes, research completion semantics and coding-job poll timeout semantics. Several broad exceptions were determined intentional best-effort behavior and were not classified as defects.

Targeted committed-secret searches found only empty examples/placeholders and explicit test fixtures in the inspected patterns; no real committed API credential/private key was established. This is a targeted static result, not an entropy-complete secret-scanner claim.

## Session log

### 2026-09-13 — Session 1 / Phase 1 discovery
- Resolved remote baseline and created audit branch, ledger and approval queue.
- Established browser/Vite + FastAPI architecture; corrected stale Electron assumptions.
- Audited Windows prepare/native wrapper, canonical verifier, CI workflow and branch protection.

### 2026-09-13 — Session 2 / Phase 1 hardening
- Hardened setup/version checks, release semantics, startup readiness, PyInstaller packaging, native generator selection and CI ownership.
- Added regression contracts for setup/launcher/build/release wrapper behavior.
- Confirmed full validation remains blocked by unavailable GitHub runners/no local Windows checkout.

### 2026-09-13 — Session 3 / Phase 2–3 architecture/config/security discovery

**Audited / traced**
- MCP stdio manager-to-client environment boundary.
- Provider settings persistence/API/history surfaces.
- Workspace archive secret-redaction behavior.
- Plugin runtime isolation/env inheritance.
- Plugin dependency-install environment and marketplace policy path.
- Bootstrap environment validation.
- Targeted committed-secret patterns and production flight-recorder redaction.
- Dataset Brain interrupted-job reconciliation candidate from the broad false-success scan.

**Implemented**
- Hardened MCP stdio child environment so unrelated ambient credentials are removed and only manager-explicit server env can re-enter.
- Added `backend/tests/test_mcp_stdio_environment.py`.
- Hardened bootstrap request timeout/concurrency validation in `backend/config.py`.
- Added `backend/tests/test_bootstrap_config.py`.
- Startup readiness identity hardening completed earlier in the same PR slice.

**Open high-priority defects**
1. F-015 provider settings secret storage/API/history migration.
2. F-016 workspace archive history redaction.
3. F-017 plugin ambient credential inheritance / explicit authorization model.
4. F-018 dependency-install environment + marketplace policy gate.
5. F-020 Dataset Brain stale interrupted-state reconciliation.

**Next action**
- Re-resolve `main` and audit head at the next turn.
- Continue Phase 3 with a safe, compatibility-preserving secret-store/API masking migration design and identify an atomic edit path before touching `main.py`/Control Service/database hotspots.
- Continue plugin/security audit around dependency credentials, manifest env contracts and approval boundaries; do not solve this by blindly stripping all registry tokens.
- Implement F-016 and F-020 only when the affected stateful files can be edited atomically and regression-tested.
- Keep Phase 1 and all security findings non-VERIFIED until canonical validation actually runs.

## `APPROVAL?` status

- Canonical page: GitHub issue #95 titled exactly `APPROVAL?`.
- New proposals: **none**.
- Approval-required work in progress: **none**.
