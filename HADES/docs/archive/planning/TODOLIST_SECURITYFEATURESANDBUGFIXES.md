# HADES — TODO LIST: SECURITY, FEATURES & BUG FIXES

Date recorded: 2026-09-13
Repository: `syneyexx/HADES`
Source audit branch: `astra-audit-2026-09-13`
Audit PR: #96
Baseline used by the ASTRA audit: `main` @ `dbe0ed51f46e3c5908a0c5d9edca084bdfaeea25`

> This file is the future-work queue left after the ASTRA audit/hardening campaign was made merge-ready.
>
> It contains only work that is still open, intentionally deferred, externally blocked, host/runtime-unverified, or not demonstrated as fully audited. Historical findings that were later fixed are deliberately not re-added as active TODOs.
>
> Before implementing any item, re-check current `main`, current production source and later commits. An old checkpoint saying `OPEN` is not sufficient evidence if the code has changed since this list was written.

---

## 0. Resume rules

- [ ] Re-resolve the current remote `main` and compare it with the state recorded here before changing anything.
- [ ] Do not assume source-reviewed regressions have passed until they are physically executed.
- [ ] Do not silently broaden public/persisted contracts while fixing an old defect.
- [ ] Prefer narrow fixes with permanent regressions over broad rewrites.
- [ ] New/speculative Category-C functionality must first be proposed in GitHub issue #95 `APPROVAL?` and explicitly approved by the user.
- [x] Path/workspace boundary findings F-060–067 were implemented in ASTRA continuation 2026-09-14 (`backend/path_boundary.py`). Windows symlink/privilege host verification remains UNVERIFIED_ON_HOST.

---

# 1. OPEN SECURITY / TRUST-BOUNDARY WORK

## 1.1 Secrets, configuration and credential handling

- [x] **F-015 — Move provider credentials out of ordinary SQLite/general settings surfaces.** ✅ FIXED (ASTRA continuation 2026-09-14)
  - OS keyring-backed `ProviderSettingsSecretStore` + fail-safe migration; masked API/history; plaintext retained when keyring unavailable.
  - Evidence: `backend/settings_secrets.py`, `backend/tests/test_provider_settings_secrets.py`.

- [x] **F-016 — Make `include_secrets=false` workspace backups actually secret-free.** ✅ FIXED (ASTRA continuation 2026-09-14)
  - Overrides/history redacted; fail-closed on redaction failure.
  - Evidence: workspace backup secret-redaction regressions.

- [x] **Phase-4C Secrets/Inbox F-038 — Control config export must redact all core provider secret settings.** ✅ FIXED (ASTRA continuation 2026-09-14)
  - Authoritative `SECRET_STORAGE_KEYS` includes LM Studio/TTS/STT.
  - Evidence: `backend/tests/test_control_export_secret_redaction.py`.

- [x] **F-017 — Define explicit plugin credential authorization instead of ambient credential inheritance.** ✅ FIXED (ASTRA continuation 2026-09-14)
  - `authorized_plugin_environment` + isolation-tier matrix; manifest `required_env`/`optional_env` re-admit path.
  - Evidence: `backend/tests/test_plugin_credential_authorization.py`.

- [ ] **F-018 — Harden plugin dependency-install environment and policy gating.** (PARTIAL)
  - Ambient secret scrub for dep installs: PASS on tip (`test_plugin_dependency_environment_security`).
  - Remaining: explicit marketplace/private-registry credential path review if product requires it.

## 1.2 Local API and privileged-process policy gaps

- [x] **F-024 — Add request-origin / trusted-Host protection for unsafe local API mutations.** ✅ FIXED (ASTRA continuation 2026-09-14)
  - `LocalApiTrustMiddleware` + loopback/`testserver` Host trust; Origin checks for unsafe methods.
  - Evidence: `backend/tests/test_local_api_origin_security.py`.

- [x] **F-040 / F-042 / F-043 / F-045 / F-046 / F-047 — Subprocess allow/ask/block.** ✅ FIXED (ASTRA continuation 2026-09-14)
  - Dedicated `approved_subprocess` across folder picker, terminal, training, preview, build, release-smoke.
  - Evidence: matching `test_*_subprocess_policy.py` suite + training UI wiring.

## 1.3 Intentionally deferred safety-filtered path/workspace boundary findings

These path/workspace findings were fixed in the ASTRA continuation (2026-09-14) via shared `backend/path_boundary.py`.

- [x] **F-060 / F-061 / F-062 / F-063 / F-066 / F-067 — Shared resolved-root containment.** ✅ FIXED
  - Symlink-aware containment for coding/build/investigate/repair/test targets + run IDs.
  - Evidence: path/build boundary regressions; Windows host semantics remain UNVERIFIED_ON_HOST.

---

# 2. OPEN DURABILITY / PERSISTENCE / CORRECTNESS BUGS

