# HADES portfolio demos

Reproducible demos. They exercise real HADES modules without requiring LM Studio
or a running UI. Exit code `0` means the demo assertion passed (or an explicitly
labeled UNAVAILABLE path that the harness treats as non-failure).

## Run all

```bash
python3 tools/run_portfolio_demos.py
```

## Individual demos

| Demo | Script | What it proves |
|---|---|---|
| 01 Successful task | `demo_01_successful_task.py` | Artifact bytes + verified checkpoint → Work completion |
| 02 Blocked action | `demo_02_blocked_action.py` | Policy denies injection-style tool args |
| 03 Recovery | `demo_03_recovery_after_failure.py` | Contentful mission replan |
| 04 False-success defense | `demo_04_false_success_defense.py` | Empty artifact + unverified checkpoint refuse completion |
| 05 Crash/resume effects | `demo_05_crash_resume_effects.py` | Effect ledger ALREADY_COMMITTED after commit |
| 06 Context quality shadow | `demo_06_context_quality.py` | Offline legacy vs compiler coverage proxy (not live model quality) |

## Limits

- Not live LM Studio quality, Windows Job Objects, or full GUI E2E.
- Demo 06 lexical coverage proxy ≠ retrieval quality benchmark.
