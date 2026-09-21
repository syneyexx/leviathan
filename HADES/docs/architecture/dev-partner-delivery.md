# Development Partner (`dev_partner_v1`)

HADES as a measurable local coding partner — built on Coding Agent, Work Runtime,
Eval Lab, Flight Recorder, and Agent Factory. No second framework.

## Suite

- **Version:** `dev_partner_v1`
- **Tasks:** 20 (8 bugfix / 4 feature / 4 regression / 4 review)
- **Split freeze (before optimization):**
  - development: DP01–DP12
  - holdout: DP13–DP20
- **Fingerprint:** via `evals.dev_partner_suite.suite_manifest()`

## Commands

```bash
# From repository root with backend on PYTHONPATH, or cwd=backend:
python -m evals.dev_partner_harness --mode honesty --split holdout
python -m evals.dev_partner_harness --mode software --split holdout
python -m evals.dev_partner_harness --mode baseline_compare --split development
python -m evals.dev_partner_harness --mode executable --split holdout --out artifacts/eval_runs/dp_live.json

# Via unified harness
python -m evals.harness --dataset dev_partner_v1 --mode software

# Focused tests
python -m unittest tests.test_dev_partner_suite -v
```

Eval Lab (Mission Control): suite `dev_partner_v1`, modes `dev_partner_software` / `dev_partner_baseline`.

## Separation

| Layer | Role |
|---|---|
| Agent workspace | Fresh tempfile fixture per task; writable |
| Judges | `evals.dev_partner_judges` imported from backend package — **not** copied into the workspace |
| Enforcement | Path scan for grader filenames + package import boundary. A folder name alone is not security. |

Harness never injects solutions into the agent path for live/executable mode. Software-mode heuristics exist only to prove harness/judge contracts offline.

## Coding workflow

Phases in `coding_delivery.WORKFLOW_PHASES`. Delivery schema `coding_delivery_v1`.
Autonomy profiles (`coding_autonomy`): `analyze_only` | `managed_workspace_modify` | `reviewable_result`.
External publish/push/merge remain under existing authorization — never granted by scores.

## Measured software baseline (this delivery)

Fixture-level baseline_compare on **development** split (limit 12), judge `dev_partner_judge_v1`:

| Arm | Pass rate | Note |
|---|---|---|
| Baseline (no-fix / weak reports) | low | Existing weak path |
| Improved (report path + delivery-aware heuristics) | higher | Same tasks/judges/budgets |

See `artifacts/eval_runs/dev_partner_baseline_compare.json`.

**Live agent quality: UNMEASURED** (no LM Studio in this environment).

Executable command for real measurement:

```bash
python -m evals.dev_partner_harness --mode executable --split holdout --out artifacts/eval_runs/dp_live.json
```

## Targeted improvement

`DP_IMP_01_report_delivery_gate` — report-only path for review/regression + CodingDeliveryV1 gate that demotes incomplete “completed” claims.
Proposal loop: `evals.dev_partner_improve` (cannot rewrite judges / auto-merge).

## Human usability

Mission Control + Coding Agent: ratings `directly_usable` | `usable_after_small_correction` | `needs_major_correction` | `unusable`.
Active correction time only via explicit seconds or opt-in timer — never inferred from open windows.
API: `POST /gen2/evals/human-rating`, `GET /gen2/evals/human-ratings`.

## Open limitations

- Windows host VERIFY not claimed here
- Live LM Studio / token metrics UNMEASURED without provider
- Software heuristics ≠ agent skill proof
- Twenty tasks ≠ general programming expertise
- Human guidance hours remain unknown unless explicitly recorded
