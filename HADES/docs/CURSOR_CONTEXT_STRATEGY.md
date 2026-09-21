# Cursor context strategy for HADES

The objective is to spend model context on the subsystem being changed, not on dependencies, runtime databases or unrelated source.

## Current Cursor source of truth

Keep Cursor-specific context deliberately small:
- `docs/CURSOR_PAGE_INVENTORY.md` — current page/router ownership map.
- `.cursor/rules/pages/` — page-scoped minimal read-sets.
- `.cursor/rules/00-hades-core.mdc` through `60-tests-release.mdc` — short cross-cutting engineering/safety rules.
- `.cursorignore` — excludes generated/runtime/historical noise from normal context.

There is intentionally no separate onboarding prompt library or Cursor verification package anymore. The user gives the task; Cursor should use the matching scoped context.

## Default behavior

1. Read `CURRENT_STATUS.md` and the codebase map only for broad work.
2. For a page-specific task, use `docs/CURSOR_PAGE_INVENTORY.md`; the matching scoped rule under `.cursor/rules/pages/` supplies the minimal page boundary automatically.
3. For product direction, use `docs/DECISIONS.md` (D018 Chat-primary) and `docs/CURRENT_STATUS.md`. Archived Gen2 planning under `docs/archive/planning/` is historical only.
4. Use the minimal read-set for the subsystem.
5. Search within large hotspot files for functions/classes before loading broad ranges.
6. Open direct dependencies only when an interface requires it.
7. Use a fresh Agent chat when switching to another subsystem.
8. End each session with a compact handoff update.

## Avoid

- `@codebase`/“read the entire repository” as a default prompt.
- Attaching `backend/data`, installed plugin source, `node_modules`, `.venv`, build output or logs to normal coding chats.
- Historical `docs/archive/` or `artifacts/audit/` material unless the task explicitly requires history.
- Huge always-on project rules.
- Repeating architecture/specification text in every prompt.
- Keeping one enormous Agent conversation for Plugin Runtime, Research, UI and Reasoning work together.

## When a full audit is justified

A repository-wide audit is appropriate for:
- dependency/security audit,
- architecture migration planning,
- release-readiness review,
- dead-code analysis,
- cross-cutting schema/API migration.

Even then, first use the codebase map and dependency graph; do not dump every file into one prompt.
