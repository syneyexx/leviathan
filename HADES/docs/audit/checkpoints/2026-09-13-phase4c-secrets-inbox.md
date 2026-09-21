# HADES ASTRA Audit — Phase 4C Secrets / Inbox Checkpoint

Date: 2026-09-13
Repository: `syneyexx/HADES`
Baseline main: `dbe0ed51f46e3c5908a0c5d9edca084bdfaeea25`
Audit branch: `astra-audit-2026-09-13`
Draft PR: #96

This checkpoint extends the Phase-4 and Phase-4B persistence/security checkpoints.

## F-2026-09-13-016 — Workspace archive redaction misses secret history and scoped overrides

- Severity: HIGH / secret disclosure in backups.
- Status: OPEN / CHARACTERIZED.
- Existing behavior: when `include_secrets=false`, workspace backup copies the SQLite database and masks known keys in `app_settings` / `settings`.
- Confirmed gap: `_sqlite_backup_bytes()` does not redact `setting_overrides.value` or `setting_history.old_value/new_value` for those same secret keys.
- Runtime relevance: ControlService stores scoped overrides in `setting_overrides` and records old/new setting values in `setting_history`; those rows can therefore retain credential material even when the archive manifest claims database settings were redacted.
- Additional honesty gap: SQLite errors during the current redaction block are swallowed; a backup may continue even if masking could not be completed.
- Regression characterization: `backend/tests/test_workspace_backup_secret_history.py` creates an isolated SQLite fixture and requires current, scoped-override, and history values to contain no secret material in the redacted copy. Currently `expectedFailure`.
- Characterization commit: `dc86f803831169e9698d3a3df3168a3f0d73ab17`.
- Required remediation: redact current settings, scoped overrides, and history consistently using one authoritative secret-key definition; redaction failure must fail the secret-excluding archive rather than silently continue.

## F-2026-09-13-038 — Control config export leaks TTS/STT API keys when secrets are excluded

- Severity: HIGH / direct secret export boundary.
- Status: OPEN / CHARACTERIZED.
- Root cause: `control.service.SECRET_STORAGE_KEYS` contains only `lm_studio_api_key`, while the control registry exposes `tts_api_key` and `stt_api_key` as critical API-key settings.
- Impact: `export_config(include_secrets=False)` masks LM Studio but can serialize configured TTS/STT API key values into the supposedly redacted export.
- Existing test gap: the prior `test_export_redacts_secrets` asserted only `lm_studio_api_key`.
- Regression characterization: `backend/tests/test_control_export_secret_redaction.py` sets synthetic LM/TTS/STT key values and requires all three to be masked and absent from the rendered export. Currently `expectedFailure`.
- Characterization commit: `7c73d0ef527d02764a738f8fcbb864b1b655b040`.
- Required remediation: centralize core secret-setting classification and use it for control export, API views, backup current values, overrides, and history. Avoid independent drifting hard-coded sets.

## F-2026-09-13-039 — Archived inbox item could be resurrected by mark-read

- Severity: MEDIUM / durable inbox lifecycle correctness.
- Status: FIXED / FULL-SUITE UNVERIFIED.
- Root cause: `InboxService.mark_read()` unconditionally wrote `status='read'`; `mark_refs_read()` already protected archived rows. Calling mark-read on an archived item therefore revived archived history.
- Fix: `mark_read()` now performs a single conditional SQLite update with `WHERE status!='archived'`, then reads the durable row back. This avoids a read-then-write race with concurrent archive.
- Production commit: `65096a147e58a87c099956bdc2a4485fa42268c6`.
- Regression coverage: `backend/tests/test_inbox_archive_terminal.py`; promoted to permanent gate in `1f152eab3e74617337ca48a8936f50b4936e40be`.
- Diff verification: production commit changes only `InboxService.mark_read()`.

## Audited with no new finding

- Work Runtime completion helper accepts a missing `passed` field when `phase='verified'`, but the only production Work-checkpoint writer found for that phase explicitly persists `passed=True`; no current runtime path producing a missing boolean was established.
- Conversation deletion on shared production SQLite is protected by a fail-closed `BEFORE DELETE` trigger that removes searchable conversation chunks/FTS and marks the knowledge source forgotten in the same transaction. Regression tests also prove trigger failure rolls back the primary conversation deletion.
- Browser preview screenshot/user-flow paths remain fail-honest: successful plugin invocation alone is insufficient; missing screenshot files and failed flow steps keep `ok=False`.
- Voice model installation verifies non-empty assets and final provider doctor readiness before returning overall `ok=True`.

## Validation honesty

- Remote `main` remained `dbe0ed51f46e3c5908a0c5d9edca084bdfaeea25` at continuation start.
- No local HADES checkout is mounted; canonical backend/frontend/native/Windows/full gates were not run.
- F-016 and F-038 are characterization tests and remain OPEN.
- F-039 has production code + permanent regression coverage but remains FULL-SUITE UNVERIFIED.
- No CI wait/poll loop was used.

## APPROVAL?

No Category C/new speculative functionality was proposed or implemented. Issue #95 remains unchanged.
