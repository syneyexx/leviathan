# LEVIATHAN A–Z Consolidation — Final Evidence Report

## SUMMARY

A–Z truth-hardening and autonomous paper completion on branch
`cursor/az-consolidation-truth-hardening-035b` (PR #228).

**Strict trading verification PASS** (`strict_all_required_pass=true`) on a clean
tree. Live trading remains **BLOCKED**. Branch protection remains
**OPERATOR_ACTION_REQUIRED**.

## BASELINE

- Original main SHA: `5923e2018ecb63aab25d91a2f170ea3b2f34f768`
- Prior institutional hardening (PR #227) already present on main.
- Forensic Wave 0 mapped remaining gaps against executable code (SHORT bypass,
  UNKNOWN→HEALTHY defaults, in-memory risk log, MEASURED≡PASS, synthetic A3/A4
  acceptance, unwired fabric/Fincept, scholarly false peers, dead resource env
  fields, missing scale-to-zero, CI root gaps).

## VERIFIED SOURCE SHA (strict trading)

- Clean-tree strict trading: `06cecb6d0df3cc2acb522831bd17413923dcb417`
- Branch: `cursor/az-consolidation-truth-hardening-035b`
- Evidence tip may be this commit or a subsequent evidence-only commit; trading
  report `source_commit` records the verified clean SHA above.

## ARCHITECTURE (no duplicate systems)

| Domain | Canonical owner | Change |
|--------|-----------------|--------|
| Risk | `RiskGuard` | HealthState fail-closed; SHORT through guard; durable receipts |
| Paper evidence | `autonomous_paper_loop` | MEASURED≠PASS; no synthetic sealed/acceptance |
| Operating profile | `operating_profiles` | `AUTONOMOUS_PAPER_REAL_DATA` (config, not engine) |
| Context | `TradingContextFabric` | Wired into orchestra + research_cycle |
| Fincept | `FinceptEvidenceBridge` + ModuleManager | Evidence-only; UNKNOWN≠AVAILABLE |
| Learning | StrategyMemory / lesson_retrieval | Lifecycle + novelty + structural grammar |
| Ingestion | `source_ingestion` | Streaming, parse cache, progress writes |
| Research | `source_quality` / gaps | Honest publication_type / peer_review_status |
| Workers | WorkerSupervisor + ResourceAdmission | UNKNOWN pressure; env profile; scale-to-zero |
| Security | http_auth TrustedHost | Fail-closed non-loopback hosts |
| UI | Brain pages | Hover-first labels; existing celestial clamps |
| CI | leviathan-ci.yml | Root triggers; Windows launcher tests; optional E2E |

**Untouched:** `editor/`, `Data/HADES/`

**Databases:** exactly CONTROL / KNOWLEDGE / MARKET. Added MARKET table
`market_risk_receipts` (domain migration v8) — not a fourth authority.

## VERIFICATION EVIDENCE

| Gate | Result |
|------|--------|
| Strict trading `--run-tests --strict` | **PASS** (`strict_all_required_pass=true`; 93 PASS; G16 FEATURE_GATED; G47 NOT_TESTED_IN_CI) |
| Frontend typecheck / 331 unit tests / production build | PASS |
| Launcher typecheck / 32 unit tests | PASS |
| TrustedHost + mutation auth suites | PASS |
| A–Z risk/evidence/fincept/ingestion/worker focused suites | PASS |
| Full backend pytest (pre-epistemic-fix commit) | 2 failures (AGENT_PROPOSED/PAPER_OBSERVED collapse) — **fixed** |
| Branch protection API | **OPERATOR_ACTION_REQUIRED** (HTTP 403) |
| Windows `run_leviathan.exe` build | **OPERATOR_ACTION** (lane runs typecheck/tests only) |
| Playwright E2E | Bounded suite present; optional CI; stubbed API |
| Frontier R01–R30 | NOT_STARTED (honest; not fabricated) |

## LIVE TRADING

**BLOCKED.**

## KNOWN LIMITATIONS / REMAINING

- `OPERATOR_ACTION_REQUIRED`: GitHub main branch protection
- `OPERATOR_ACTION`: native Windows exe artifact build/smoke
- `FEATURE_GATED`: G16 sandbox
- `NOT_TESTED_IN_CI`: G47 Windows paths
- `UNMEASURED`: live market credentials / Fincept install without module present
- Full backend suite re-run after final evidence tip may still be in progress on CI
- Playwright E2E does not hit a live control plane
- Performance profiling (Wave 40) metrics not published as a dedicated artifact in this run

## TRUTHFUL VERDICT

**READY_FOR_AUTONOMOUS_PAPER_WITH_EXTERNAL_GAPS**

Supported by clean-tree strict trading evidence at
`06cecb6d0df3cc2acb522831bd17413923dcb417`. Not claimed: live trading, server-side
branch protection application, Windows exe binary build, or Frontier R01–R30.
