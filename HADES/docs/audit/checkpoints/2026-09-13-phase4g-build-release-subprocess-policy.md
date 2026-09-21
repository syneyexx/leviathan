# HADES ASTRA Audit — Phase 4G Build / Release Subprocess Policy

Date: 2026-09-13
Repository: `syneyexx/HADES`
Baseline main: `dbe0ed51f46e3c5908a0c5d9edca084bdfaeea25`
Audit branch: `astra-audit-2026-09-13`
Draft PR: #96

## F-2026-09-13-046 — Coding build routes ignore subprocess_policy

- Severity: HIGH / user-invoked code execution and test-process policy bypass.
- Status: OPEN / CHARACTERIZED.
- Runtime path: `POST /api/build/goal` calls `CodingAgentService.run_from_goal()` directly; `POST /api/build/goal/async` persists a recoverable job and dispatches it through the coding-job store. The build service can invoke Git and allowed test commands through `subprocess.run(..., shell=False)`.
- Defect: neither sync nor async route enforces `subprocess_policy` before execution/dispatch. `subprocess_policy=block` therefore does not prevent these coding/test subprocess paths.
- Scope nuance: command construction is allowlisted / argv-based and `shell=False`; this finding concerns the missing global permission gate, not shell injection.
- Regression characterization: `backend/tests/test_build_subprocess_policy.py` contains two independent `expectedFailure` API tests. The sync test mocks `CodingAgentService.run_from_goal`; the async test mocks the coding-job store. Neither test starts Git, tests, or any subprocess.
- Characterization commit: `6e837714c2ef07815664a07e0d6a6dafe375e8e8`.
- Required remediation: enforce subprocess allow/ask/block before sync execution and before async job dispatch. `ask` requires a dedicated invocation approval and must not reuse file/network approval implicitly.
- Safe-edit constraint: both routes live in large `backend/capability_routes.py`; no whole-file rewrite was attempted.

## F-2026-09-13-047 — Release-confidence smoke ignores subprocess_policy

- Severity: MEDIUM/HIGH / developer diagnostic process policy bypass.
- Status: OPEN / CHARACTERIZED.
- Runtime path: `POST /api/release/confidence/smoke` optionally calls `run_focused_unittest()`, which executes `python -m unittest ... -v` using `subprocess.run`.
- Defect: the API route does not consult `subprocess_policy` before starting that local test process.
- Scope nuance: `run_focused_unittest()` validates the dotted test module and does not use a shell; the issue is policy consistency rather than command injection.
- Regression characterization: `backend/tests/test_release_smoke_subprocess_policy.py` mocks both gate inventory and the unittest runner, then requires `subprocess_policy=block` to reject before the runner is called. The test starts no unittest process.
- Characterization commit: `08609a0b8108575561c5db90817c251c9c9e4346`.
- Required remediation: enforce subprocess allow/ask/block when `run_smoke=true`; pure inventory (`run_smoke=false`) must remain available because it does not spawn a process.
- Safe-edit constraint: the route lives in large `backend/capability_routes.py`; no risky whole-file replacement was attempted.

## F-2026-09-13-048 — Release-confidence inventory could report an unreadable VERIFY_HADES.bat as green

- Severity: MEDIUM/HIGH / release-gate honesty and false-green reporting.
- Status: FIXED / FULL-SUITE UNVERIFIED.
- Root cause: `inventory_gates()` caught `OSError` while reading an existing `VERIFY_HADES.bat` and replaced its contents with an empty string, but the gate status was still derived only from `verify_bat.is_file()`. An existing-but-unreadable canonical verifier could therefore be reported as `ok` with zero parsed stages.
- Remediation: verifier read failures are now retained as explicit evidence, the `verify_bat` gate becomes `error`, the detail reports the read failure, and the existing aggregate logic makes the inventory overall `error` with a `what_broke` entry. Missing-file behavior remains the existing `warn` contract.
- Production commit: `bc7840405dea3ec5cb41d8cd6a8ce1612097d425`.
- Regression coverage: `backend/tests/test_release_confidence_inventory_honesty.py` uses a temporary repository skeleton and injects an `OSError` only for `VERIFY_HADES.bat`; it requires gate + aggregate error and no fabricated stages. No subprocess or network operation is executed by the test body.
- Diff review: the production commit changes exactly `backend/release_confidence.py` (+11/-5) and the new focused regression test. No release execution path, smoke command or Windows wrapper was changed.
- Validation boundary: regression source was reviewed but not executed in the canonical/full suite in this environment.

## Non-finding: native companion lifecycle

- `POST /api/native/restart` may restart HADES' own native companion process.
- No repository contract was found proving that `terminal.subprocess_policy` is intended to disable core HADES companion lifecycle management.
- This path was therefore not classified as a policy bypass.

## Validation honesty

- No canonical/full suite was run.
- F-046 and F-047 remain OPEN / CHARACTERIZED.
- F-048 has a reviewed production fix + permanent regression source, but remains FULL-SUITE UNVERIFIED.
- Characterization/regression tests use mocked or local temporary boundaries and were not executed as a full suite here.
- No CI polling or external network probe was performed.
- No Category C functionality was proposed or implemented.

## APPROVAL?

Issue #95 remains unchanged; no approval is required for this checkpoint.
