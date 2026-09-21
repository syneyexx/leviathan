# HADES ASTRA Audit — Phase 9 Execution / Durability Truth

Date: 2026-09-13
Repository: `syneyexx/HADES`
Baseline main: `dbe0ed51f46e3c5908a0c5d9edca084bdfaeea25`
Audit branch: `astra-audit-2026-09-13`
Draft PR: #96

## F-2026-09-13-052 — Tool-observation evidence classification may over-promote support

- Severity: HIGH candidate / verification truth.
- Status: PARKED / NEEDS CALLER-SEMANTICS REVIEW; no production change.
- Candidate root cause: `reasoning.evidence_coverage.classify_support()` can return `direct_observation` for `is_tool_observation=True` when referenced evidence kinds are tool/deterministic checks without first proving the claim text is actually supported by the referenced evidence content.
- Reason for parking: before changing a central verification classifier, caller-side evidence matching semantics must be completed. The audit intentionally moved on rather than spending disproportionate time on one candidate.
- No regression or production behavior was changed for F-052 in this checkpoint.

## F-2026-09-13-053 — Unknown tool execution statuses can normalize to success

- Severity: HIGH / execution-truth false success.
- Status: OPEN / CHARACTERIZED.
- Root cause: `execution_truth._normalize_tool_status()` treats any unknown non-empty status without an explicit error as `succeeded` in its final fallback. Values such as `timeout`, `interrupted`, `provider_pending`, or future provider-specific states can therefore become authoritative success.
- Existing regression gap: prior tests cover known `failed` and `completed` values but not unknown non-empty statuses.
- Characterization: `backend/tests/test_execution_truth_unknown_status_honesty.py` requires unknown statuses to fail closed and keeps known `completed` as a permanent success control. The unknown-status case is currently `expectedFailure`.
- Characterization commit: `770850dd691426d53650a19a541255a2cdc510a8`.
- Required remediation: map only explicit success statuses to `succeeded`; unknown terminal/provider statuses must remain non-success unless a typed normalization layer explicitly recognizes them.
- Safe-edit constraint: `backend/execution_truth.py` is a large central owner and the available connector replaces complete files; no blind whole-file production rewrite was performed.

## F-2026-09-13-054 — SideEffectLedger persistence failure can still report durable success

- Severity: HIGH / crash-recovery, idempotency and side-effect truth.
- Status: OPEN / CHARACTERIZED.
- Root cause: `reasoning.long_task_resume.SideEffectLedger._save()` catches `OSError` and returns. Callers such as `record_intent()` and `complete()` mutate in-memory state, invoke `_save()`, then return `ok=True` even if the durable JSON snapshot was not written.
- Impact: HADES can claim a crash-recovery/idempotency intent is recorded while the only durable copy is absent. A crash can then forget the intent and permit duplicate or unreconciled external side effects.
- Characterization: `backend/tests/test_side_effect_ledger_persistence_honesty.py` fault-injects a local snapshot write failure and requires the operation not to report success. It is currently `expectedFailure` and performs no network I/O.
- Characterization commit: `53bdf770d883f2db17ee83de39f568dca73eee3c`.
- Required remediation: make durable persistence failure observable and roll back or explicitly mark non-durable in-memory mutations before returning. Preserve late-artifact/cancel-fence semantics.
- Safe-edit constraint: `long_task_resume.py` is a large stateful owner; no blind full-file replacement was performed.

## F-2026-09-13-055 — Unknown coding-runner terminal status is promoted to completed

- Severity: HIGH / coding-job false completion.
- Status: OPEN / CHARACTERIZED.
- Root cause: after a runner returns, `CodingJobStore._work()` reads `result.status` and converts every value not present in `TERMINAL_STATUSES` to `completed`.
- Authoritative terminal contract: `coding_job_control.TERMINAL_STATUSES` contains `cancelled`, `interrupted`, `verified`, `failed`, `completed`, and `tests_failed`. An unknown value such as `timeout`, `verification_failed`, or a future provider/runtime state is not completion evidence.
- Characterization: `backend/tests/test_coding_job_unknown_terminal_status_honesty.py` runs a temp local job whose runner returns `status=timeout` and requires the durable job not to become `completed`. It is currently `expectedFailure`; no network is used.
- Characterization commit: `534feb823898af21ce6d75abc4f563a5b1c302f5`.
- Required remediation: accept only explicit terminal statuses; unknown runner statuses must fail closed (or map through a typed explicit translation), preserving runner error/evidence in the job record.
- Safe-edit constraint: `backend/coding_jobs.py` is a large stateful owner; no blind full-file replacement was performed.

## F-2026-09-13-056 — A blocked plan dependency does not propagate blocked state downstream

- Severity: MEDIUM/HIGH / plan liveness and execution truth.
- Status: OPEN / CHARACTERIZED.
- Root cause: `plan_scheduler.TERMINAL_FAILURE_STATUSES` includes `blocked`, but `evaluate_dependency_states()` only adds steps with status `failed` to the failed set and status `cancelled` to the cancelled set. A dependency already marked `blocked` is therefore treated as neither completed nor failed, leaving dependents pending instead of deterministically blocked.
- Impact: a plan can stall/deadlock behind a permanently blocked dependency instead of surfacing a clear blocked chain.
- Characterization: `backend/tests/test_plan_scheduler_blocked_dependency_propagation.py` requires the downstream dependency state and `apply_blocked_statuses()` output to become blocked. It is currently `expectedFailure`.
- Characterization commit: `8855ab1af3308fe87a536bd3731a6da4893d3907`.
- Required remediation: include already-blocked steps in dependency-failure propagation while preserving root blocked-step semantics and existing failed/cancelled behavior.

## F-2026-09-13-050 closure carried into this slice

- Host capability readiness was repaired separately before this checkpoint: Python >=3.11, Node >=22.13, npm, Git and writable workspace are required for `ready`; Node is checked with a bounded local argv subprocess.
- Existing expected-failure host readiness characterizations were promoted to permanent tests so a successful fix cannot produce unittest `unexpected success` failures.
- Full-suite/Windows validation remains unexecuted here.

## Validation honesty

- No canonical/full backend/frontend/native/Windows suite was executed for F-052 through F-056.
- The F-053/F-054/F-055/F-056 regression sources were added but their expected-failure behavior was not claimed as locally executed in this environment.
- No CI polling, live provider probe, external network test, or destructive user-data operation was performed.
- All work remains on draft PR #96 / `astra-audit-2026-09-13`; `main` was not modified.
- No Category C functionality was proposed or implemented.

## APPROVAL?

Issue #95 remains unchanged; no approval is required for these defect characterizations.
