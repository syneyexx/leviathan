# HADES ASTRA Audit — Phase 4 Security/Persistence Checkpoint

Date: 2026-09-13
Repository: `syneyexx/HADES`
Baseline main: `dbe0ed51f46e3c5908a0c5d9edca084bdfaeea25`
Audit branch: `astra-audit-2026-09-13`
Draft PR: #96

This checkpoint extends `docs/audit/ASTRA_AUDIT_LEDGER.md`. The master ledger currently ends at F-020 and needs a later safe reconciliation. Do not infer that omitted findings were resolved.

## Numbering continuity

The audit branch already contained `backend/tests/test_shared_migration_namespace.py` referring to F-2026-09-13-023, while no durable F-021/F-022 record was found in the master ledger, PR conversation, or current PR patch search. To avoid silently reusing prior-analysis identifiers, F-021 and F-022 remain reserved/unreconstructed. F-023 is retained for the migration namespace defect already referenced by the branch test.

## F-2026-09-13-023 — Shared integer migration namespace can skip Gen2 migrations

- Severity: HIGH / upgrade and persistence compatibility.
- Status: OPEN / CHARACTERIZED.
- Root cause: `PlatformDatabase`, `Gen2Store`, and MCP schema code share `schema_migrations(version INTEGER PRIMARY KEY)` without an owner/subsystem dimension. Platform currently writes versions 8, 10 and 11; Gen2 independently uses 8, 10 and 11 for different schema changes.
- Fresh-current nuance: `main.py` constructs `Gen2Store(config.database_path)` early, so a brand-new current install can create Gen2 schema first.
- Upgrade risk: if Platform migrations 8/10/11 are already recorded before Gen2 first runs (legacy database, alternate initialization order, tests/tools, or future migration reordering), Gen2 trusts the version marker and skips its own unrelated migration.
- Consequences proven statically:
  - Gen2 v8 may skip `gen2_mission_executions` plus `gen2_missions.execution_id` / `executions_json`.
  - Gen2 v10 may skip `gen2_workflows`, revisions, and runs.
  - Gen2 v11 may skip `gen2_jit_grants` and `gen2_plugin_integrity`.
- Regression characterization: `backend/tests/test_shared_migration_namespace.py` contains three independent `expectedFailure` tests for collisions 8, 10 and 11. Remove `expectedFailure` only after production migration ownership is repaired.
- Required remediation: introduce subsystem-owned migration identity or verify per-migration schema invariants rather than trusting a shared bare integer. Preserve existing databases; do not renumber blindly or delete existing migration history.
- Connector constraint: direct imports of `Gen2Store` are widespread, so an export-only wrapper is not a complete repair. The available GitHub write interface only replaces full files; do not rewrite the large stateful store merely to force a small fix.

## F-2026-09-13-024 — Local FastAPI mutation surface lacks request-origin / Host enforcement

- Severity: HIGH / local-browser trust boundary.
- Status: OPEN / CHARACTERIZED.
- Evidence: HADES configures Starlette `CORSMiddleware` with allowed frontend origins, but no separate trusted Host/origin enforcement was found around route execution.
- Framework behavior: Starlette CORS preflight can reject disallowed cross-origin preflights, but simple requests are passed through to the application and CORS controls response readability/headers rather than preventing the side effect.
- Concrete HADES mutation: `POST /api/settings/backup` has no request body requirement and creates a local SQLite backup. A hostile browser origin can issue a simple POST even though it cannot read the response. Other bodyless/form/multipart mutation routes require the same review.
- DNS-rebinding boundary: no trusted Host allowlist was found; requests without an Origin header also need a local Host check.
- Regression characterization: `backend/tests/test_local_api_origin_security.py` contains isolated temp-database `expectedFailure` tests for hostile Origin and untrusted Host. No user database is touched.
- Required remediation: reject unsafe browser methods from untrusted origins before route execution and reject untrusted Host values, while preserving legitimate loopback CLI/non-browser clients that send no Origin. Do not rely solely on CORS response headers.

## F-2026-09-13-025 — MCP v16 table rebuild has a non-atomic failure window

- Severity: MEDIUM/HIGH / MCP availability and migration durability.
- Status: OPEN / CHARACTERIZED; permanent data loss not established.
- Root cause: MCP v16 rebuilds `mcp_executions` through `executescript()` (`CREATE temp` -> `INSERT copy` -> `DROP original` -> `ALTER RENAME`) without explicit `BEGIN/COMMIT` in the script.
- Python `sqlite3.executescript()` commits a pending transaction before execution and performs no other implicit transaction control; the surrounding connection rollback therefore does not make this multi-statement rebuild atomic.
- Fault-injection result: denying the `ALTER TABLE ... RENAME` after the DROP leaves `mcp_executions` absent and `mcp_executions_v16` present for that failed attempt.
- Recovery nuance: an equivalent retry experiment showed a second migration run can recreate the empty original, retain the `_v16` rows, then complete the rename, restoring the execution row. Therefore permanent corruption/data loss is not currently proven.
- Runtime blast radius: `ensure_mcp_manager()` catches MCP initialization errors and degrades MCP instead of crashing all HADES.
- Regression characterization: `backend/tests/test_mcp_migration_atomicity.py` fault-injects an ALTER failure and requires the original table/history to remain available after a failed migration; currently marked `expectedFailure`.
- Required remediation: perform the destructive rebuild under a SQLite SAVEPOINT/transaction using individually executed DDL statements, preserving retry recovery from legacy `_v16` remnants, before removing `expectedFailure`.

