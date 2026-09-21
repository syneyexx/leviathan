# A13 Reliable Resume Experiment

- Experiment: `reliable_resume_a13`
- Dataset / grader: `resume_tasks_v1` / `resume_grader_v1`
- Quality layer: **software** (software-test measurements)
- Config hash: `bbf2e6a6b8071bc9`
- Git: `c536917e9df259119674df8b29df3b964531cc01`
- Exactly-once claimed: **no**

## Aggregate

| Arm | n | correct_resume | lost_work | duplicate_effects | false_success | mean_effects | mean_overhead_ms |
|---|---:|---:|---:|---:|---:|---:|---:|
| recovery_on | 12 | 1.00 | 0.00 | 0.00 | 0.00 | 2.50 | 1.85 |
| recovery_off | 12 | 0.25 | 0.25 | 0.75 | 0.25 | 4.00 | 0.36 |

## Benefit deltas

- `correct_resume_delta`: 0.7500
- `duplicate_effects_delta`: -0.7500
- `lost_work_delta`: -0.2500
- `false_success_delta`: -0.2500
- `overhead_ms_delta`: 1.4956

## Honest analysis

- Recovery_on incurred higher mean overhead_ms (expected bookkeeping cost).
- Recovery_off showed higher false-success risk on injected tool failures.

## Limits

- software-labeled measurements only when LM Studio is absent
- does not claim universal exactly-once for external tools
- injected failures are synthetic process/tool stops
- Windows host GUI resume path UNVERIFIED_ON_HOST in this harness

Raw rows: 24

