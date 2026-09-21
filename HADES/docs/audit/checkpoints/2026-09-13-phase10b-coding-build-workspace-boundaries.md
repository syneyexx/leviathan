# HADES ASTRA Audit — Phase 10B Coding / Build Workspace Boundaries

Date: 2026-09-13
Repository: `syneyexx/HADES`
Baseline main: `dbe0ed51f46e3c5908a0c5d9edca084bdfaeea25`
Audit branch: `astra-audit-2026-09-13`
Draft PR: #96

This checkpoint continues directly from Phase 10. No new branch or PR was created.

## F-2026-09-13-060 — Coding Agent exploration can read a file symlink outside the workspace

- Severity: HIGH / workspace file-read boundary and prompt/context confidentiality.
- Classification: Category A defect.
- Status: OPEN / CHARACTERIZED.
- Primary owner: `backend/coding_agent.py`.
- Root cause: `_iter_source_files()` traverses `root.rglob("*")`, accepts `path.is_file()`, and `explore_repository()` subsequently reads those paths without checking where a symlink target resolves. A file symlink lexically inside the workspace can therefore point outside the approved workspace and its target contents can enter an `ExploreHit` preview/hash and downstream coding context.
- Related helper: `_read_rel(root, rel)` directly reads `root / rel` without resolved-root validation, so a coherent remediation should not patch only the scanner.
- Characterization: `backend/tests/test_coding_agent_workspace_symlink_boundary.py` creates an in-workspace Python symlink to an outside file containing a unique marker and requires exploration not to return/read that marker. The test is intentionally `expectedFailure` while the defect remains open; hosts without symlink support skip only the symlink-specific case.
- Characterization commit: `e341ef0447260221d901739daf28cdcf07844aee`.
- Safe remediation direction: introduce/reuse one deterministic workspace path resolver for coding-agent reads and scans, reject paths whose resolved target is outside the root, and preserve ordinary files plus symlinks resolving inside the workspace.
- Why not fixed here: `coding_agent.py` is a large stateful owner with multiple read/edit paths. The available remote writer performs complete-file replacement, so a broad reconstruction solely to close this finding would create unnecessary regression risk.

## F-2026-09-13-061 — Build Agent isolation can consume external symlink targets

- Severity: HIGH / workspace isolation and external-file ingestion.
- Classification: Category A defect.
- Status: OPEN / CHARACTERIZED.
- Primary owner: `backend/build_agent.py`.
- Root cause A: `BuildAgentService.detect_baseline()` traverses `repo.rglob("*")`, accepts `is_file()`, and hashes with `_sha256_file(path)` without resolved containment. A file symlink inside the source repository can therefore make baseline capture read bytes outside the repository.
- Root cause B: when detached Git worktree creation is unavailable/not applicable, `prepare_workspace()` falls back to `shutil.copytree(source, work, ...)` with the default symlink behavior. File symlinks are dereferenced by that copy path, so bytes from an outside target can be materialized into the supposedly isolated build copy.
- Root cause C: downstream worktree enumeration (`_unified_diff()`, `_changed_files()` and related conflict/apply paths) also relies on lexical `rglob()` / `is_file()` checks and hashes/reads those files without first proving their resolved target remains inside the worktree. A file symlink created during a build/test can therefore be treated as an ordinary changed file whose external target bytes are hashed and can enter later review/apply logic.
- Existing positive control: `_safe_relpath()` already resolves and contains explicit edit destinations, so the defect is specifically in source/worktree enumeration, baseline/copy and later change accounting rather than every explicit edit path.
- Characterization: `backend/tests/test_build_agent_copy_symlink_boundary.py` now contains three intentionally `expectedFailure` cases: baseline hashing must omit an out-of-root source symlink; copy fallback must not materialize the outside target; and `_changed_files()` must ignore an out-of-root symlink introduced into the worktree. Git invocation is mocked/no real subprocess is required. Symlink creation is skipped only when unavailable on the host.
- Characterization commits: `d1b395c9c13273e19185553cbe68b3518dc1936c`, `ac8d0eaca18ba6a5dbe0bbba7ed2f70b77869754`, expanded again by `cb29ea070e6100ce5682ac5bdb9d8fb58cb0ef81`.
- Safe remediation direction: define explicit source/worktree symlink semantics, ensure all enumeration/hashing/copy/apply inputs are resolved and contained before HADES reads them, and make copy fallback preserve or reject links according to that contract instead of silently dereferencing outside targets.
- Why not fixed here: the owner combines baseline hashing, Git worktrees, copy fallback, edits, tests, diffing, apply/conflict handling and restore. The correct repair needs a coherent source/worktree isolation contract and focused regressions rather than a risky whole-file remote rewrite.

## F-2026-09-13-062 — Coding Investigator filesystem actions/import expansion can escape workspace

