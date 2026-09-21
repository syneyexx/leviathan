# HADES ASTRA Audit — Phase 10G Coding / Side-Effect Durability

Date: 2026-09-13
Repository: `syneyexx/HADES`
Baseline main: `dbe0ed51f46e3c5908a0c5d9edca084bdfaeea25`
Audit branch: `astra-audit-2026-09-13`
Draft PR: #96

This checkpoint continues the existing audit campaign directly after Phase 10F. No new branch or pull request was created.

## Phase-9 coding-job unknown terminal-status finding — CLOSED IN SOURCE

- Severity: HIGH / terminal false-success.
- Status: FIXED / REGRESSION PROMOTED / FULL-SUITE UNVERIFIED.
- Owner: `backend/coding_jobs.py::CodingJobStore._work`.
- Root cause: the worker converted every runner result status outside `TERMINAL_STATUSES` into `completed`. Explicit states such as `timeout` could therefore become terminal success.
- Production fix: commit `22a1ea432bf689d5e2408bb476174e77d6a8221d` preserves the historical compatibility default only when the runner omits `status`; an explicit non-empty unknown status now fails closed to `failed`.
- Regression promotion: commit `1b70d7e94dc80829e5bd33738dcbfd9ef967d57f` removes `expectedFailure` from `backend/tests/test_coding_job_unknown_terminal_status_honesty.py`.
- Exact production diff: +4/-3 in the terminal-status normalization block only.

## Phase-9 side-effect ledger persistence finding — CLOSED IN SOURCE

- Severity: HIGH / durable side-effect truth, cancellation fencing and crash recovery.
- Status: FIXED / REGRESSION PROMOTED / FULL-SUITE UNVERIFIED.
- Owner: `backend/reasoning/long_task_resume.py::SideEffectLedger`.
- Root cause: `_save()` swallowed every `OSError`, while mutation callers continued returning successful state transitions. A durable ledger configured with `persist_path` could therefore claim an intent/fence/completion/reconciliation state that had never reached its canonical JSON snapshot.
- Production fix: commit `00a5dbee33da1e4d56d3a4557b82f23615458beb` makes `_save()` a boolean durability gate and restores in-memory ledger state from the last readable durable snapshot after a failed write. Mutating dict-return APIs now fail honestly with `persistence_failed` instead of returning success. `request_cancel()`, whose established return contract is a fence string, raises an explicit runtime persistence error rather than returning a non-durable fence.
- Late-artifact rejection remains fail-closed even if its audit snapshot cannot be written; its reason now exposes that persistence failure rather than claiming the rejection record was durably saved.
- Regression promotion: commit `cd4fbf5f09bf0d87f9c3928ff50c072e01c9764e` removes `expectedFailure`, requires `reason="persistence_failed"`, and verifies the failed record is also removed from in-memory lookup state.
- Production diff review: changes are confined to SideEffectLedger persistence/rollback and callers of `_save()`; no resume-planning or outcome-display logic changed.

## Still-open durability finding

### F-2026-09-13-069 — Build result persistence failure can be hidden from the immediate caller

- Status: OPEN / CHARACTERIZED.
- Existing characterization commit: `39919b76bbf03fe7925242a4b6ed29276c9c9a19`.
- Owner: `backend/build_agent.py::_persist_result` / `run_repair_loop` result paths.
- The direct caller can still receive a verified in-memory build result when the canonical `result.json` write failed. No production fix is claimed here.

## Safety-filtered sub-area note

Per the user's explicit instruction, the previously identified sub-area that triggered a cyber-safety warning was not further analyzed, expanded, or remediated in this continuation. Existing findings there remain unchanged/open. This intentional skip is recorded for continuity and is not evidence that the skipped area is safe or verified.

## Validation honesty

- Performed: source review, exact complete-blob replacement from current GitHub blobs, post-write per-commit diff review, focused regression-source promotion, and a four-commit slice comparison.
- Slice `3c187e1c...` -> `cd4fbf5f...` changes exactly four files: `backend/coding_jobs.py` (+4/-3), `backend/reasoning/long_task_resume.py` (+74/-15), `backend/tests/test_coding_job_unknown_terminal_status_honesty.py` (-1), and `backend/tests/test_side_effect_ledger_persistence_honesty.py` (+11/-3).
- Not performed: execution of the promoted regressions, canonical/full repository suite, Windows host verification, GitHub Actions validation, live provider calls, or external network probes.
- Therefore these fixes are source/diff reviewed but **not reported as passing tests**.
- `main` remains untouched. All writes remain on `astra-audit-2026-09-13` / draft PR #96.
- No Category C functionality was proposed or implemented. Issue #95 remains unchanged.

## Next continuation point

Stay in non-security-sensitive state truth/durability work. Prefer:

1. project-continuity stale-assumption packaging (existing expected-failure F-034) if an exact minimal current-blob diff can repair it;
2. F-069 build-result persistence, after tracing every result/error caller so a persistence failure cannot become a new recursive or misleading failure path;
3. remaining training stale-process / spawn-persistence / managed-delete honesty findings when their owner can be changed with a bounded, reviewable diff.

Do not re-enter the safety-filtered security/traversal sub-area unless the user explicitly changes that instruction.
