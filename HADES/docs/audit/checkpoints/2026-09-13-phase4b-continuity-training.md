# HADES ASTRA Audit — Phase 4B Continuity / Training Checkpoint

Date: 2026-09-13
Repository: `syneyexx/HADES`
Baseline main: `dbe0ed51f46e3c5908a0c5d9edca084bdfaeea25`
Audit branch: `astra-audit-2026-09-13`
Draft PR: #96

This checkpoint extends `2026-09-13-phase4-security-persistence.md`. It records findings created after F-031 without rewriting the larger earlier checkpoint.

## F-2026-09-13-032 — Approval public views leaked compound credential field names

- Severity: HIGH / secret disclosure boundary.
- Status: FIXED / FULL-SUITE UNVERIFIED.
- Root cause: `ApprovalService.public_view()` uses `redact_secrets()` before returning `arguments_json` / `arguments_preview`, but the old classifier masked only exact names such as `api_key`, `token`, `password`, `secret`, `authorization` and `auth`.
- Impact: compound credential fields such as `openai_api_key`, `refresh_token`, `client_secret`, `signing_private_key`, `aws_secret_access_key`, `authorization_header` and nested `hf_token` could be exposed to the approval API/UI.
- Fix: `backend/approvals.py` now classifies exact and bounded prefix/suffix credential field names while preserving ordinary metrics/fields such as `max_tokens` and `monkey`.
- Scope safety: durable approval arguments, fingerprints and decision logic are unchanged; only public redaction changed.
- Production commit: `c37646ceff8c74fd682e8ddc541466cb2e499779`.
- Regression coverage: `backend/tests/test_approval_secret_redaction.py`; promoted to permanent gate in `e2e1db617f192a9ecc84a94aa35e91905c0e2a8b` using synthetic fixture values only.
- Boundary: this does not resolve F-015 general provider-setting plaintext storage/API/history.

## F-2026-09-13-033 — Archived inbox rows permanently reserved their dedupe key

- Severity: MEDIUM / notification lifecycle correctness.
- Status: FIXED / FULL-SUITE UNVERIFIED.
- Root cause: `InboxService.create()` intended archived items not to block a fresh notification, but `inbox_items.dedupe_key` is globally unique while archive retained the key. A new insert hit the unique constraint and the DB helper returned the old archived row.
- Fix: when an existing dedupe row is archived, only its dedupe key is released (`NULL`) before creating the new unread item. Historical archived content/status remains intact and the DB unique index still serializes concurrent re-creates.
- Production commit: `052e33586d33e3364f828ee2cef8e24096b14753`.
- Regression coverage: `backend/tests/test_inbox_dedupe_archive.py`; permanent gate commit `d0d6507bc70df4bcc1f8b4b3c0e6d686f59f5606`.

## F-2026-09-13-034 — Falsified/superseded assumptions disappear from project continuity stale reporting

- Severity: MEDIUM / continuity truthfulness.
- Status: OPEN / CHARACTERIZED.
- Root cause: `context_package()` requests `list_items(... active_only=True)`, whose SQL already removes `falsified` and `superseded` rows. The subsequent branch intended to add those assumptions to `stale_assumptions` is therefore unreachable for those rows.
- Impact: an assumption that was explicitly falsified can disappear from both active context and stale-assumption reporting, weakening resume/provenance truth.
- Regression characterization: `backend/tests/test_project_continuity_stale_assumptions.py` (`expectedFailure`) created in commit `d7d4594abbbd8be81f7acf10bf03eccee2aed0f8`.
- Required remediation: build the context package from a query that includes stale assumptions for classification while still excluding them from active assumptions. Preserve excluded/superseded semantics and history.

## F-2026-09-13-035 — Abrupt training-worker loss leaves jobs permanently active-looking

- Severity: HIGH / training recovery and state truth.
- Status: OPEN / CHARACTERIZED.
- Evidence: `TrainingWorkspace.get_job()` and `list_jobs()` only read `job.json`; unlike Dataset Brain, there is no PID/process reconciliation. `training_worker.py` writes terminal `completed`, `cancelled` or `failed` states during normal exits, but an abrupt process kill/crash cannot execute that writer.
- Impact: `running` / `cancelling` jobs may remain active indefinitely after worker loss or restart. `delete_dataset()` explicitly refuses deletion while such a job exists, so stale state can also block dataset lifecycle operations.
- Security/storage note: training dataset/job JSON writes use same-directory temp files, flush + fsync + `os.replace`; HF tokens are passed only through the trusted internal worker environment and are not stored in job metadata.
- Regression characterization: `backend/tests/test_training_job_recovery_truth.py` constructs a dead-PID running job without starting ML dependencies and requires it not to remain in an active status; currently `expectedFailure`.
- Production characterization commit: `93c724e0a8a667d0f2cab2310304ee7f80f8c33e`.
- Required remediation: add Windows-safe/POSIX-safe read-only PID liveness reconciliation for active training jobs, convert abandoned jobs to an honest terminal/interrupted state, and preserve resume/cancel semantics. Do not use destructive `os.kill(pid, 0)` behavior on Windows.

