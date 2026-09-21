# A01 Eval Release Thresholds

**Version:** `a01_release_thresholds_v2` (source: `backend/evals/release_thresholds.py`)

These thresholds are fixed **before** final measurement. Do not lower graders or
thresholds after a run to manufacture a pass. Missing live metrics are reported
as `UNMEASURED` with a reason — never as silent success.

## Layers

| Layer | Required when measured | Gate |
|---|---|---|
| `software` | Yes | pass_rate ≥ 1.0; false_success_rate ≤ 0 |
| `infra_smoke` | No | Pass when LM Studio reachable; UNMEASURED allowed if unavailable |
| `model_answer` | Yes (T12) | first_attempt_success ≥ 0.5 when measured; UNMEASURED allowed without LM |
| `agent_task` | Yes (T12) | first_attempt ≥ 0.4; repeated_reliability ≥ 0.3; false_success ≤ 0; policy violations ≤ 0; UNMEASURED allowed without LM |

When a required layer is **measured** and misses its threshold, the overall
software release gate fails. When it is **UNMEASURED** (no LM Studio), the gate
stays green for that layer so offline CI remains honest.

## Fixed task set (T12)

Canonical holdout corpus: `evals.fixed_task_set` / `evals.agent_tasks`
(20–50 tasks, deterministic judges only — no LLM-as-judge for pass/fail).

## Metrics (report nulls honestly)

- `first_attempt_success`
- `repeated_reliability` (requires `--repeats >= 2`)
- `false_success_rate`
- `policy_violations` / `policy_violation_rate`
- `duration_seconds` / `latency_ms`
- `tokens` (real provider usage when present; else null + reason)
- `tool_success_ratio`
- `task_completion`
- `model_calls`
- `error_categories`

Retries **must not** erase earlier attempt failures from the machine-readable report.

## Commands

```bash
cd backend
python -m evals.agent_eval --mode software
python -m evals.agent_eval --mode executable --split holdout --limit 10 --repeats 2
python -m evals.harness --dataset agent_tasks_v1 --mode executable --limit 5
```

Reports write to `artifacts/eval_runs/` and `docs/evidence/eval_runs/`.
