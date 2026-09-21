# HADES ASTRA Audit — Phase 10D Lease Recovery / Repair Context

Date: 2026-09-13
Repository: `syneyexx/HADES`
Baseline main: `dbe0ed51f46e3c5908a0c5d9edca084bdfaeea25`
Audit branch: `astra-audit-2026-09-13`
Draft PR: #96

This checkpoint continues the existing audit campaign. No new branch or PR was created.

## F-2026-09-13-049 — Corrupt execution lease recovery state could be treated as empty

- Severity: HIGH / crash recovery, fencing and lifecycle correctness.
- Classification: Category A defect.
- Status: IMPLEMENTED / REGRESSIONS PROMOTED / FULL VALIDATION UNVERIFIED.
- Owners: `backend/run_leases.py` and `backend/app_lifecycle.py`.
- Historical root cause A: `ExecutionLeaseStore._load()` swallowed `OSError` and `json.JSONDecodeError`, leaving empty in-memory lease/control/generation maps when durable `execution_leases.json` was unreadable or corrupt.
- Historical root cause B: `app_lifecycle.startup()` wrapped lease persistence attachment, reclaim and pause/control restoration in a broad fail-soft block and continued startup after any recovery exception. Fixing only the loader therefore would not have made startup fail closed.
- Existing characterization: `backend/tests/test_run_lease_load_honesty.py` was originally added as an intentional expected-failure in commit `a1726817ad9133021f5eda8111097cd8769de3de`.
- Lifecycle characterization: `backend/tests/test_app_lifecycle_lease_recovery_honesty.py` was added as an intentional expected-failure in commit `555e75b5723df586bf302a834b2d683cba810fdb`.
- Production remediation:
  - commit `295120688afe3e29a4cf38fdbec39efbad179be1` makes `_load()` validate the full JSON document into temporary mappings before committing recovered state; malformed/unreadable durable state now raises `RuntimeError` instead of becoming an empty snapshot;
  - commit `88e74e11522fd692d227f31647fd67c04cb709b4` makes lifecycle lease attachment/reclaim/control restoration fail startup with a durable diagnostic note instead of continuing with unknown fencing state;
  - claim-store attachment remains separately fail-soft to avoid silently broadening F-049 into a different startup policy decision.
- Regression promotion:
  - `047eb1074abd6fa9de035412981119b757b737e4` removes expected-failure from corrupt-load coverage and adds a positive valid-state load control;
  - `c9fe536ff67174166b3bfa2910b84272133ac9de` promotes the lifecycle fail-closed regression to an ordinary contract test.
- Exact production diff review from lifecycle characterization base `555e75b...` through regression promotion `c9fe536...`: four files only; production changes are `backend/run_leases.py` (+22/-5) and `backend/app_lifecycle.py` (+14/-4), plus the two focused regression modules.
- Important validation boundary: these regressions were updated in source but were **not executed in this environment**. F-049 is therefore implemented/source-reviewed, not claimed as runtime-validated.

## F-2026-09-13-067 — Repair test-log paths can load files outside the isolated worktree into model context

- Severity: HIGH / test-output to filesystem-read to model-context trust boundary.
- Classification: Category A defect.
- Status: OPEN / CHARACTERIZED.
- Primary owner: `backend/coding_agent.py::propose_repair`, sharing the unsafe raw reader `backend/coding_agent.py::_read_rel` already relevant to F-060/F-062.
- Root cause: generic test-output path extraction can preserve strings such as `../../outside.py`; `propose_repair()` checks `(work_root / candidate).is_file()` without resolved containment and then passes the same candidate into `_read_rel()`. If that path resolves to a real file outside the isolated worktree, its contents can be included in repair context sent to the coding model.
- This is distinct from the existing out-of-root symlink scan finding: the path can be introduced directly through test output even without an in-workspace symlink.
- Characterization: `backend/tests/test_coding_agent_repair_log_path_boundary.py` uses a fake async chat callback only. It creates an outside file with a unique marker, injects a parent-relative path through synthetic failing-test output, captures the generated repair prompt, and requires neither the marker nor the outside relative path to appear.
- Characterization commit: `70275d5c175a42d84a6ea36bf7bea9f62dfaeca7`.
- The characterization is intentionally `expectedFailure` while this defect remains open and was not executed in this environment.
- Safe remediation direction: unify coding-agent read/path normalization behind a resolved-root gate and apply it before traceback/test-log candidate acceptance. This should be coordinated with F-060/F-062 rather than adding another isolated lexical check.

## Startup readiness candidate — ruled out as currently open

The older audit continuation note said `START_HADES.bat` and `HADES_LAUNCHER.py` still needed startup-honesty review. Current branch source already fails closed on readiness timeout:

- `HADES_LAUNCHER.py` calls `wait_for_local_hades()` and fails instead of opening the browser when backend/frontend do not become reachable;
- `START_HADES.bat` invokes `tools/local_startup_health.py`, exits non-zero on failed readiness and prints `HADES draait lokaal` only after successful readiness;
- launcher history includes commit `6011e6568191c46647645c8fde66ed4ecff7ba8c` (`fix: fail closed when launcher services never become ready`).

No new startup-readiness defect was opened from the older observation.

## Validation honesty

- Performed: source inspection, caller/lifecycle analysis, exact commit/diff review, and regression-source promotion/addition.
- Not performed: execution of the F-049/F-067 regressions, canonical/full repository suite, Windows-host validation, GitHub Actions validation, live provider calls, or real external subprocess/network validation.
- `main` remains untouched. All writes remain on `astra-audit-2026-09-13` / PR #96.
- No Category C functionality was proposed or implemented. Issue #95 remains unchanged.

## Next exact continuation point

Continue with `backend/host_capability.py` / F-050. Re-evaluate the current branch against the official Node >= 22.13 and Python >= 3.11 runtime contract, and trace how readiness is consumed. Any version probing must stay within HADES' existing process-execution policy architecture; do not introduce an uncontrolled subprocess or network dependency merely to close the finding. If a safe deterministic fix is not possible through the current owner, preserve the finding as open with characterization rather than bypassing policy.