## F-2026-09-13-026 — Expired execution lease could be renewed before reclaim

- Severity: HIGH / duplicate-work fencing reliability.
- Status: FIXED / FULL-SUITE UNVERIFIED.
- Root cause: `ExecutionLeaseStore.renew()` checked holder, fence token and generation but not `expires_at`. Between TTL expiry and the next `reclaim_stale()` pass, the old worker could extend its already-expired lease.
- Fix: `renew()` now rejects `expires_at <= now` with `ok=false`, `reason="expired"`, preserving normal live renewal and existing takeover/reclaim semantics.
- Regression coverage: `backend/tests/test_run_lease_expiry.py` uses a deterministic patched clock; it covers expired-renew rejection, subsequent CAS takeover, and normal live renewal.
- Production diff verification: commit `4513630d06eb46fe21be9f6dd6a57d9fa531d218` changes only the intended expiry guard in `backend/run_leases.py`.

## F-2026-09-13-027 — Lease persistence could fail silently while operations still reported success

- Severity: HIGH / crash-recovery honesty and fencing durability.
- Status: FIXED / FULL-SUITE UNVERIFIED.
- Root cause: when `execution_leases.json` persistence was configured, `_save()` caught `OSError` and returned silently after callers had already mutated in-memory lease/control/generation state.
- Runtime relevance: application startup configures `execution_leases.json`; silent disk-full/permission failures could therefore leave RAM-only fencing/resume state that disappeared on crash while the operation looked successful.
- Fix: `_save()` now propagates persistence failures and best-effort removes the temporary file. Every mutating lease/control path snapshots the relevant prior in-memory state and restores it before re-raising when persistence fails. This covers generation bump, acquire, release, renew, CAS takeover, pause transitions, stale reclaim and startup control restoration.
- Regression coverage: `backend/tests/test_run_lease_persistence_honesty.py` forces the durable write to fail and requires no retained RAM-only lease. The former `expectedFailure` marker was removed after the production repair, making this a permanent gate.
- Production commit: `f322af588e1382a0b2e7dd01ff6acc392c460599`; regression-gate promotion commit `90c02c73ea26f2c581f92e02cbfa168246ce660c`.

## F-2026-09-13-028 — Claim expiry ignores ISO-8601 timezone offsets

- Severity: MEDIUM / temporal claim correctness.
- Status: OPEN / CHARACTERIZED.
- Root cause: `_is_past_valid_until()` prefers lexical comparison of the first 19 timestamp characters, and `_parse_iso_utc()` intentionally does not parse offset-bearing timestamps. Absolute instants with `+/-HH:MM` can therefore be ordered by wall-clock text rather than UTC time.
- Impact: a claim can remain non-STALE after its absolute expiry or be marked STALE while still valid when imported/provided timestamps carry offsets.
- Input relevance: temporal/claim surfaces accept `valid_until` strings without restricting them to `Z`-only timestamps.
- Regression characterization: `backend/tests/test_claim_timezone_expiry.py` contains positive-offset expired and negative-offset future cases as independent `expectedFailure` tests.
- Required remediation: parse ISO-8601 timestamps into aware UTC datetimes when offsets are present; retain deterministic behavior for existing naive/Z timestamps.

## F-2026-09-13-029 — Coding-job atomic status writer falls back to destructive in-place overwrite

- Severity: HIGH / crash-resume durability.
- Status: OPEN / CHARACTERIZED.
- Root cause: `CodingJobStore._write()` normally writes a unique temp file and retries `os.replace()` on Windows sharing/access races, but after 16 failures it falls back to `target.write_text(body)`. That overwrites the last known-good `status.json` in place despite the method contract calling the write atomic.
- Impact: a crash, disk error or interrupted fallback write can truncate/corrupt the only durable coding-job status and undermine resume/recovery truth.
- Regression characterization: `backend/tests/test_coding_job_atomic_write.py` forces every `os.replace` attempt to fail and then simulates an interrupted direct-target write; the old valid JSON must remain recoverable. The test is currently `expectedFailure`.
- Test hygiene: executor cleanup is registered with `addCleanup` so characterization failure cannot leave a threadpool behind.
- Required remediation: never write the live status target in place as a fallback. If atomic replace cannot complete, preserve the old valid target, clean or retain the temp file intentionally for diagnostics/recovery, and return/raise an explicit persistence failure.

