# Baseline reconciliation (SpaceX Batch 0 — 2026-09-17)

Historical note: the previous “Baseline python-only (pre-fix)” block recorded
1060 tests with 11 failures / 3 errors on an older tip. This file now states the
**reconciled** status for those named residuals on current `main` tip evidence
from Linux Cloud Agent (2026-09-17). It does **not** claim a fresh full-suite PASS.

## Reconciled named residuals

| Residual | Old baseline | 2026-09-17 this host | Label |
|---|---|---|---|
| `ApiTests` autonomy plugin invoke / failed tool / multi-tool | ERROR | **PASS** after Fake LM `attach_run` + duck-typed `attach_lm_run` | VERIFIED |
| `ApiTests.test_invalid_autonomous_tool_choice_returns_truthful_chat_response` | ERROR | **PASS** (`status=blocked`, honest stop message) | VERIFIED |
| `ApiTests.test_persistent_work_runtime_plans_executes_and_verifies` | FAIL | still FAIL `evidence_coverage:insufficient_support` | REGRESSION_PRESENT |
| AgentE2E evidence_auditor / tool_orchestrator / trading_specialist / voice / web_scout | FAIL | still FAIL same completion-verification gate | REGRESSION_PRESENT |
| `Gen2ApiContractDriftTests.test_mapped_methods_cover_posted_input_models` | FAIL | **PASS** | VERIFIED |
| Milestone1 investigate + hard benchmark | FAIL | **PASS** | VERIFIED |
| Humanizer PluginManager E2E | FAIL | hung / timeout on this agent | insufficient_evidence |
| Full discover hang (`test_api_fixture_e2e` / related) | (not listed) | hang observed | insufficient_evidence |

## Still open (not claimed fixed)

- Work Runtime / specialist agent e2e completion verification mismatch
- Full `verify_hades.py` on a prepared Windows host
- GitHub Actions: **BLOCKED_EXTERNAL** (billing/runners)
- Windows Job Objects / live LM / Voice physical audio: **UNVERIFIED_ON_HOST**

## Trading Lab

Trading Lab unit headers previously said NOT EXECUTED. Re-run:
`python3 -m unittest discover -s backend/tests -p 'test_trading*.py' -v` → **120 OK** → **VERIFIED_ON_HOST**
(see `docs/TRADING_LAB.md` §8 and `docs/CURRENT_STATUS.md`).

## Historical raw baseline (pre-fix archive)

- Ran 1060 tests, FAILED (failures=11, errors=3, skipped=12)
- Host: Linux cloud agent

### Failures/Errors (historical list)

- `ERROR: test_bot_autonomously_invokes_enabled_plugin_and_receives_result`
- `ERROR: test_failed_autonomous_tool_result_is_returned_to_bot`
- `ERROR: test_invalid_autonomous_tool_choice_returns_truthful_chat_response`
- `FAIL: test_evidence_auditor_real_store_and_no_false_pass`
- `FAIL: test_tool_orchestrator_plugin_spine_permissions_and_audit`
- `FAIL: test_trading_specialist_paper_seed_and_kill_switch`
- `FAIL: test_voice_specialist_doctor_and_transcript_flow`
- `FAIL: test_web_scout_block_allow_persist_and_failures`
- `FAIL: test_bot_can_execute_multiple_tools_in_one_chat_response`
- `FAIL: test_persistent_work_runtime_plans_executes_and_verifies`
- `FAIL: test_mapped_methods_cover_posted_input_models`
- `FAIL: test_investigate_coding_run_verifies`
- `FAIL: test_hard_benchmark_layer`
- `FAIL: test_humanizer_search_skills_via_plugin_manager`
