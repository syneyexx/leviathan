# A10 — Product / recovery tests

## Goal

Behavior tests for reproduced audit defects (isolation, artifacts, metrics,
stop_and_ask, replan) plus a compact product API module with isolated DB and a
labeled `software-test` model stub. Crash boundaries use persisted
`SideEffectLedger` across separate processes.

## Modules

| Test | Focus |
|---|---|
| `backend/tests/test_audit_a02_a03_a04.py` | Isolation / artifacts / metrics |
| `backend/tests/test_audit_a07_replan.py` | Contentful replan waves |
| `backend/tests/test_audit_a09_policy_paths.py` | G11/G8 + stop_and_ask payload |
| `backend/tests/test_audit_a10_product_recovery.py` | Product API, failure modes, leases, crash/restart, mutation proof |

## Mutation proof

`test_mutation_proof_idempotency_link` temporarily breaks `make_idempotency_key`
to show duplicate effects, then restores the original symbol (no mutation left
in tree).

## Verify

```bash
cd backend && python -m unittest tests.test_audit_a10_product_recovery -v
```

## Host gaps

- Secured FS isolation tests may `skip` when userns unavailable
- Real browser (Puppeteer) E2E: optional host probe, not required for green CI
- Live LM Studio paths: software-test stub only on Cloud Agent
