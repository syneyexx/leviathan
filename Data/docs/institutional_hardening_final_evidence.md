# LEVIATHAN Institutional Hardening — Final Evidence Report

## SUMMARY

Waves 0–25 executed on branch `cursor/institutional-hardening-e3ae` (PR #227).
Backend full suite is green. Frontend and launcher gates pass. Live trading remains **BLOCKED**.
Autonomous **paper** envelope is implemented, wired, persisted, observable, tested, and documented — with honest external gaps.

## BASELINE SHA

- Program-authored main (at authoring): `e0a5999ac6e12e617ed4392042d51a5cfec372b8`
- Actual fetched baseline main: `35174d88edcccd87e7f40d34651ae2cc9bcc7abb` (moved via #221)
- Main moved since authorship: **yes**

## FINAL SHA

Recorded at report generation tip: see `Data/backend/tests/institutional_hardening_final_evidence_report.json` (`final_sha`).
Strict trading re-run commits may advance the tip; the JSON is authoritative for the evidence SHA.

## FILES CHANGED

~68 files vs `origin/main` (≈8k insertions). Major owners extended (not replaced):

- Worker Fabric: `context.py`, `loop.py`, `admission.py`, maintenance entrypoint
- Trading: `lesson_retrieval.py`, `trading_context.py`, `learning_memory.py`, `strategy_search_grammar.py`, `fincept_bridge.py`, `paper_causality.py`, `risk_guard.py`
- Ingestion progress, research claim/concurrency/verifier, schedules/operating pipeline, observability receipts
- Brain Graph / celestial / clusters frontend
- Docs, CODEOWNERS, PR template, branch-protection operator doc

**Untouched:** `editor/`, `Data/HADES/`

## MIGRATIONS

No new SQLite domain databases. CONTROL / KNOWLEDGE / MARKET ownership preserved.
No `agent.db` / private permanent agent databases.

## ARCHITECTURAL DECISIONS

1. Typed `WorkerExecutionContext` with declared handler requirements; production validates full base at construction; undeclared handlers validate runtime keys (not KeyError/`ctx.get` sprinkles).
2. Pressure governor NORMAL/PRESSURE/CRITICAL with available-MB as authoritative RAM signal (no double-derived used% at exactly 4 GiB free).
3. Closed learning loop: `prior_lessons` retrieved via bounded ranked `lesson_retrieval` (negative experience first-class).
4. One `TradingContextFabric` — not a second Brain.
5. Fincept via evidence bridge — never execution authority; explicit UNAVAILABLE when disabled.
6. Weighted ingestion progress; UNMEASURED only when genuinely impossible.
7. Paper RiskGuard kill/limits deterministic; LLMs propose only.
8. Operating pipeline schedules map to registered MarketSim capabilities (no phantom caps).

## BUGS FOUND

- Wave-12 pressure double-penalized 4 GiB-available fixtures → PRESSURE denials in reservation tests.
- `queue_is_saturated` TypeError on Mock job stores.
- Handler default context required `function_runtime`/`artifact_store` → lease fencing tests failed with `WORKER_CONTEXT_INVALID`.
- Offline brain preflight vs enqueue classification gate mismatch under load.
- Soak test missing `fenced_transition` import; claim-graph casing `supports` vs `SUPPORTS`.

## BUGS FIXED

All of the above; full backend suite: **3038 passed**, 19 skipped, 4 xfailed, **0 failed**.

## AUTONOMOUS TRADING STATUS

Learning loop closed (prior lessons wired). Strategy search grammar + epistemic learning memory present.
Orchestra / AgentFleet / JobRuntime contracts restored. Qualification remains evidence-based.

## PAPER TRADING STATUS

Paper path + PIT causality + RiskGuard envelope + operating scheduler + soak fencing covered by tests.
Real-provider live external loop: **UNMEASURED** without credentials.

## LIVE TRADING STATUS

**BLOCKED** (product contract / LiveTradingGuard). Not claimed.

## KNOWLEDGE ACCESS STATUS

TradingContextFabric assembles bounded provenance-bearing refs from Brain/Knowledge/Memory/StrategyMemory/Evidence/MarketSim.

## FINCEPT STATUS

Lifecycle bridge implemented. Disabled/uninstalled → explicit UNAVAILABLE (no invented analytics).

## LEARNING LOOP STATUS

`run_research_generation_cycle(..., prior_lessons=...)` fed from StrategyMemory retrieval (not `[]`).

## INGESTION STATUS

Streaming/progress model + weighted phases; measurable percent when units known.

## RESEARCH STATUS

Claim relations (SUPPORTS/…), bounded concurrency, independent verifier path extended — ResearchService preserved.

## BRAIN UI STATUS

Hover-only node labels; spacing via bounded neighbor lookup; celestial motion slowed; clusters regression suite added.

## RESOURCE PROFILE

Target: 16 GB RAM + 16/6 GB VRAM. Pressure states + nonessential shed; DB writer never killed mid-commit.
Lazy/scale-to-zero compatible settings documented; browser affinity preserved.

## PERFORMANCE BEFORE/AFTER

Correctness-first; full suite runtime ≈10.3 min on this host after fixes (comparable to baseline).
Ingestion/progress and admission governor reduce pathological RAM / GPU collision risk; detailed MB/s profiling remains operator-measurable on target hardware (not fabricated here).

## TEST RESULTS

| Gate | Result |
|------|--------|
| Backend pytest | 3038 passed / 0 failed |
| Frontend typecheck/lint/test/build | PASS |
| Launcher typecheck/test/build | PASS |
| Security rounds 8–10 | 37 passed |
| Release gate pytest | 22 passed |
| Trading offline (non-strict) | 83 PASS; 10 UNMEASURED; 1 FEATURE_GATED; 1 NOT_TESTED_IN_CI |
| Frontier F0 | PASS |
| Frontier R01–R30 | NOT_STARTED (honest; not fabricated) |

## RELEASE GATES

CI workflow + CODEOWNERS + PR checklist + `github_branch_protection.md` operator instructions.
**GitHub branch protection is NOT claimed applied** (agent cannot write repo admin settings).

## KNOWN EXTERNAL DEPENDENCIES

- Live market provider credentials / network
- Fincept module install/enable
- Optional remote embedding providers (offline path refuses remote)

## KNOWN LIMITATIONS

- Frontier Reasoning R01–R30 remain a separate unfinished program
- Some trading gates stay UNMEASURED until `--run-tests` / live externals
- Live money forever blocked in this envelope

## OPERATOR RUNBOOK

See `Data/docs/Leviathan_system_backend.md` §31 — “How to put LEVIATHAN to work autonomously with paper money”
(settings, providers, paper broker, workers, models, Brain, kill switch, observability, recovery).

## ROLLBACK PLAN

1. Revert PR #227 / reset branch to `35174d88`.
2. Do not restore `editor/` or `Data/HADES/` (untouched).
3. Drop any experimental local `Data/backend/data/` artifacts only — never production MARKET/KNOWLEDGE without backup.

## TRUTHFUL FINAL VERDICT

**READY_FOR_AUTONOMOUS_PAPER_WITH_EXTERNAL_GAPS**

Supported by executed CI evidence for the paper/autonomous envelope.
Not claimed: live trading, Frontier R01–R30 completion, or live-external market certification without credentials.
