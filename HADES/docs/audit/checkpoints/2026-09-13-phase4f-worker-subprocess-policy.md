# HADES ASTRA Audit — Phase 4F Worker Subprocess Policy

Date: 2026-09-13
Repository: `syneyexx/HADES`
Baseline main: `dbe0ed51f46e3c5908a0c5d9edca084bdfaeea25`
Audit branch: `astra-audit-2026-09-13`
Draft PR: #96

## F-2026-09-13-043 — Training job route ignores subprocess_policy

- Severity: HIGH / background process policy bypass.
- Status: PARTIAL REMEDIATION / ASK CONTRACT OPEN / FULL-SUITE UNVERIFIED.
- Root cause: `POST /api/training/jobs` enforced `network_policy` when model/dataset sources needed network, then called `TrainingWorkspace.create_job()`. That method starts `training_worker.py` with `subprocess.Popen`, but the route did not inspect `subprocess_policy`.
- Remediation completed: the training route now checks the absolute `subprocess_policy=block` boundary immediately before `TrainingWorkspace.create_job()`. A blocked policy therefore rejects with HTTP 403 before any worker launch, regardless of network approval.
- Production commit: `4cec8044c30092390fb6268edc0caf9fc219efdc`.
- Diff review: production changed by six added lines in `backend/training_routes.py`; the same commit also updates only the focused regression test. No training API/UI contract was silently widened.
- Permanent regression: `backend/tests/test_training_subprocess_policy.py::test_training_job_respects_subprocess_block_before_worker_spawn` is no longer expected-failure and requires `create_job()` to remain untouched under `block`. No subprocess/model/GPU work is executed by the test.
- Open remainder: `subprocess_policy=ask` still lacks a dedicated `approved_subprocess` request/UI field. A separate expected-failure test now records that gap. Network approval is deliberately not reused as subprocess approval.
- Required final remediation: add a distinct invocation-scoped subprocess approval through `TrainingJobInput`, `lib/hades-training-api.ts`, and the explicit Start Training UI action, then promote the `ask` characterization to a permanent gate. This was not forced via a whole-file rewrite of the larger training workspace UI.

## F-2026-09-13-044 — Dataset Brain indexing ignores subprocess_policy

- Severity: HIGH / background indexing process policy bypass.
- Status: FIXED / FULL-SUITE UNVERIFIED.
- Original root cause: `POST /api/training/brain/datasets/{dataset_id}/index` correctly enforced source-read policy, then called `DatasetBrainManager.create_job()` without enforcing `subprocess_policy`.
- Remediation: `DatasetBrainIndexInput` now has a dedicated `approved_subprocess` field and the route enforces `subprocess_policy` immediately before worker creation. `block` is absolute; `ask` requires the dedicated invocation approval.
- UI/API contract: `lib/hades-dataset-brain-api.ts` carries the dedicated approval and the explicit Dataset Brain start/reindex/rematerialize button sends `approved_subprocess: true`. Network/file approvals remain separate.
- Regression gate: `backend/tests/test_dataset_brain_subprocess_policy.py` is no longer `expectedFailure` and now covers (1) block cannot be overridden, (2) ask without approval is rejected, and (3) ask with explicit approval reaches job creation. The test uses a fake manager and starts no worker.
- Fix commit: `548d893abbe3b2495420721ae99580e139338efd`.
- Diff review: commit modifies exactly `backend/dataset_brain_routes.py`, `backend/tests/test_dataset_brain_subprocess_policy.py`, `lib/hades-dataset-brain-api.ts`, and `components/hades/features/training/dataset-brain-panel.tsx`; no unrelated production behavior was changed.
- Validation honesty: the regression was promoted to a permanent test but has not been executed in the canonical/full suite in this environment.

## Validation honesty

- No canonical/full suite was run.
- F-043 has an enforced block boundary but remains open for explicit `ask` approval semantics.
- F-044 is fixed by reviewed source + permanent regression contract, but test execution/full-suite validation remains unverified.
- No CI polling was performed.
- No Category C functionality was proposed or implemented.

## APPROVAL?

Issue #95 remains unchanged; no approval is required for this checkpoint.
