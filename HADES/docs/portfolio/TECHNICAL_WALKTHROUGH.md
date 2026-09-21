# HADES technical walkthrough (5–10 minutes)

Factual demo script for reviewers. No company affiliation claims.

## 1. Problem

Local autonomous AI agents on a personal Windows/Linux host must use tools safely.
Models propose actions; they must not authorize filesystem, network, or subprocess effects.

## 2. Architecture (one minute)

- React/Vite frontend + FastAPI + SQLite (offline-first)
- LM Studio as local model gateway (dynamic model IDs)
- Plugin Runtime + Work Runtime + Gen2 Mission/Eval/Sandbox spines
- Dual UI (Classic / Obsidian) — same APIs

## 3. Deterministic security

Show `backend/runtime/execution_gateway.py` and `policy_enforcement.py`.

Key invariant: `invocation_type=install` alone cannot skip G11/G8 — requires `privileged_policy_skip`.

Demo: `python3 docs/demos/demo_02_blocked_action.py`

## 4. Local-first model gateway

Settings keep LM Studio endpoint/model dynamic. Absence → UNAVAILABLE/UNMEASURED, never fake PASS.

## 5. Reasoning / Work Runtime

Work completion requires verified checkpoint (`decide_work_task_completion`).
Demo: `demo_01_successful_task.py` and `demo_04_false_success_defense.py`.

## 6. Plugins

Manual Plugin page invoke and autonomous chat tools share `PluginManager.invoke`.

## 7. Evidence-gated completion

Empty artifacts fail `verify_ready` (`non_empty`). Process-alive ≠ healthy.

## 8. Eval lab

```bash
cd backend && python -m evals.gen2_release_gate
# reasoning + red_team + frontier_adversarial_v1 (100+ software cases)
```

Label: software defenses, not live model quality.

## 9. Live demo sequence

1. Portfolio demos: `python3 tools/run_portfolio_demos.py` (6 demos)
2. Invariant tests: `python -m unittest tests.test_frontier_execution_invariants -q`
3. Optional: open Chat UI; show approval/block behavior if LM Studio present

## 10. Known limits

- Windows Job Object / AppContainer operational: UNVERIFIED_ON_HOST on Linux CI
- Live LM Studio quality: UNMEASURED without provider
- Context Compiler default path still opt-in (shadow compare exists)
- Coding/build/voice subprocess paths still outside PluginManager

## 11. Tradeoffs

Prefer fail-closed deterministic gates over LLM judgment for permissions.
Prefer honest UNAVAILABLE over simulated PASS.
Prefer incremental megafile extraction over risky rewrites.
