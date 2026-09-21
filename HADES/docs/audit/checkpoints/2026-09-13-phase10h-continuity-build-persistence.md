# HADES ASTRA Audit — Phase 10H Continuity / Build Result Persistence

Date: 2026-09-13
Repository: `syneyexx/HADES`
Baseline main: `dbe0ed51f46e3c5908a0c5d9edca084bdfaeea25`
Audit branch: `astra-audit-2026-09-13`
Draft PR: #96

This checkpoint continues the existing campaign after Phase 10G. No new branch or pull request was created.

## F-2026-09-13-034 — Falsified/superseded assumptions vanished instead of being reported stale

- Severity: MEDIUM / project-continuity and resume-context truth.
- Status: FIXED / REGRESSION PROMOTED / FULL-SUITE UNVERIFIED.
- Owner: `backend/project_continuity.py::context_package`.
- Root cause: `context_package()` queried `list_items(... active_only=True)` before attempting to classify `falsified` and `superseded` assumptions. `list_items()` intentionally filters those statuses in active-only mode, making the stale-classification branch unreachable.
- Production fix: commit `5b46b196ab525cf2e0a929fc4a4be783a6548855` keeps the existing active-only query unchanged and adds a separate assumption-only historical query (`active_only=False`, `include_superseded=True`) for `falsified`/`superseded` rows. Excluded rows remain excluded because `include_excluded` is not enabled.
- Proposal provenance remains governed by the existing `include_proposals` contract for both active and stale assumptions.
- Exact production diff: one `context_package()` hunk only, +12/-5.
- Regression promotion: commit `529bb0f6d89a09e5ac2ef74d4e6377d6e8fc1810` removes `expectedFailure` and covers falsified, superseded and excluded assumptions: stale rows are visible but never re-enter active context; excluded rows remain absent from both.

## F-2026-09-13-069 — Build result persistence failure could be hidden from the immediate caller

- Severity: HIGH / durability and terminal false-success.
- Status: FIXED / REGRESSION PROMOTED / FULL-SUITE UNVERIFIED.
- Owner: `backend/build_agent.py::_persist_result` and `run_repair_loop` error path.
- Root cause: `_persist_result()` swallowed `OSError`. `run_repair_loop()` could therefore mark a run `verified`, fail to write canonical `result.json`, still return the verified in-memory result, and leave `get_run()` unable to recover that result later.
- Production fix: commit `483fd924ae7c7b257c6cff222b16fe37a03ee82b` stops swallowing persistence errors. A failure on the normal verified path enters the existing outer failure path, changes the in-memory result to `failed`, and attempts to persist that failed result. If persistence remains unavailable, the second write failure is captured into `result.error` as `result_persistence_failed` and the caller still receives an honest failed result rather than verified success.
- Artifact export remains after successful result persistence; persistence failure therefore does not create an artifact that pretends the canonical run record was stored.
- Exact production diff: +7/-7, confined to `_persist_result()` and the outer error-path second persistence attempt.
- Regression promotion: commit `0502117668d4584455ed47cc746e970b8cb0b250` removes the direct characterization `expectedFailure` and adds a behavior-level fault-injection case. Even with a passing mocked test phase, repeated `result.json` write failure must return `status="failed"`, include `result_persistence_failed`, and leave no canonical result file.

## Safety-filtered sub-area note

Per the user's explicit instruction, the previously identified sub-area that triggered a cyber-safety warning was not further analyzed, expanded or remediated in this continuation. Existing findings there remain unchanged/open. This skip is intentional and does not count as verification.

## Validation honesty

- Performed: current source-contract review, exact complete-blob edits, post-write commit diff review, focused regression-source promotion and a four-commit slice comparison.
- Slice `4bee3c7e...` -> `05021176...` changes exactly four files: `backend/project_continuity.py` (+12/-5), its regression (+32/-9), `backend/build_agent.py` (+7/-7), and its regression (+44/-8).
- Not performed: execution of these tests, canonical/full suite, Windows host verification, GitHub Actions validation, live providers, external network probes, or destructive user-data tests.
- Therefore fixes are source/diff reviewed but **not reported as passing tests**.
- `main` remains untouched. All writes remain on `astra-audit-2026-09-13` / draft PR #96.
- No Category C functionality was proposed or implemented. Issue #95 remains unchanged.

## Next continuation point

Continue only in non-security-sensitive lifecycle/durability areas. Re-open the existing training lifecycle findings around stale-process truth, spawn persistence and managed deletion, preferring exact minimal owner diffs with fault-injection regressions. Avoid the user-requested safety-filtered traversal/security sub-area.