- Severity: HIGH / model-to-filesystem trust boundary and local file disclosure.
- Classification: Category A defect.
- Status: OPEN / CHARACTERIZED.
- Primary owner: `backend/coding_investigate.py`, with the raw read helper in `backend/coding_agent.py::_read_rel`.
- Root cause A: `InteractiveCodingInvestigator._load(rel)` forwards directly to `_read_rel(self.root, rel)`, which performs `(root / rel).read_text(...)` without containment validation. `_dispatch()` exposes this through both `read_file` and `read_span` actions.
- Model path relevance: `_model_select_action()` validates that the proposed action `kind` is in the allowed set, then merges model-provided `args` over the template. It does not restrict a proposed read path to selected files or validate that the resolved path remains within the workspace. Therefore the defect crosses the model/action-to-filesystem boundary rather than being only an unreachable helper issue.
- Root cause B: `_resolve_relative_js()` constructs a lexical path from the importing file plus relative import specifier, checks `(self.root / cand).is_file()`, and can return a path such as `nested/../../outside.ts` without resolved containment. That resolved path can subsequently enter selection and `_load()`.
- Characterization: `backend/tests/test_coding_investigate_read_path_boundary.py` contains intentionally `expectedFailure` local tests for `read_file`, `read_span`, and an in-workspace TypeScript file whose `../../outside` import would resolve outside the workspace. The read actions require outside markers never to appear; the JS resolver must return no outside target.
- Characterization commits: `a57370c0507ba11cf76601321092b602504ab6dd`, expanded by `1aceb1fcc2b05e80bd407ecd323c859886628bf8`.
- Safe remediation direction: all investigator filesystem reads and import resolution should pass through the same resolved-root gate; action validation should reject invalid/outside paths before I/O while preserving selected in-workspace files and legitimate internal symlinks.
- Related review: `backend/code_intel.py::analyze_file()` already resolves the candidate and rejects paths outside root, so that helper is not the source of this defect. Phase-10 F-059 also separately hardened `read_diagnostics()`.
- Why not fixed here: `coding_investigate.py` is a large orchestration owner and shares the unsafe primitive with `coding_agent.py`. A shared/coherent correction is safer than duplicating partial checks through complete-file remote replacement.

## F-2026-09-13-063 — Build test targets can escape the isolated worktree

- Severity: HIGH / workflow-to-subprocess workspace boundary.
- Classification: Category A defect.
- Status: OPEN / CHARACTERIZED.
- Primary owner: `backend/build_agent.py::BuildAgentService.run_tests`.
- Root cause: `run_tests()` accepts any `extra_args` item that starts with `-`, contains `/` or `\\`, or ends in `.py`, and appends it directly to the chosen test command. It does not resolve path-like test targets against `work_root` or reject parent-relative targets before `subprocess.run()`.
- Production caller: `backend/gen2/workflow_adapters.py::_adapt_coding_agent()` takes `test_args = list(inputs.get("test_args") or [])` from workflow action inputs and passes them to `CodingAgentService.run_from_goal()`. `run_from_goal()` forwards the same list into investigate/build test execution. This confirms a real workflow-input → test-runner path rather than a dead helper.
- Impact: for a suite such as pytest, a target like `../outside_test.py` can be handed to a subprocess with cwd set to the isolated worktree, defeating the intended filesystem execution boundary even though shell execution itself is disabled.
- Characterization: `backend/tests/test_build_agent_test_target_boundary.py` has an intentionally `expectedFailure` case requiring a parent-relative pytest target to raise before `subprocess.run()` is called, plus a mocked positive control showing a legitimate `tests/test_ok.py` target remains allowed.
- Characterization commit: `736d0e4380db1ecc476decae11a8d2a8fe03e8cc`.
- Safe remediation direction: parse/validate path-like runner arguments against `work_root` before execution while preserving legitimate in-worktree test paths and explicitly supported non-path runner options. Do not solve this by banning all slashes or all flags indiscriminately.
- Why not fixed here: test-runner argument semantics differ across unittest/pytest/npm and live in the same multi-responsibility build owner as F-061. A partial slash-based filter could break legitimate test selection or miss flag-based path arguments.

## Validation honesty

- Performed: source inspection, production caller/path analysis, commit/ref checks, and focused characterization-test source additions.
- Not performed: execution of the new characterization tests, canonical/full repository test suite, Windows-host validation, live model/provider calls, GitHub Actions validation, or external network/subprocess validation.
- The `expectedFailure` annotations record known-open behavior; they are not evidence that the tests were executed.
- The positive-control subprocess in `test_build_agent_test_target_boundary.py` is mocked in source; this session did not execute that test.
- `main` was not modified. All writes remain on `astra-audit-2026-09-13` / draft PR #96.
- No Category C functionality was proposed or implemented. Issue #95 remains unchanged.

## Next exact continuation point

Continue the process/isolation audit at `backend/build_agent.py::run_tests()` and its callers. Determine whether inherited environment variables, runner flags, or other non-target arguments can bypass existing policy/isolation assumptions before proposing a coherent test-runner contract. Then continue through build apply/restore path validation and coding-agent repair context reads. Keep F-060/F-061/F-062/F-063 open until their shared boundary semantics can be repaired without unsafe full-owner reconstruction.
