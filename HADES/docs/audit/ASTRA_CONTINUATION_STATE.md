# ASTRA Continuation State

Updated: 2026-09-14T14:30Z

| Field | Value |
|---|---|
| Branch | `cursor/astra-continuation-performance-2026-09-14` |
| Base SHA | `7f08b297f3c7b9ad7417abe4339cc6a923fc2429` |
| HEAD | see `git rev-parse HEAD` |
| PR | https://github.com/syneyexx/HADES/pull/101 |
| Host | Linux x86_64 Cloud Agent — **not Windows** |
| Active phase | **H/I** — verify remaining pre-existing failures; docs reconciliation |

## Completed phases

- **A** Baseline + continuation state + perf baseline
- **B** Security/trust: F-024, F-040–047, F-016, F-038, F-060–067, F-015, F-017, F-018 partial
- **C** Durability: F-020, F-023, F-025, F-028, F-029, F-053, F-058, F-064/065
- **D** Performance Foundation (prod frontend, code-split, health TTL, training poll split)
- **E** Plugin Intelligence (observations, budgets, knowledge index, caches)
- **F** Partial deep-pass + suite regression restoration

## Findings disposition (this campaign)

| ID | Status | Evidence |
|---|---|---|
| F-015 | FIXED | `settings_secrets.py` + `test_provider_settings_secrets` PASS; keyring fail-safe keeps plaintext |
| F-016 | FIXED | workspace backup redaction tests PASS |
| F-017 | FIXED | `authorized_plugin_environment` + `test_plugin_credential_authorization` PASS |
| F-018 | PARTIAL | dep env scrub PASS; marketplace gate SOURCE_REVIEWED |
| F-038 | FIXED | `SECRET_STORAGE_KEYS` TTS/STT + export tests PASS |
| F-024 | FIXED | `local_api_trust` middleware + origin tests PASS |
| F-040–047 | FIXED | subprocess ask/block regressions PASS |
| F-012 | FIXED | `scripts/refresh_python_constraints.py` + `requirements.lock.txt` + `--check` |
| F-020/023/025/028/029/053/058/064/065 | FIXED | matching promoted tests PASS |
| F-060–067 | FIXED | `path_boundary` + build/coding tests PASS |
| F-005 | BLOCKED_EXTERNAL_ADMIN | branch protection |
| Windows VERIFY / NVIDIA / LM Studio / VoiceStudio | UNVERIFIED_ON_HOST | Linux agent |

## Performance evidence

See `docs/audit/PERF_BASELINE.md`: entry JS ~644 kB → ~234 kB after interface lazy-load.

## Latest verify_hades.py --python-only

Latest `verify_hades.py --python-only`: **6 fail / 7 error** (down from 24/11 → 12/7 → 6/7). Remaining cluster is largely pre-existing/env:

- GhostTrack missing `phonenumbers` (env)
- MCP sensitive-header / catalog ERRORS
- Dataset brain preflight TemporaryDirectory tuple ERROR
- PaperBot `PlatformDB` import ERROR
- Eval release-gate baseline drift
- Training SFT spacing (`Vraag:antwoord`)
- Chat repetition count 4>3
- MCP cancel isolation / OS resume checkpoint

## Commits (logical)

1–6 earlier security/perf/plugin commits  
7. `fix(security): migrate provider credentials…` / constraints / plugin creds  
8. `fix(test): restore suite regressions from ASTRA continuation`  
9. (pending) redaction + discovery fixture trust + docs reconciliation

## Next exact action

1. Commit remaining redaction/discovery fixture fixes  
2. Update TODOLIST + CURRENT_STATUS + PR body  
3. Re-run `verify_hades.py --python-only` and record honest residual failures  
4. Run npm typecheck/lint/build if time permits  
