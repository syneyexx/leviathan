# HADES ASTRA Audit — Phase 10 Search / Workspace Boundaries

Date: 2026-09-13
Repository: `syneyexx/HADES`
Baseline main: `dbe0ed51f46e3c5908a0c5d9edca084bdfaeea25`
Audit branch: `astra-audit-2026-09-13`
Draft PR: #96

## F-2026-09-13-057 — Project-scoped Global Search could return messages from another project

- Severity: HIGH / project-scope data isolation.
- Status: IMPLEMENTED / TARGETED REGRESSION ADDED / FULL SUITE UNVERIFIED.
- Public contract: `SearchInput.project_id` is an explicit API field and conversations have a persistent `project_id` relation managed by Project Continuity.
- Root cause: `GlobalSearchService.search()` filtered conversation title hits by `project_id` but appended `database.search_messages()` results without checking the parent conversation's project.
- Impact: a search scoped to project A could return message text from a conversation explicitly attached to project B.
- Compatibility preserved: existing behavior allowing unscoped conversations (`project_id=None`) to appear alongside the selected project is retained. Only messages whose parent belongs to another explicit project are excluded.
- Production fix: `backend/global_search.py` builds the allowed conversation-id set once and applies it to message hits when `project_id` is supplied.
- Regression: `backend/tests/test_global_search_project_message_scope.py` uses pure stubs and proves own-project + unscoped messages remain visible while cross-project messages are excluded.
- Production/test commits: `f4531f8a5202490cea262a4f3bb90e288779d839`, `487a9b9a4ad010d541c5b56f56c695b9b4db7369`.
- Diff review: two files only; production +16/-2 and one focused test module.

## F-2026-09-13-058 — Workspace symbol/LSP-light scans could follow file symlinks outside approved root

- Severity: HIGH / file-read boundary.
- Status: IMPLEMENTED / TARGETED REGRESSION ADDED / FULL SUITE UNVERIFIED.
- Root cause: workspace symbol indexing and LSP-light reference scanning used `Path.rglob()`, `is_file()` and `read_text()` without checking where a symlink target resolved. A code-file symlink inside an approved workspace could point outside that root and still be read.
- Production fix:
  - `workspace_symbols._path_within_root()` resolves both root and candidate and fails closed on outside/invalid paths;
  - `_iter_code_files()` and tree-summary scans skip resolved targets outside root;
  - `lsp_light.find_references()` reuses the same boundary helper before reading.
- Normal behavior preserved: ordinary in-root files and links resolving inside the root remain eligible.
- Regression: `backend/tests/test_workspace_symbols_symlink_boundary.py` covers out-of-root file symlink exclusion for both symbol indexing and LSP-light references, plus a regular in-root control. On hosts where symlink creation is unavailable, only the symlink-specific cases are skipped explicitly.
- Production/test commits: `0ad583e5fd0da832fcf234e41b6d1623dcadada0`, `5698fafd7aa2bd52f5fa669d82a547b90a85a88e`, `0398945f8b5470f03c4f894575b8e34cb4c8d47f`, `178f7d28c66c7d32902cfec71527c19e743070ff`.

## F-2026-09-13-059 — Language-server diagnostics accepted paths outside workspace

- Severity: HIGH / file-read and local tooling boundary.
- Status: IMPLEMENTED / TARGETED REGRESSION EXPANDED / FULL SUITE UNVERIFIED.
- Root cause: `language_servers.read_diagnostics(root, paths=...)` formed `root / rel`, checked `is_file()` and passed the same untrusted target list into Pyright without resolved containment validation. Parent-relative, absolute, or in-workspace symlink paths could therefore reference files outside the approved workspace.
- Runtime relevance: Coding Investigate calls `read_diagnostics(self.root, paths=list(self.selected.keys())[:12])`.
- Production remediation:
  - `backend/language_servers.py::_resolve_within_root()` resolves candidate and root and rejects any target that cannot be proven contained;
  - diagnostics canonicalize the safe target set before any `py_compile`, text read, or Pyright invocation;
  - out-of-root symlink targets are rejected while symlinks that resolve inside the workspace remain usable through their canonical target;
  - Jedi seed scans now use the same resolved containment check before HADES reads seed Python files. Jedi-returned external dependency definitions/references were deliberately not reclassified because that navigation contract may legitimately surface dependency locations and no defect was proven there.
- Regression: `backend/tests/test_language_server_diagnostics_path_boundary.py` now requires parent-relative escapes to produce no diagnostic, proves an outside target is not forwarded to `subprocess.run()` even when Pyright is discoverable, covers out-of-root file symlinks where the host supports them, and preserves an in-workspace syntax-error control.
- Characterization commit: `218d20464239b9dfa77fbed93ee491c0088ffe14`.
- Production commit: `efb52ca2040dd67c6adb4ca91489e6782aff4bec`.
- Regression hardening commit: `b33fbbf058895b740dfe699b7ea71dde40cd8ad1`.
- Diff review from the prior Phase-10 checkpoint: exactly two files — `backend/language_servers.py` (+52/-9) and `backend/tests/test_language_server_diagnostics_path_boundary.py` (+53/-1).

## Validation honesty

- Source inspection and exact Git diff review were performed for F-059.
- The F-059 regression source was added/expanded but was **not executed** in this environment.
- The canonical/full test suite was not executed in this environment.
- No Windows-host validation was performed.
- No external network probes, CI polling, provider calls, or user-data scans were performed.
- All writes remain on draft PR #96 / `astra-audit-2026-09-13`; `main` is untouched.
- No Category C functionality was proposed or implemented.

## APPROVAL?

Issue #95 remains unchanged; no approval is required for these defect fixes/characterizations.
