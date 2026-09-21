# HADES portfolio report — audit remediation A01–A14

Compact reviewer packet for branch `cursor/audit-remediation-a01-a14-7ab4`.

## Fingerprint

| Field | Value |
|---|---|
| Base (audit start) | `6c4b7112af7d7dc45741af8c2681d5e6f4586739` |
| Report tip | `c394c2e` (A14 docs/demos; recompute with `git rev-parse HEAD`) |
| Diff vs base (at A12) | 56 files, +11415 / −412 (grows with A14 docs/demos) |
| Platform of evidence | Linux Cloud Agent; Windows = first-class target |

Recompute:

```bash
git rev-parse HEAD
git diff --shortstat 6c4b711...HEAD
```

## What was actually completed on this branch

| ID | Outcome (bounded) | Evidence |
|---|---|---|
| A01 | Production-route agent eval harness; software layer verified; live model **UNMEASURED** without LM Studio | `backend/evals/agent_eval.py`, `docs/evidence/eval_runs/`, `tests.test_agent_eval_a01` |
| A02–A04 | Terminal FS isolation (fail-closed secured), ArtifactService bytes gate, honest metrics/smoke routing | `execution_isolation.py`, `artifacts.py`, `tests.test_audit_a02_a03_a04` |
| A06 | Workflows wired to real coding/research adapters; product sandbox refused | `workflow_adapters.py`, `tests.test_audit_a06_workflows` |
| A07 | Contentful mission replan with wave diffs | `mission_control.py`, `tests.test_audit_a07_replan` |
| A08 | Local embeddings + chat context wiring; lexical fallback honest | `embeddings.py`, `tests.test_audit_a08_embeddings_context` |
| A09 | G11/G8 on plugin/tool paths; real stop_and_ask wait | `policy_enforcement.py`, `tests.test_audit_a09_policy_paths` |
| A12 | Lifecycle ownership contracts; lint≡tsc honesty; cheap baseline | `run_lifecycle.py`, `tests.test_audit_a12_lifecycle`, `artifacts/baselines/` |
| A14 | English portfolio README, 3 demos, this report, changelog | `README.md`, `docs/demos/`, `docs/archive/planning/CHANGELOG_AUDIT_REMEDIATION.md` |

A05 / A10 / A11 / A13 may land on the same branch from parallel work — treat their AUDIT_REMEDIATION rows as authoritative; do not invent VERIFIED here without evidence.

## Test evidence (this agent)

```bash
cd backend && python3 -m unittest \
  tests.test_agent_eval_a01 \
  tests.test_audit_a02_a03_a04 \
  tests.test_audit_a07_replan \
  tests.test_audit_a09_policy_paths \
  tests.test_audit_a12_lifecycle -q
# → OK (focused suite)

python3 tools/run_portfolio_demos.py
# → 3/3 demos passed
```

Full `verify_hades.py` / Windows CI matrix: run on a prepared host; remote CI billing may be `BLOCKED_EXTERNAL`.

## Benchmark / baseline

| Measurement | Result | Bound |
|---|---|---|
| A12 import baseline | `artifacts/baselines/a12_runtime_baseline.json` | Import/call latency only — not browser/load |
| A01 software eval | `docs/evidence/eval_runs/a01_software.*` | Wiring/honesty — not live agent quality |
| A01 executable sample | `docs/evidence/eval_runs/a01_executable_sample.*` | Host without LM Studio → UNMEASURED layers |

## Demos

See `docs/demos/README.md`.

```bash
python3 tools/run_portfolio_demos.py
```

## Known limits / unproven claims

- Live LM Studio agent quality and embedding quality on production models
- Windows Job Object / AppContainer **operational** PASS
- Full GUI product-execute path for Workflows on Windows host
- Exact-once side effects for arbitrary external tools
- Multi-host distributed compute beyond local queue gate
- Monster checklist “161/161” = IDs ticked with mixed verified/partial/deferred/UNVERIFIED — **not** operational 100%
- Remote GitHub Actions green may be billing-blocked (`BLOCKED_EXTERNAL`)

## Status vocabulary (do not collapse)

| Axis | Meaning |
|---|---|
| Implementation | Code present for the contract |
| Integration | Wired into production routes/UI |
| Operational availability | Works on a real host with required hardware/providers |
| Quality | Measured model/agent performance vs thresholds |

Never report “100% complete” by counting deferred or `UNVERIFIED_ON_HOST` as operational PASS.

## AI assistance

This remediation packet was produced with Cursor Cloud Agent assistance. Descriptions above are limited to repository evidence. No fabricated personal experience, user metrics, or Anthropic-scale authorship claims.
