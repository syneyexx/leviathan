# HADES ASTRA Audit — Phase 10I Training Lifecycle / Durability Truth

Date: 2026-09-13
Repository: `syneyexx/HADES`
Baseline main: `dbe0ed51f46e3c5908a0c5d9edca084bdfaeea25`
Audit branch: `astra-audit-2026-09-13`
Draft PR: #96

This checkpoint continues the existing campaign after Phase 10H. No new branch or pull request was created.

## F-2026-09-13-035 — Persisted training jobs could remain active forever after worker loss

- Severity: HIGH / lifecycle truth and operator recovery.
- Status: FIXED / REGRESSION PROMOTED / FULL-SUITE UNVERIFIED.
- Owner: `backend/training_service.py::get_job` and `_process_is_alive`.
- Root cause: training worker ownership was tracked in process-local state while the durable job record persisted only a PID/status. After backend restart, a stale `running`/`cancelling` record could remain active indefinitely even when its worker no longer existed.
- Production fix: commit `61d31e6b6d973d5dfcadf750a32a8d4de821cbda` adds a best-effort cross-platform PID liveness check and reconciles persisted `running`/`cancelling` records whose process cannot be confirmed alive to `interrupted`, with an explicit error and `finished_at` timestamp.
- `queued` is intentionally not reconciled through the same rule because there is a legitimate creation window between writing the queued record and spawning the worker.
- Regression promotion: commit `b4ba169039c4e8ff8e70c91b49e89fa5b3c5e13d` removes `expectedFailure` from `test_training_job_recovery_truth.py`.
- Limitation: PID liveness is best-effort, not worker identity proof. PID reuse can theoretically make a stale record appear live. No command-line/identity token scheme was introduced in this defect fix.
- Windows liveness uses `OpenProcess` / `GetExitCodeProcess`; physical Windows execution was not available in this audit session.

## F-2026-09-13-036 — Training spawn/state failures could misreport lifecycle truth or leave a worker behind

- Severity: HIGH / lifecycle reliability, durability and honest failure reporting.
- Status: FIXED / REGRESSION PROMOTED FOR POST-SPAWN PERSISTENCE / FULL-SUITE UNVERIFIED.
- Owner: `backend/training_service.py::create_job`.
- Root cause A: a `subprocess.Popen(...)` failure was persisted as a failed job but returned from `create_job()` instead of re-raising, allowing the HTTP creation path to treat a worker that never started as successful job creation.
- Root cause B: after `Popen(...)` succeeded, failure to persist the durable `running`/PID state propagated out but left the newly spawned worker without cleanup.
- Production fix A: commit `61d31e6b6d973d5dfcadf750a32a8d4de821cbda` preserves the failed job record and re-raises the original spawn exception so the caller cannot report successful creation.
- Production fix B: commit `5603054266da38aa22680594fbedcf91237c7a3f` wraps the post-spawn `write_job_state(...)`; if durable running/PID registration fails, HADES requests `process.terminate()`, falls back to `process.kill()` only if termination itself raises, and re-raises the original persistence exception.
- Exact diff review for `56030542...`: one hunk only in `create_job`, +10/-4 relative to its parent; no unrelated source lines changed.
- Regression promotion: commit `d00e743e06845d968c3b61e1269634addce84c37` removes `expectedFailure` from `test_training_spawn_persistence.py`. The fault injection makes the second atomic job-state write fail after a fake worker has started, requires `create_job()` to raise `OSError`, and requires that worker to receive terminate/kill cleanup.
- The pre-spawn `Popen` exception-propagation path is source-reviewed here but not claimed as executed by this regression.
- Cleanup limitation: the regression proves cleanup is requested, not that a real OS process has exited. No physical process-lifecycle execution was available in this session.

### Write-integrity note for F-036

