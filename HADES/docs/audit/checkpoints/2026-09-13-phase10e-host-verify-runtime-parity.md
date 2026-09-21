# HADES ASTRA Audit — Phase 10E Host Verify Runtime Parity

Date: 2026-09-13
Repository: `syneyexx/HADES`
Baseline main: `dbe0ed51f46e3c5908a0c5d9edca084bdfaeea25`
Audit branch: `astra-audit-2026-09-13`
Draft PR: #96

This checkpoint continues the existing audit campaign. No new branch or PR was created. `main` was re-resolved before this continuation and remains at the recorded baseline SHA.

## F-2026-09-13-068 — Host verification consumers could still pass unsupported runtimes

- Severity: MEDIUM / setup, release and host-readiness honesty.
- Classification: Category A defect.
- Status: IMPLEMENTED / REGRESSION SOURCE ADDED / FULL VALIDATION UNVERIFIED.
- Owners: `backend/host_verify_sim.py` and `VERIFY_HADES_HOST.bat`.
- Related prior finding: F-050 correctly hardened `backend/host_capability.py` to require Python >=3.11, Node >=22.13, npm, Git and a writable workspace. This continuation re-checked how that readiness result is consumed.

### Root cause

The authoritative capability checker was correct, but two consumers still encoded the older contract:

1. `backend/host_verify_sim.py` independently accepted Python >=3.10.
2. The simulation treated Node as optional and did not independently require npm.
3. The simulation considered both `status="ready"` and `status="degraded"` from `check_host_capabilities()` acceptable, allowing the host verification suite to report `passed` even when the authoritative runtime checker explicitly reported a degraded host.
4. `VERIFY_HADES_HOST.bat` warned rather than failed when Node was missing, did not require npm, and invoked `check_host_capabilities()` only for its printed report; the Python command exited successfully regardless of whether the returned status was `ready` or `degraded`.
5. The batch file also contained a `#` pseudo-comment in cmd syntax; this was changed to `REM` while touching the same verification block so the verifier does not attempt to execute the comment text as a command.

### Remediation

- Commit `ede2041b809c8cfba20cccf7d0b42fc5b217c8c1` makes `host_verify_sim` derive the required Python/Node/npm/Git/workspace checks from the existing authoritative `host_capability` report rather than maintaining a second version policy. A degraded report can no longer satisfy the `host_capability_module` gate.
- Commit `20497af8c37f2234d275b7d23d1d0ec131cdc33a` makes `VERIFY_HADES_HOST.bat` require Node and npm, and makes the Python capability-report command exit non-zero unless the report status is exactly `ready`.
- Commit `8fcb91195bb6988c2c14ff96fe2a2c25f1afa8b3` adds `backend/tests/test_host_verify_runtime_contract.py`, locking the required capability set, degraded-report rejection, supported-report acceptance and the Windows batch fail-closed source contract.

### Compatibility / scope

- No runtime minimum was raised in this checkpoint; the existing HADES contract (Python >=3.11, Node >=22.13) is merely enforced consistently by its verifier consumers.
- Optional LM Studio/model reachability remains optional and does not block host runtime readiness.
- OS Job Object/AppContainer verification remains explicitly unclaimed; this change does not promote simulated isolation to physical verification.
- No new network or subprocess mechanism was introduced. The existing bounded local checks remain in place.

## Safety-filtered sub-area note

At the user's request, the sub-area from the previous continuation that triggered a cyber-safety warning was **not further analyzed, expanded or remediated in this continuation**. Existing audit records/findings for that area remain unchanged and must not be interpreted as closed or verified. This skip is intentional and recorded for continuity; no omitted validation is being reported as passing.

## Validation honesty

- Performed: current `main` re-resolution, branch/checkpoint continuity review, source/caller analysis, targeted production edits, targeted regression-source addition, and exact three-commit diff-stat review from `9a9e6b55...` to `8fcb9119...`.
- Diff scope before this checkpoint: exactly three files — `VERIFY_HADES_HOST.bat` (+16/-6), `backend/host_verify_sim.py` (+54/-34), and the new 56-line regression module.
- Not performed: execution of the new regression, canonical/full repository suite, physical Windows host run, GitHub Actions validation, live provider calls, or external network validation.
- `main` remains untouched. All writes remain on `astra-audit-2026-09-13` / PR #96.
- No Category C functionality was proposed or implemented. Issue #95 remains unchanged.

## Next continuation point

Continue the host/readiness consumer audit without revisiting the safety-filtered sub-area. Review the remaining host capability consumers and release/eval surfaces for stale assumptions, then move to the next non-security-sensitive open lifecycle/durability finding. Do not treat a shape-only or simulated check as proof of physical host readiness.
