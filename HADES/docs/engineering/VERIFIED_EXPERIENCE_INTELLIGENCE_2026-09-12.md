# Verified Experience Intelligence — merge evidence

Date: 2026-09-12
PR: #91
Branch: `feat/verified-experience-intelligence`
Base audited: `8d0506bb990c6c75c3a2a729e4c8de7ac317870d`

## Purpose

This change closes a bounded feedback loop between HADES' existing durable run events and the existing chat context pipeline. It does not add a second memory database, planner, permission system, or completion owner.

The authoritative runtime pipeline remains:

`understand -> retrieve -> plan -> execute/tools -> verify -> answer -> optional memory/knowledge update`

Prior run experience is only additional data-only evidence for later retrieval.

## Implementation

- `backend/gen2/verified_experience.py`
  - reads the existing append-only `gen2_run_events` store
  - supports both Gen2 Flight Recorder and shared Chat/Tasks/Research RunEventBus vocabularies
  - uses one bounded SQLite tail read per retrieval; no N+1 per-run query loop
  - positive history requires final terminal success plus latest verification success
  - latest verification failure converts an otherwise successful terminal claim into failed experience
  - in-progress and successful-but-unverified runs are not promoted
  - recovered/replanned runs use the latest terminal/verification state
  - terminal failures remain recallable as warning evidence
  - stopword-only/generic queries retrieve no experience
  - relevance requires at least one meaningful lexical overlap
  - secret-like values are re-redacted
  - model input/output and hidden reasoning/scratchpad fields are not copied
  - lifecycle admission is deterministic but reliability/freshness quality remains explicitly unmeasured
- `backend/reasoning/chat_context.py`
  - adds the bounded experience source before the existing ContextItem budgeting / optional Context Compiler boundary
  - experience items are `trusted=False`, redactable and data-only
  - experience retrieval is fail-open and cannot fail the established chat path
  - production kill switch: `HADES_VERIFIED_EXPERIENCE_RETRIEVAL=0`
  - no current-task completion, verification or permission decision is delegated to historical experience
- `backend/tests/test_gen2_verified_experience.py`
  - focused regression coverage for verification gating, runtime vocabulary, replan recovery, terminal/verification contradictions, transient tool failures, terminal failures, secret/hidden-reasoning exclusion, relevance gating, generic-query rejection, context budget integration, opt-out, environment kill switch, fail-open behavior and training-record CoT exclusion

## Deliberately unchanged

- no database migration
- no `backend/main.py` rewrite
- no GUI/API/OpenAPI changes
- no model IDs or provider choices hardcoded
- no permission/security policy moved into prompts
- no new training dependency in the product runtime
- no historical experience can mark the current task successful

## Static integration audit

The final diff was reviewed against these existing contracts:

- `Gen2Store.gen2_run_events` schema and append-only ordering
- Flight Recorder canonical event vocabulary and failure taxonomy
- shared RunEventBus vocabulary persisted by `_durable_sink`
- chat `verification_allowed` / `decide_route_completion` semantics
- `ContextItem` trust/budget behavior
- optional Context Compiler fail/fallback behavior
- existing data-vs-system-authority boundary

No unresolved PR review threads or submitted change requests were present at merge-readiness review time.

## Verification status

### GitHub Actions

Actions attempts for PR #91 fail before execution because no runner is assigned. Observed attempts include `34712300557`, `34712547205`, `34712784471`, and `34713359249`; Ubuntu and Windows matrix jobs contained zero workflow steps and no assigned runner. Therefore these checks provide no code/test signal.

The repository owner confirmed the cause is the known GitHub billing problem. This is classified as `BLOCKED_EXTERNAL`, not as a script/test failure and not as a PASS.

### Tests

The focused regression suite is present in `backend/tests/test_gen2_verified_experience.py`, but it was **not executed in GitHub Actions** because the runners never started. No fabricated green result is claimed.

### Static status

`MERGE_READY_STATICALLY_HARDENED_CI_BLOCKED_EXTERNAL`.

The change is considered merge-ready under the repository owner's explicit decision to accept the known external CI/billing condition. When runner execution is restored, the normal repository gates should still be run (`python verify_hades.py`, including the backend suite and frontend gates).

## Rollback

Immediate runtime bypass without data migration:

`HADES_VERIFIED_EXPERIENCE_RETRIEVAL=0`

Reverting PR #91 requires no database cleanup because the feature only reads existing run-event rows.
