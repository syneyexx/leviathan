# Eval report (frontier hardening)

## Software / deterministic

| Suite | Total | Pass rate | Mode |
|---|---|---|---|
| reasoning (`hades-reasoning-core`) | 10 | 1.0 | deterministic_software |
| red_team_v1 | 3 | 1.0 | red_team_software |
| frontier_adversarial_v1 | 109 | 1.0 | software adversarial |

Command:

```bash
cd backend && python -m evals.gen2_release_gate
```

Gate version: `gen2_release_gate_v2_frontier`.

**Honesty:** these suites measure software contracts and defenses. They are
**not** live model quality.

## First-class metric: false success

False-success defenses covered in software:

- Work completion without verified checkpoint
- Empty artifact `verify_ready`
- Coding poll timeout ≠ completion
- Schedule occurrence dispatch ≠ completed
- Policy-blocked tools cannot report success via skip

## Live LM Studio

| Layer | Status on Cloud Agent host |
|---|---|
| infra_smoke | UNAVAILABLE |
| model_answer | UNMEASURED |
| agent_task | UNMEASURED |

Optional host command (when LM Studio present):

```bash
cd backend && python -m evals.agent_eval --mode executable --split holdout --repeats 2
```

## Portfolio demos

```bash
python3 tools/run_portfolio_demos.py
```

Expect 6 demos (success, block, recovery, false-success, crash/resume, context shadow).

## Thresholds

See `docs/engineering/EVAL_RELEASE_THRESHOLDS.md` (A01 layers). Do not lower
thresholds after measurement to manufacture PASS.