- [x] **F-012 — Create a reproducible Python dependency lock/constraints process.** ✅ FIXED (ASTRA continuation 2026-09-14)
  - `scripts/refresh_python_constraints.py` (+ `--check`) and `backend/requirements.lock.txt`.

- [x] **F-020 / F-023 / F-025 / F-028 / F-029 / F-053 / F-058 / F-064 / F-065** ✅ FIXED (ASTRA continuation 2026-09-14)
  - Dataset Brain recovery truth; Gen2 migration collision; MCP v16 atomicity; claim TZ expiry; coding atomic write; Work proposed_final coverage; symbol-cache sha256; build restore/apply honesty.
  - Evidence: corresponding `backend/tests/test_*` regressions PASS on Linux agent.

---

# 3. HOST / CI / RELEASE VALIDATION STILL NOT DONE

The branch was made **merge-ready at source/PR level**, not fully runtime-verified. These checks remain future work.

- [ ] Run the canonical full HADES verification against the merged/current code, including frontend typecheck/lint/build/tests, backend unittest discovery, native CMake/CTest/install, targeted boundary lint, release eval and OpenAPI/TS drift checks.
- [ ] Run `VERIFY_HADES.bat` on a real supported Windows host.
- [ ] Run `VERIFY_HADES_HOST.bat` on real supported/unsupported Python + Node combinations and confirm its fail-closed behavior physically.
- [ ] Build and launch the optional PyInstaller `HADES.exe` on Windows; verify runtime assets/root handling and launcher readiness.
- [ ] Reproduce or definitively close the historical native Windows install-prefix/directory failure noted as F-002.
- [ ] Execute Windows-specific regressions, especially path semantics, symlink availability, ctypes/PID liveness and launcher/build wrappers.
- [ ] Execute the promoted/source-reviewed regressions that were never physically run in the audit environment.
- [ ] Exercise real training-worker lifecycle cleanup: verify terminate/kill cleanup actually leaves no live orphan process after post-spawn state-persistence failure.
- [ ] Verify training PID-liveness reconciliation on Windows; current implementation is source-reviewed but physical Windows execution was unavailable.
- [ ] Consider a stronger training worker-identity contract if PID reuse proves material; current liveness is best-effort and not identity proof.
- [ ] Exercise real LM Studio/provider streaming against supported servers, including normal completion and interruption behavior.
- [ ] Exercise VoiceStudio/TTS/STT live provider paths and actual model/dependency installation where appropriate.
- [ ] Exercise browser/preview/live sandbox/native companion host paths in a real HADES installation.
- [ ] Restore functioning GitHub Actions runner execution. The observed audit runs failed before runner allocation with zero executed steps, so they produced no software test result.
- [ ] After Actions is actually stable, configure `main` branch protection / required release check (**F-005 / admin action**).

---

# 4. INCOMPLETE AUDIT COVERAGE / FUTURE DEEP PASSES

The original campaign was broad, but merge readiness did not mean every subsystem reached `VERIFIED`. The following areas still need a future end-to-end pass against the then-current codebase.

- [ ] Core utilities, shared contracts and error-model consistency.
- [ ] Native C++ runtime and Python/native boundary end-to-end audit.
- [ ] Browser/web/crawler/networking subsystem, including crawler result truth, cancellation, redirects, download limits and failure reporting.
- [ ] PDF/document ingestion/extraction end-to-end audit, including malformed/large document behavior and extraction-result truth.
- [ ] RAG, embeddings, indexes and retrieval lifecycle, including rebuild/recovery and provenance integrity.
- [ ] Memory/brain/knowledge lifecycle beyond the already-characterized Dataset Brain recovery bug.
- [ ] Conversation lifecycle/persistence/forget-delete semantics as a full subsystem, despite the already-reviewed transactional delete/search-trigger path.
- [ ] Backend API contract/auth/validation/error-surface pass beyond the specific route findings already recorded.
- [ ] GUI / Classic-Obsidian parity, async state, real backend bindings, stale loading/error states and false-success UI reporting.
- [ ] Installer/launcher/packaging/update/migration compatibility on actual supported Windows installations.
- [ ] Reliability/cancellation/shutdown/recovery/observability full-system pass after all open lifecycle fixes land.
- [ ] Performance/scaling/resource-use audit: large repositories, long conversations, large datasets, streaming backpressure, worker/process counts, memory use and disk growth.
- [ ] Test-architecture review for remaining expected-failure tests, skipped host tests, false-positive-green patterns and gaps between unit contracts and real integration behavior.
- [ ] Documentation/setup/operational truthfulness pass after future architecture/security changes.
- [ ] Cross-system integration review after the remaining security, persistence and policy fixes are complete.
- [ ] Final adversarial/regression pass across the entire repository before declaring a future release fully verified.

---

# 5. DEFERRED HARDENING / PRODUCT-POLICY CANDIDATES

