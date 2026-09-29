# LEVIATHAN Institutional Hardening — Final Evidence Report

## SUMMARY

Waves 0–25 executed on branch `cursor/institutional-hardening-e3ae` (PR #227).
Backend full suite green. Frontend and launcher gates pass. **Strict trading verification PASS**
(`strict_all_required_pass=true`) on a clean tree. Live trading remains **BLOCKED**.

## BASELINE SHA

- Program-authored main (at authoring): `e0a5999ac6e12e617ed4392042d51a5cfec372b8`
- Actual fetched baseline main: `35174d88edcccd87e7f40d34651ae2cc9bcc7abb` (moved via #221)
- Main moved since authorship: **yes**

## FINAL SHA

Strict trading verified on clean tree: `3104cfb4815f7d5404393dcbe8621f4d89928bae`

Evidence commit tip: `c73d95ea1ea03dd9765cfefc273877d6b169c5eb`

## FILES CHANGED

~70 files vs `origin/main`. Owners extended (not replaced): Worker Fabric, MarketSim learning/RiskGuard,
TradingContextFabric, Fincept bridge, ingestion progress, research verifier, schedules, observability,
Brain Graph UX, docs/governance.

**Untouched:** `editor/`, `Data/HADES/`

## MIGRATIONS

No new SQLite domain databases. CONTROL / KNOWLEDGE / MARKET preserved. No private agent DBs.

## ARCHITECTURAL DECISIONS

1. Typed worker context; production validates full base; handlers declare requirements.
2. Pressure governor with available-MB as authoritative RAM signal.
3. Closed learning loop via bounded ranked prior lessons (negatives first-class).
4. One TradingContextFabric — not a second Brain.
5. Fincept evidence bridge — never execution authority.
6. Weighted ingestion progress; measurable percent when possible.
7. Deterministic paper RiskGuard; LLMs propose only.
8. Trading verifier executes `test_node_ids` (documentary/file_exists alone ≠ PASS).

## BUGS FOUND / FIXED

Pressure double-count at 4 GiB free; Mock-safe queue saturation; WORKER_CONTEXT_INVALID on partial
test fixtures; offline preflight/classification mismatch; soak import; claim-graph SUPPORTS;
strict gates left UNMEASURED despite existing pytest node ids.

## AUTONOMOUS TRADING STATUS

Learning loop closed. Strategy grammar + epistemic memory present. JobRuntime contracts restored.

## PAPER TRADING STATUS

Paper path + PIT + RiskGuard + scheduler + soak covered. Strict required gates **PASS**.
Live-provider loop: credentials-dependent (**UNMEASURED** without secrets).

## LIVE TRADING STATUS

**BLOCKED**.

## KNOWLEDGE / FINCEPT / LEARNING / INGESTION / RESEARCH / BRAIN UI

Implemented and tested per waves 2–15; see backend doc §31 runbook and module owners.

## RESOURCE PROFILE

16 GB RAM + 16/6 GB VRAM pressure states; DB writer never killed mid-commit.

## TEST RESULTS

| Gate | Result |
|------|--------|
| Backend pytest | 3038 passed / 0 failed |
| Frontend typecheck/lint/test/build | PASS |
| Launcher typecheck/test/build | PASS |
| Security rounds 8–10 | 37 passed |
| Release gate pytest | 22 passed |
| Trading **strict** `--run-tests` | **PASS** (93 PASS; G16 FEATURE_GATED; G47 NOT_TESTED_IN_CI) |
| Frontier F0 | PASS |
| Frontier R01–R30 | NOT_STARTED (honest) |

## RELEASE GATES

CI + CODEOWNERS + PR checklist + operator branch-protection doc.
GitHub server-side protection **not claimed applied**.

## KNOWN LIMITATIONS

- Frontier Reasoning R01–R30 separate unfinished program
- G16 sandbox FEATURE_GATED (DSL path supported)
- G47 Windows paths not tested in this Linux CI
- Live market credentials / Fincept install optional externals

## OPERATOR RUNBOOK

`Data/docs/Leviathan_system_backend.md` §31 — autonomous paper money.

## ROLLBACK PLAN

Revert PR #227 to `35174d88`. Do not touch `editor/` / `Data/HADES/`.

## TRUTHFUL FINAL VERDICT

**READY_FOR_AUTONOMOUS_PAPER_WITH_EXTERNAL_GAPS**

Supported by executed CI + strict trading evidence.
Not claimed: live trading, Frontier R01–R30 completion, or live-external certification without credentials.
