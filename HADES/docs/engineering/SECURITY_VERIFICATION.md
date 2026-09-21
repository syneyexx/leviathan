# Security verification (frontier hardening)

## Deterministic defenses verified (software)

| Area | Evidence | Status |
|---|---|---|
| G11 tool-arg injection | `policy_enforcement` + ADV corpus + A09 tests | PASS (software) |
| G8 MCP deny-wins | ADV06/07 + mcp_harden | PASS (software) |
| Privileged invoke skip | `execution_gateway` + invariant tests | PASS |
| Harvest ask approval | `chat_commands` + HarvestAskParityTests | PASS |
| Policy ImportError fail-closed | PluginManager + tool_engine | PASS |
| Empty artifact false-success | `artifacts.verify_ready` non_empty | PASS |
| Work completion gate | `decide_work_task_completion` | PASS |
| Secured isolation + venv symlink | `execution_isolation` + A02 tests | PASS on Linux host with userns |
| Effect ledger restart classes | `runtime/effect_ledger` + tests/demos | PASS (software) |
| Schedule dispatch ≠ completed | `TaskRunner.schedule_ticker` | PASS (code change) |

## Host / operational

| Area | Status |
|---|---|
| Windows Job Object FS/network isolation | **UNVERIFIED_ON_HOST** (honesty preserved in source) |
| AppContainer | Not claimed |
| Live LM Studio adversarial quality | **UNAVAILABLE / UNMEASURED** on Cloud Agent |

## Commands

```bash
cd backend
.venv/bin/python -m unittest tests.test_frontier_execution_invariants \
  tests.test_frontier_false_success_security tests.test_effect_ledger \
  tests.test_audit_a02_a03_a04 tests.test_audit_a09_policy_paths -q
.venv/bin/python -m evals.adversarial_corpus
.venv/bin/python -m evals.gen2_release_gate
```

## Residual risks

1. Coding/build/voice/preview still use subprocess outside PluginManager.
2. Plugin `_run_command` is isolation-backed for `secured` only (terminal defaults secured when available); other plugin tiers remain app-level.
3. Exactly-once external effects are not claimed — ledger is at-least-once guidance.
4. Prompt-injection defenses are pattern-based; novel phrasings may evade (fail-open risk residual on content, fail-closed on sensitive keys).