## F-2026-09-13-036 — Training worker can start before running/PID state is durably recorded

- Severity: HIGH / process ownership and training lifecycle truth.
- Status: OPEN / CHARACTERIZED.
- Root cause: `TrainingWorkspace.create_job()` writes a queued job, starts the trainer with `subprocess.Popen`, and only afterwards writes `status=running`, `pid`, and `started_at` through the atomic JSON state writer.
- Failure window: if the post-spawn durable state write fails, the worker has already started but the API propagates an error and the persisted record can remain queued with no PID. HADES then lacks truthful ownership/control metadata for a live training process.
- Regression characterization: `backend/tests/test_training_spawn_persistence.py` uses a fake process and injected state-write failure; no trainer or ML stack is started. It requires an already-spawned process to be terminated if ownership state cannot be persisted. Currently `expectedFailure`.
- Characterization commit: `ac375f8b27a09051bfd2f0eac6a4b591fd1e54bc`.
- Required remediation: after spawn, if durable PID/running-state persistence fails, terminate/kill and reap the child before surfacing the persistence error; preserve the durable queued/failed truth according to the final chosen contract.

## F-2026-09-13-037 — Managed dataset delete can report success while uploaded bytes remain

- Severity: HIGH / user-data deletion truthfulness.
- Status: OPEN / CHARACTERIZED.
- Root cause: `TrainingWorkspace.delete_dataset()` first deletes `dataset.json` and its dataset directory, then attempts to remove the managed upload file/directory inside a broad `except OSError: pass` block.
- Impact: the API can return `204 No Content` even though HADES-managed uploaded dataset bytes remain on disk. Because metadata was already removed, the normal delete path no longer has the record needed for a clean retry.
- Scope: this applies to `source_type="upload"`; externally managed local-path datasets must not have their source files deleted by HADES.
- Regression characterization: `backend/tests/test_training_managed_delete_truth.py` injects a managed-upload deletion failure and requires the operation not to claim successful deletion while retaining bytes; currently `expectedFailure`.
- Characterization commit: `c86fed594b185c35718e16a93e9403a383746946`.
- Required remediation: for HADES-managed uploads, make source-byte removal and metadata removal failure-honest. On byte-removal failure retain enough metadata/state for retry and return an explicit failure; do not silently orphan user data.

## Completion-gate review — no new finding

- `decide_work_task_completion()` would technically accept `phase="verified"` when `passed` is absent because it only blocks explicit `passed is False`.
- The current production checkpoint writer in `backend/main.py` is the only repository production path found that writes a Work checkpoint with `phase="verified"`, and it writes `passed=True` explicitly.
- Therefore no current runtime path was established that can persist a verified Work checkpoint without the boolean. This remains a defensive-hardening candidate, not an evidence-backed defect.

## Additional audited paths with no new finding

- Approval decisions are genuinely compare-and-set at persistence level: `decide_approval_request()` updates only `WHERE id=? AND status='pending'`.
- Artifact payload writes are atomic and checksum-verified before DB registration. A DB registration failure can leave orphan filesystem material but does not return success; treat as cleanup debt, not false-green.
- Empty generated artifacts intentionally fail `ArtifactService.verify_ready()` via the `non_empty` invariant; existing threat model/evals make this a deliberate contract rather than a create-time status bug.
- Training dataset/job metadata uses an atomic temp + fsync + replace helper. No HF token is persisted in dataset/job JSON.
- Training cancellation has an asymmetric failure window (cancel marker can exist even if status persistence fails), but the worker still observes the marker and can materialize `cancelled`; no durable false-success was established from that path.

## Validation honesty

- Remote `main` was re-resolved during continuation and remained `dbe0ed51f46e3c5908a0c5d9edca084bdfaeea25`.
- No canonical full suite was run in this environment.
- F-032 and F-033 have production fixes plus permanent regression tests, but remain FULL-SUITE UNVERIFIED.
- F-034, F-035, F-036 and F-037 are characterization tests marked `expectedFailure`; they are not fixes.
- No CI polling is required for this audit slice; unavailable/queued Actions do not block continued static and focused repository work.

## Next exact slice

1. Continue compact persistence components for crash windows, deletion honesty, stale-state recovery and false-success.
2. Prefer real fixes only where file size/edit surface can be fully controlled through the available GitHub contents API.
3. Return to F-023/F-024/F-025/F-029/F-020 when a safe atomic edit path exists.
4. Revisit F-034/F-035/F-036/F-037 once their production files can be changed safely without large blind whole-file replacement.
5. Reconcile both Phase-4 checkpoints into the master ledger at a safe consolidation point.

## APPROVAL?

No Category C/new speculative functionality was proposed or implemented. Issue #95 remains unchanged.