These were not established as current defects requiring an immediate Category-A/B change, but they are worth revisiting later.

- [ ] Define an evidence-backed maximum input-size policy for Voice JSON `audio_base64` and upload transcription before adding limits. Selecting arbitrary limits is product policy, not a safe one-line defect fix.
- [ ] Revisit Work completion defensive handling of malformed/missing verification booleans if new writers appear; current reviewed production writer explicitly stores `passed=True` for verified checkpoints.
- [ ] Revisit Knowledge Freshness bulk-ingest `completed` + errors semantics if/when a production caller/user-facing path depends on that status.
- [ ] Decide whether direct registration of `managed_upload=True` datasets outside the managed upload directory should ever imply physical deletion. Current defect fix intentionally preserved existing compatibility semantics.
- [ ] Consider stronger worker ownership/identity tokens for long-lived background jobs where PID reuse/restart ambiguity matters.

---

# 6. FEATURE QUEUE / APPROVAL

- [ ] GitHub issue #95 `APPROVAL?` remains the mandatory queue for genuinely new functionality or substantial speculative architecture changes.
- [x] **User-approved via ASTRA continuation prompt (2026-09-14):** HADES Performance Foundation + Plugin Intelligence Layer (+ required engineering infrastructure). Recorded in PR #101 / `docs/audit/ASTRA_CONTINUATION_STATE.md` (issue #95 comment blocked: GraphQL not resolvable from this agent).
- [ ] Future agents should add other proposed Category-C functionality to #95 first and wait for explicit user approval before implementation.

---

# 7. IMPORTANT: DO NOT REDO ALREADY-CLOSED FINDINGS WITHOUT NEW EVIDENCE

The following notable areas were already fixed in source during the audit and should not be reopened merely because an older checkpoint says `OPEN`: execution-status false success, blocked dependency propagation, SideEffectLedger persistence honesty, coding-job unknown terminal status, project-continuity stale assumptions, build-result persistence honesty, corrupt lease-state startup recovery, host runtime readiness parity, F-035/F-036/F-037 training lifecycle/deletion fixes, LM Studio truncated-stream completion, evidence/tool-observation alignment, event-bus backpressure resync, provider-budget tool history/reserve handling, and the reviewed workspace/LSP search-boundary fixes.

They still belong in the **runtime/full-suite validation** queue above where validation was never physically executed.

---

## Source-of-truth audit references

Use these before implementing a future item:

- `docs/audit/ASTRA_AUDIT_LEDGER.md`
- `docs/audit/checkpoints/2026-09-13-phase4-security-persistence.md`
- `docs/audit/checkpoints/2026-09-13-phase4b-continuity-training.md`
- `docs/audit/checkpoints/2026-09-13-phase4c-secrets-inbox.md`
- `docs/audit/checkpoints/2026-09-13-phase4c-voice-boundaries.md`
- `docs/audit/checkpoints/2026-09-13-phase4d-privileged-route-policy.md`
- `docs/audit/checkpoints/2026-09-13-phase4e-provider-network-policy.md`
- `docs/audit/checkpoints/2026-09-13-phase4f-worker-subprocess-policy.md`
- `docs/audit/checkpoints/2026-09-13-phase4g-build-release-subprocess-policy.md`
- `docs/audit/checkpoints/2026-09-13-phase4h-host-runtime-honesty.md`
- `docs/audit/checkpoints/2026-09-13-phase8-model-provider-streaming.md`
- `docs/audit/checkpoints/2026-09-13-phase8b-verification-integrity.md`
- `docs/audit/checkpoints/2026-09-13-phase8c-provider-event-integrity.md`
- `docs/audit/checkpoints/2026-09-13-phase9-execution-durability-truth.md`
- `docs/audit/checkpoints/2026-09-13-phase10-search-workspace-boundaries.md`
- `docs/audit/checkpoints/2026-09-13-phase10b-coding-build-workspace-boundaries.md`
- `docs/audit/checkpoints/2026-09-13-phase10c-build-apply-durability.md`
- `docs/audit/checkpoints/2026-09-13-phase10d-lease-recovery-and-repair-context.md`
- `docs/audit/checkpoints/2026-09-13-phase10e-host-verify-runtime-parity.md`
- `docs/audit/checkpoints/2026-09-13-phase10f-execution-truth-liveness.md`
- `docs/audit/checkpoints/2026-09-13-phase10g-coding-ledger-durability.md`
- `docs/audit/checkpoints/2026-09-13-phase10h-continuity-build-persistence.md`
- `docs/audit/checkpoints/2026-09-13-phase10i-training-lifecycle-durability.md`
- `docs/audit/checkpoints/2026-09-13-phase10j-merge-readiness.md`
- GitHub issue #95 `APPROVAL?`

When a future item is completed, update this file by checking the item off and recording the fixing commit + permanent regression + actual validation state.