# HADES ASTRA Audit — Phase 10C Build Apply Durability

Date: 2026-09-13
Repository: `syneyexx/HADES`
Baseline main: `dbe0ed51f46e3c5908a0c5d9edca084bdfaeea25`
Audit branch: `astra-audit-2026-09-13`
Draft PR: #96

This checkpoint continues directly from Phase 10B. No new branch or PR was created.

## F-2026-09-13-064 — Build restore can report success while newly applied files remain

- Severity: HIGH / rollback correctness and failure honesty.
- Classification: Category A defect.
- Status: OPEN / CHARACTERIZED.
- Primary owner: `backend/build_agent.py::BuildAgentService.apply_to_source` / `restore_backup`.
- Public runtime path: `POST /build/{run_id}/apply` calls `apply_to_source()`, and `POST /build/{run_id}/restore` calls `restore_backup()` directly.
- Root cause: apply stores pre-apply bytes only for destinations that already exist. A newly added file has no entry under `pre_apply_backup`. Restore enumerates only that backup tree, so it restores modified pre-existing files but has no durable record telling it to remove files that the apply operation created.
- False-success impact: if an apply changed at least one old file and added at least one new file, restore can return `status="restored"` / `restored=true` after restoring the old file even though the newly added file remains in the source workspace. The source is therefore not actually returned to its pre-apply state.
- Characterization: `backend/tests/test_build_agent_restore_added_file_honesty.py` constructs an entirely local source/worktree, applies one modified and one added file, invokes restore, and requires both the old bytes to return and the newly added file to disappear. The test is intentionally `expectedFailure` while the defect remains open.
- Characterization commit: `062cc96aa8ea6c0a04a1735c2de7c896ac881152`.
- Safe remediation direction: persist an apply manifest that distinguishes pre-existing from newly created destinations, and on restore remove only apply-created files that still match the exact applied work-copy hash so later user edits are never deleted blindly.
- Why not fixed here: the correct repair crosses apply bookkeeping, restore conflict protection, durable apply metadata and symlink/path boundary work already open in F-061. A partial whole-file replacement of this large owner would create unnecessary risk.

## F-2026-09-13-065 — Mid-apply I/O failure can leave the source partially mutated

- Severity: HIGH / multi-file durability and atomicity.
- Classification: Category A defect.
- Status: OPEN / CHARACTERIZED.
- Primary owner: `backend/build_agent.py::BuildAgentService.apply_to_source`.
- Root cause: after preflight conflict checking, apply loops over changed files and mutates the user source one file at a time. There is no transaction/rollback guard around the loop. If backup/copy for a later file raises, earlier files may already contain worktree bytes.
- Failure-honesty impact: `apply.json` is written only after the loop completes. Therefore an exception can leave a partially modified source workspace without a durable completed/partial apply record, while the HTTP route receives an unhandled I/O failure rather than a coherent rollback outcome.
- Characterization: `backend/tests/test_build_agent_apply_atomicity.py` injects a deterministic `OSError` only on the second worktree-to-source copy, while all backup/first-file copies use the real local `copy2`. The desired invariant is that both source files remain at their original contents after the failed operation. The test is intentionally `expectedFailure` while the defect remains open.
- Characterization commit: `db33410ece714047c87c43324e742f66f6fd99c7`.
- Safe remediation direction: stage/backup all destinations before mutation, record the intended apply set durably, and guarantee rollback of already-written destinations if any later write fails. Restoration must remain conflict-aware and must not overwrite user edits made after a successful apply.
- Why not fixed here: the same large build owner currently also has unresolved source/worktree symlink boundary findings. Applying a narrow transactional patch without first defining those path semantics could make rollback itself unsafe.

## F-2026-09-13-066 — Windows build run IDs can traverse outside `build_runs`

- Severity: HIGH / public route to filesystem boundary.
- Classification: Category A defect.
- Status: OPEN / CHARACTERIZED / WINDOWS-HOST EXECUTION UNVERIFIED.
- Primary owner: `backend/build_agent.py` run lookup/apply/restore methods; route owner `backend/capability_routes.py`.
- Safe ID generation exists: `prepare_workspace()` creates run IDs internally through `new_id("build")`, producing `build_<uuid>` values.
- Defect boundary: public routes such as `/build/{run_id}`, `/build/{run_id}/preview`, `/apply` and `/restore` accept an unconstrained string and forward it directly. Service methods construct paths as `self.runs_root / run_id / ...` without validating the ID or proving the resulting run directory remains inside `runs_root`.
- Windows-specific impact: backslash is not the route's `/` separator but is a Windows filesystem separator. A value such as `..\\..\\outside-run` can therefore be one logical route parameter while `Path` resolves it outside `build_runs` on Windows. In `restore_backup()`, that can redirect `meta.json`, `pre_apply_backup` and worktree reads to a foreign run directory, after which metadata controls the source path being restored.
- Characterization: `backend/tests/test_build_agent_run_id_boundary.py` is an intentionally `expectedFailure`, Windows-only local regression. It creates a crafted run directory outside the HADES workspace and requires `restore_backup(r"..\\..\\outside-run")` to raise before reading/restoring it. The source file must remain unchanged.
- Characterization commit: `e10405eea5b479cd1991a0f686c4b5f1d6dcd271`.
- Validation nuance: the service-level Windows path behavior and unconstrained route forwarding are established by source. This session did not execute the route through a Windows Uvicorn/FastAPI host, so transport-level encoded-backslash behavior is not claimed as executed validation.
- Safe remediation direction: require canonical HADES build-run identifiers at the shared service boundary (or resolve-and-contain one run directory once) so every get/preview/conflict/apply/restore path fails closed before filesystem access. Route handlers should convert invalid IDs to a client error rather than relying on path normalization.
- Why not fixed here: a complete repair should cover every build run-ID consumer consistently and must be coordinated with the already-open build path/symlink/restore findings rather than protecting only one endpoint.

## Validation honesty

- Performed: source review, public route/caller confirmation, exact branch-head checks, and focused local regression source additions.
- Not performed: execution of the new regressions, canonical/full repository suite, Windows-host validation, GitHub Actions validation, live provider calls, or real subprocess/network validation.
- `expectedFailure` records known-open behavior only; it is not evidence the tests were run.
- The F-066 regression is Windows-only by design and was not executed in this environment.
- `main` remains untouched. All writes remain on `astra-audit-2026-09-13` / draft PR #96.
- No Category C functionality was proposed or implemented. Issue #95 remains unchanged.

## Next exact continuation point

Continue from `backend/coding_agent.py::propose_repair` and its traceback/test-log-derived `sample_files` construction. Determine whether untrusted test output or symlink aliases can cause `_read_rel()` to load files outside the isolated worktree into model repair context. Then inspect `_persist_result()` and adjacent build lifecycle persistence for false-success/data-loss behavior; do not classify its fail-soft `OSError` handling without tracing callers and recovery expectations.