- An initial attempt, commit `3367deee2e47ab8b7f2816ab3d4ea73e7488d8f5`, contained the intended lifecycle hunk but post-write diff review also caught one unrelated accidental wording change in `_safe_dataset_id`.
- That attempt was immediately neutralized in commit `bd9865fa7ba16b3b8cf32f6cc0e81882209b5666` by restoring `backend/training_service.py` to the exact pre-attempt blob `2f3132df70c7974dfca885c6055ad6d6870248d7` through Git tree/blob SHA, preserving the already-correct test promotions.
- The production change was then reapplied cleanly as `5603054266da38aa22680594fbedcf91237c7a3f` and its post-write diff contains only the intended `create_job()` hunk.
- Therefore the effective branch state contains no accidental `_safe_dataset_id` wording change. The transient commits remain in history for audit transparency.

## F-2026-09-13-037 — Managed dataset deletion could orphan bytes while claiming success

- Severity: HIGH / data lifecycle and durable deletion truth.
- Status: FIXED / REGRESSION PROMOTED / FULL-SUITE UNVERIFIED.
- Owner: `backend/training_service.py::delete_dataset`.
- Root cause: metadata was removed before managed upload bytes, and payload deletion `OSError` was swallowed. The API could therefore report successful dataset deletion while the uploaded payload remained on disk with no metadata record for retry/recovery.
- Production fix: commit `61d31e6b6d973d5dfcadf750a32a8d4de821cbda` deletes an in-workspace managed upload payload first and raises `ValueError` on payload deletion failure; metadata is removed only after the payload step succeeds.
- Regression promotion: commit `63c8ce8ca12593bc5c9b0f28f6843ceebf64adf0` removes `expectedFailure` from `test_training_dataset_delete_honesty.py`. Its fault injection requires the payload and dataset metadata to remain present when payload unlink fails, so deletion remains retryable and cannot claim success.
- Existing behavior for paths outside `uploads_dir` was not broadened; API-created managed uploads use the managed upload directory, and changing direct-registration semantics without compatibility evidence would exceed this defect fix.

## Effective slice review

- Comparison from Phase 10H head `7b6176a678b34fe8e53890ead65e97467f862945` to regression head `d00e743e06845d968c3b61e1269634addce84c37` is ahead by seven commits and modifies exactly four effective files.
- Effective file stats: `backend/training_service.py` +75/-13; `backend/tests/test_training_job_recovery_truth.py` -1; `backend/tests/test_training_spawn_persistence.py` -1; `backend/tests/test_training_dataset_delete_honesty.py` -1.
- The larger training-service total includes the F-035/F-036/F-037 production hardening from `61d31e6...` plus the post-spawn cleanup hunk from `56030542...`; the transient bad/revert pair nets to zero in the final comparison.

## Safety-filtered sub-area note

Per the user's explicit instruction, the previously identified sub-area that triggered a cyber-safety warning was not further analyzed, expanded or remediated in this continuation. Existing findings there remain unchanged/open. This skip is intentional and does not count as verification or evidence of safety.

## Validation honesty

- Performed: source-contract review, exact branch/ref verification, existing-regression inspection, post-write commit diff review for every effective write, Git-tree exact rollback after one caught unrelated edit, and final slice comparison.
- Not performed: execution of the promoted tests, canonical/full suite, physical Windows verification, live trainer process execution, GitHub Actions validation, live providers, external network probes, or destructive user-data tests.
- Therefore these fixes are **IMPLEMENTED / SOURCE-REVIEWED** and regressions are **PROMOTED / SOURCE-REVIEWED**, but they are **not reported as passing tests**.
- `main` remains untouched. All writes remain on `astra-audit-2026-09-13` / draft PR #96.
- No Category C functionality was proposed or implemented. Issue #95 remains unchanged.

## Next continuation point

Continue with the next non-security-sensitive lifecycle/durability finding. Re-check the older Dataset Brain recovery/persistence finding F-038 only if it remains ordinary state/durability logic; do not cross into the user-requested safety-filtered traversal/security area. Prefer characterization first, exact owner-scope fixes, fault-injection regressions, and post-write diff review before any promotion.
