# HADES ASTRA Audit — Phase 10F Execution Truth / Plan Liveness

Date: 2026-09-13
Repository: `syneyexx/HADES`
Baseline main: `dbe0ed51f46e3c5908a0c5d9edca084bdfaeea25`
Audit branch: `astra-audit-2026-09-13`
Draft PR: #96

This checkpoint continues the existing campaign directly after Phase 10E. No new branch or pull request was created.

## Phase-9 F-053 closure — Unknown tool execution statuses could normalize to success

- Severity: HIGH / execution-truth false success.
- Status: FIXED / REGRESSION PROMOTED / FULL-SUITE UNVERIFIED.
- Owner: `backend/execution_truth.py::_normalize_tool_status`.
- Previously characterized by `backend/tests/test_execution_truth_unknown_status_honesty.py`.
- Root cause: after handling explicit known statuses, the final fallback returned `succeeded` for any non-empty unknown status when no error string was present. Future/provider-specific states such as `timeout`, `interrupted`, or `provider_pending` could therefore become authoritative success.
- Remediation: commit `3e0bbd0d0d30d8e2e58c3536b1f85b074ea1777d` changes only the final fallback to `failed`. Known explicit success states (`completed`, `succeeded`, `success`, `ok`) are unchanged.
- Diff verification: the production commit changes exactly one line in `backend/execution_truth.py` (+1/-1).
- Regression promotion: commit `e1109052924cbc1b8049ecdf3164b6274c0369d0` removes the characterization `expectedFailure`; the regression still includes a known-success control.

## Phase-9 F-056 closure — Blocked plan dependencies did not block downstream work

- Severity: MEDIUM/HIGH / plan liveness and execution truth.
- Status: FIXED / REGRESSION PROMOTED / FULL-SUITE UNVERIFIED.
- Owner: `backend/reasoning/plan_scheduler.py::evaluate_dependency_states`.
- Previously characterized by `backend/tests/test_plan_scheduler_blocked_dependency_propagation.py`.
- Root cause: `TERMINAL_FAILURE_STATUSES` already included `blocked`, but dependency evaluation only populated its dependency-failure sets from `failed` and `cancelled` step statuses. A downstream step depending directly on a blocked step was therefore left pending rather than blocked.
- Remediation: commit `a46259152a2fd537d223e8557d771e273e23e556` tracks existing blocked step IDs separately and includes them in `deps_failed` while excluding them from `deps_pending`. Actual `failed_ids` remain reserved for steps whose status is `failed`; blocked is not mislabeled as failed in the returned top-level set.
- Diff verification: exactly +5/-2 in the dependency evaluator; no unrelated file content changed.
- Regression promotion: commit `79934975c947641d97b26c09f5d68f4c305108f5` removes the characterization `expectedFailure`.

## F-2026-09-13-069 — Build result persistence failure can be hidden from the immediate caller

- Severity: HIGH / durability and false-success truth.
- Classification: Category A defect.
- Status: OPEN / CHARACTERIZED.
- Owner: `backend/build_agent.py::_persist_result` and its `run_repair_loop` callers.
- Root cause: `_persist_result()` catches `OSError` from directory/result JSON persistence and returns silently. `run_repair_loop()` can then return the in-memory `BuildRunResult` (including `status="verified"`) to the direct API caller even though `result.json` was never durably written. A later `get_run()` only exposes a result when that file exists.
- Characterization: commit `39919b76bbf03fe7925242a4b6ed29276c9c9a19` adds `backend/tests/test_build_agent_result_persistence_honesty.py`. It fault-injects an `OSError` only for `result.json` and requires the persistence failure not to be silently swallowed. The test remains `expectedFailure` while the production defect is open.
- Safe remediation requirement: define the run-loop contract for persistence failure before editing the large stateful build owner. At minimum a verified in-memory result must not be returned as durable success when its canonical result record cannot be stored. The repair must preserve error-path persistence attempts and artifact-export semantics without creating recursion or masking the original runner outcome.
- No production patch was forced through a broad reconstruction in this checkpoint.

## Additional confirmed open durability findings

- `SideEffectLedger._save()` in `backend/reasoning/long_task_resume.py` still catches `OSError` and returns; callers including `record_intent()`, `complete()`, `fail()` and crash reconciliation can therefore report successful state transitions after durable snapshot failure. Existing Phase-9 characterization remains open.
- `CodingJobStore._work()` still maps every non-empty runner status outside `TERMINAL_STATUSES` to `completed`. The shared `coding_job_control.py` contract is explicit and is not the root cause; a workaround in the status-contract layer was deliberately rejected. Existing characterization remains open.
- The project-continuity stale-assumption finding from Phase 4B remains open: `context_package()` still calls `list_items(... active_only=True)` before trying to classify `falsified`/`superseded` assumptions as stale, so those rows cannot reach the stale-classification branch.

## Safety-filtered sub-area note

Per the user's instruction, the previously identified sub-area that triggered a cyber-safety warning was not further analyzed, expanded, or remediated in this continuation. Existing findings in that area remain open/unchanged. Skipping that area is not evidence of safety, correctness, or verification.

## Validation honesty

- Performed: remote branch-head continuity check, current-source review, characterization review, two narrowly scoped production changes, regression-source promotion, and exact commit/diff review.
- Exact slice diff from `39919b76bbf03fe7925242a4b6ed29276c9c9a19` through `e1109052924cbc1b8049ecdf3164b6274c0369d0`: four files only — `execution_truth.py` +1/-1, `plan_scheduler.py` +5/-2, and one-line `expectedFailure` removals in each focused regression file.
- Not performed: execution of these regressions, canonical/full backend/frontend/native suite, physical Windows verification, GitHub Actions execution, live providers, external network probes, or destructive user-data tests.
- Therefore the fixes are source/diff reviewed but **not reported as passing tests**.
- `main` remains untouched. All writes remain on `astra-audit-2026-09-13` / draft PR #96.
- No Category C functionality was proposed or implemented. Issue #95 remains unchanged.

## Next continuation point

Stay in non-security-sensitive durability/lifecycle work. Prefer, in order:

1. repair `CodingJobStore._work()` unknown runner-status promotion if the complete current blob can be replaced with a post-write diff proving only the intended status-normalization lines changed;
2. repair `SideEffectLedger` persistence honesty only with rollback/non-durable semantics explicitly defined and focused regression coverage;
3. repair F-069 build-result persistence after tracing API/get-run/error-path expectations;
4. revisit project-continuity stale-assumption packaging if it can be changed with an exact minimal diff.

Do not re-enter the safety-filtered traversal/security sub-area unless the user explicitly changes that instruction.