## F-2026-09-13-030 — Schedule occurrence claim and schedule advance were separate transactions

- Severity: HIGH / scheduled-work durability.
- Status: FIXED / FULL-SUITE UNVERIFIED.
- Root cause: `ScheduleService.claim_occurrence()` first committed a unique `task_occurrences` row through `claim_task_occurrence()` and only afterward updated `task_schedules.next_run_at` in a separate transaction. A crash/update error between those operations left the old slot due but permanently duplicate-claimed, so later ticks returned `None` without advancing it.
- Fix: `claim_occurrence()` now inserts the occurrence and advances/disables the schedule within one `PlatformDatabase.connection()` transaction. The schedule update uses an optimistic predicate on `id`, `enabled`, `paused` and the expected `next_run_at`; stale pause/disable/reschedule races therefore roll the claim back.
- Regression coverage: `backend/tests/test_schedule_claim_atomicity.py` installs a SQLite trigger that aborts the schedule advance, verifies the occurrence INSERT rolls back, removes the trigger, then verifies a retry can claim and advance normally. The test is now a permanent gate.
- Production commit: `3a3d06201751dc30a2dafe42612ea9c630ea0c45`; test-gate promotion commit `89b805f7039ca492f4530d0eee4bb968b1ff347b`.

## F-2026-09-13-031 — Naive one-shot `run_at` ignored the declared schedule timezone

- Severity: MEDIUM / schedule correctness.
- Status: FIXED / FULL-SUITE UNVERIFIED.
- Root cause: `_parse_iso()` converts naïve timestamps to UTC immediately, so the subsequent `frequency="once"` branch that intended to apply `timezone` to naïve input was unreachable.
- Impact: e.g. `09:00` with `timezone="Europe/Amsterdam"` ran as 09:00Z rather than 09:00 local wall-clock time.
- Fix: one-shot parsing now parses the raw ISO value directly; explicit offsets/Z remain authoritative, while naïve values receive the declared `ZoneInfo` before conversion to UTC. Persisted `_parse_iso()` behavior for stored UTC timestamps is unchanged.
- Regression coverage: `backend/tests/test_schedule_timezone_semantics.py` requires 2026-09-14 09:00 Europe/Amsterdam to resolve to 07:00Z. Its expected-failure marker was removed after the production fix.
- Production commit: `c8e18e617b22daed4af78df0e17032d526fe20da`; test-gate promotion commit `77103ba54887e92cfabe45456fa5fd147cdcd45a`.

## Existing open high-priority findings carried forward

- F-015 provider secret storage/API/history migration.
- F-016 workspace archive can leak secret setting history despite `include_secrets=false`.
- F-017 plugin command ambient credential inheritance.
- F-018 dependency installer ambient secrets + marketplace policy-gate mismatch.
- F-020 Dataset Brain interrupted-state truth reconciliation. `backend/tests/test_dataset_brain_recovery_truth.py` now reproduces the manifest-compensation failure as an `expectedFailure`: the durable reconciled job becomes `interrupted` while stale manifest status remains `queued` unless read-side reconciliation is fixed.

## Validation honesty

- Remote main was re-resolved during this continuation and remained `dbe0ed51f46e3c5908a0c5d9edca084bdfaeea25` at that check.
- No local HADES checkout is mounted; canonical backend/frontend/native/full Windows gates were not executed.
- Origin/Host, shared-migration, MCP atomicity, claim-timezone, coding-job atomicity and Dataset Brain recovery tests are characterization tests and intentionally `expectedFailure`; they are not fixes.
- F-026, F-027, F-030 and F-031 have production code plus permanent regression coverage, but the canonical suite has not run.
- Production diffs for lease and scheduler fixes were inspected after write; no unrelated file changes were hidden by whole-file replacements.
- SQLite `executescript()` failure/retry behavior was reproduced in an isolated local Python experiment, not against the full HADES suite.
- GitHub Actions remains an external validation blocker until a run actually allocates runners and executes steps; do not wait/poll for CI in the audit loop.

## Next exact slice

1. Continue compact persistence components for durability/false-success defects; prefer real fixes where whole-file replacement remains small and diff-verifiable.
2. Keep F-029 fail-closed: remove only the destructive coding-job in-place fallback when a safe atomic edit path is available.
3. Repair F-023 only through backward-compatible subsystem migration ownership/invariant checks; no blind renumbering.
4. Repair F-024 with trusted loopback Host + unsafe-method Origin policy while preserving legitimate non-browser loopback clients.
5. Repair F-025 under a SAVEPOINT/atomic DDL strategy with legacy interrupted-migration recovery.
6. Return to F-015/F-016 secret-store/history/archive remediation and F-020 Dataset Brain state truth.
7. Reconcile this checkpoint into the master ledger when the full ledger can be edited safely without truncation/whole-file loss.

## APPROVAL?

No Category C/new speculative functionality was proposed or implemented in this checkpoint. Issue #95 remains the approval-only queue and currently requires no user decision.
