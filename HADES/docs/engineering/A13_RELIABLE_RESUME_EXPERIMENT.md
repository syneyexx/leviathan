# A13 — Reliable resume experiment

## Goal

Controlled A/B of recovery features (SideEffectLedger reconcile + resume plan)
versus naive full restart under injected process stops / tool failures.

## Honesty

- Quality layer: **software** (labeled software-test measurements)
- **No universal exactly-once claim** for external tools
- LM Studio not required for the software arm; live model resume remains host-dependent

## Harness

```bash
cd backend && python -m evals.resume_experiment --runs 3
```

Outputs:

- `artifacts/resume_experiment/report.json` (+ `.md`)
- `docs/evidence/resume_experiment/report.json` (+ `.md`)

### Arms

| Arm | Behavior |
|---|---|
| `recovery_on` | Durable intent + crash reconcile + resume plan; skip re-exec when evidence exists |
| `recovery_off` | Discard checkpoints; full restart (duplicate / lost-work / false-success risk) |

### Injected moments

`after_intent`, `after_effect_before_checkpoint`, `during_tool`, `after_partial_steps`

### Independent checks

correct resume, lost work, duplicate effects, false success, overhead_ms

## Verify

```bash
cd backend && python -m unittest tests.test_audit_a13_resume_experiment -v
```

## Host gaps

- Multi-process Work Runtime integration under Windows Job Objects: **UNVERIFIED_ON_HOST**
- Live LM-backed task resume: **UNMEASURED** without LM Studio
