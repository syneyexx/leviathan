# Frontier Hardening Results

**Branch:** `cursor/frontier-portfolio-hardening-111b`  
**Before SHA:** `19371f444f38fe2f425538fda9f4d3856765d457`  
**After SHA (baseline):** `f5ea5a3226ad37caeb515f2cc067ce17ecff764f` (+ follow-up commits)  
**Host:** Linux Cloud Agent  
**Artifacts:** `artifacts/baselines/frontier_hardening_{before,after,comparison}.json`

## Status board

| Area | Verdict | Evidence |
|---|---|---|
| Architecture (execution gateway) | **PASS** (megafile split still PARTIAL) | `runtime/execution_gateway.py` |
| Execution-path policy invariant | **PASS** | `tests.test_frontier_execution_invariants` |
| False-success defense | **PASS** (software) | demos 01/04; `verify_ready`; work gate |
| Deterministic eval | **122/122** gated | `gen2_release_gate` 10+3+109 |
| Adversarial security | **109/109** | `evals.adversarial_corpus` |
| Backend focused suites | **PASS** | invariants, A02/A09, effect ledger, plugin isolation, claims |
| Local `verify_hades.py --quick` | **PASS** (this tip) | full backend suite + gen2 gate + contracts |
| Frontend typecheck | **PASS** | `npm run typecheck` |
| Frontend lint | **PASS** | real ESLint (`npm run lint`) |
| API fixture E2E | **PASS** | `tests.test_api_fixture_e2e` (not Playwright) |
| Browser Playwright E2E | **UNMEASURED** | not added yet |
| Portfolio demos | **6/6** | `tools/run_portfolio_demos.py` |
| Live LM Studio | **UNAVAILABLE** | host probe |
| Windows secured isolation | **UNVERIFIED_ON_HOST** | honesty preserved; Linux userns PASS |
| GitHub Actions CI | **BLOCKED_EXTERNAL** | billing / spending limit — jobs exit ~3s with empty steps |

## Before → after

| Metric | Before | After |
|---|---|---|
| Release-gated deterministic cases | 13 | **122** |
| Portfolio demos | 3/3 | **6/6** |
| Backend test count (loader) | baseline JSON | +48 cases |
| Python LOC | ~98.9k | ~102.3k |
| `npm run lint` | typecheck alias | **ESLint** |
| Plugin secured isolation | not wired | **run_isolated fail-closed** |
| Claim states | thin | SUPPORTED…SUPERSEDED from evidence |

## Exact commands

```bash
cd backend
.venv/bin/python -m evals.gen2_release_gate
# PASS — reasoning 10, red_team 3, frontier_adversarial 109

.venv/bin/python -m unittest tests.test_frontier_execution_invariants \
  tests.test_frontier_false_success_security tests.test_effect_ledger \
  tests.test_frontier_plugin_isolation tests.test_claim_verification_states \
  tests.test_api_fixture_e2e tests.test_audit_a02_a03_a04 -q

cd ..
npm run lint && npm run typecheck
python3 tools/run_portfolio_demos.py   # 6/6
python3 tools/measure_frontier_baseline.py --label after --compare
```

## Architectural / security changes

1. Privileged policy skip contract; workflow cannot select install/system
2. Harvest ask requires approval
3. Policy ImportError fail-closed
4. Empty artifact non_empty gate
5. Schedule occurrence `dispatched` ≠ completed
6. Effect ledger restart classes
7. Secured plugin `_run_command` → `run_isolated`
8. Claim register evidence-driven states
9. Context compiler `shadow_compare`
10. Real ESLint + Ruff security-boundary gate in verify

## Known residual risks

- Coding/build/voice/preview still outside PluginManager kernel
- Playwright product E2E still UNMEASURED
- Token streaming not productized
- Megafile extraction still incremental/PARTIAL
- Windows Job Object / AppContainer operational UNVERIFIED_ON_HOST
- Live model quality UNMEASURED without LM Studio

## Known failures on this host

- **GitHub Actions** (`quick-gates` / `release-gates` on ubuntu+windows): **BLOCKED_EXTERNAL** — account payments failed or spending limit. Jobs show `conclusion=failure` with **no steps executed**. Not a code failure; owner must restore billing, then `gh run rerun <id> --failed`.
- Local `verify_hades.py --quick` on tip `9407b23`: **PASS** (after settings/recommend/mission/contract/test-alignment fixes).
