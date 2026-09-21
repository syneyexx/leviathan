# A11 — Telemetry, evidence, reproducibility

## Goal

Stable correlation across HADES surfaces, honest token accounting, and
reproducible exports that keep failures/aborts/infra visible. Builds on
Flight Recorder without claiming live replay when only inspection occurred.

## Implementation

| Piece | Path |
|---|---|
| Correlation + token honesty + export | `backend/gen2/correlation_telemetry.py` |
| Service wrappers | `Gen2Services.record_correlated` / `export_reproducible_bundle` / `human_run_summary` / `register_experiment_relation` |
| HTTP | `POST /api/gen2/flight/events` (correlation default), `GET .../summary`, `POST .../export`, `POST /api/gen2/flight/experiments/relate`, `GET /api/gen2/flight/modes` |

### Correlation surfaces

`correlation_id` links optional: conversation, task, mission, workflow, run, step,
toolcall, approval, plan_revision, artifact_version. Parent correlation supported
for comparable experiments.

### Token honesty

`normalize_token_usage` labels each record as:

- **exact** — provider usage present
- **estimate** — explicit estimate flag / heuristic
- **missing** — no fabricated fixed totals

### Inspect vs replay

- **Inspect / export** — stored events + tool fixtures; `inspection_not_replay`
- **Comparative replay** — may newly execute model calls; tools reuse recording or block side effects; parent relation stored

## Verify

```bash
cd backend && python -m unittest tests.test_audit_a11_telemetry -v
```

## Host gaps

- Live LM Studio token streams: **UNMEASURED** on Cloud Agent without LM
- Browser Mission Control timeline UX: unverified on Windows host in this pass
