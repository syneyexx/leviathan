# Frontier Reasoning Program State

**Active phase:** F2 (Two-axis compute — complete; next F3)  
**Date:** 2026-09-25  
**Branch:** `cursor/frontier-reasoning-f2-two-axis-4064`  
**Base:** `cursor/frontier-reasoning-f1-context-trust-4064`  
**Program:** Master Implementation Program (Frontier Reasoning + Inference-Time Compute + Verified Learning)  
**Audit:** [`frontier_reasoning_f0_audit.md`](./frontier_reasoning_f0_audit.md)  
**Gates manifest:** `Data/backend/tests/frontier_reasoning_gates.json`  
**Verifier:** `scripts/verify_frontier_reasoning.py`

---

## Phase table

| Phase | Status | Notes |
|---|---|---|
| F0 Audit | PASS | Architecture maps, gap report, verifier skeleton |
| F1 Context / Trust | PASS | BehaviorProfile + ContextBuilderV3 authority |
| F2 Two-axis compute | PASS | NeuralComputeBudget + ReasoningCapabilityProfile + clamps |
| F3 Native reasoning | NOT_STARTED | Provider adapters |
| F4–F18 | NOT_STARTED | |

---

## Gate highlights

| Gate | Status | Evidence |
|---|---|---|
| R02 | PASS | F1 authority tests |
| R03 | PASS | F1 BehaviorProfile tests |
| R04 | PASS | `test_frontier_reasoning_f2_two_axis.MetaTwoAxisTests` |
| R05 | PASS | `CapabilityProfileTests` — never guess from model name |
| R27 | PASS | MAXIMUM → DEEP under GPU_RESOURCE_PRESSURE |
| R28 | PASS | F1 injection suite |
| R01 | IN_PROGRESS | Owner preserved |
| R06+ | NOT_STARTED | |

---

## F2 summary

1. `NeuralComputeBudget` — LEVIATHAN semantic neural axis (effort, candidates, branches, critics…).
2. `ReasoningCapabilityProfile` — resolved from adapter / metadata / probe / Settings override; **never** from model name alone.
3. `MetaDecision` exposes `requested_mode` / `effective_mode` / `clamp_reason` / both budget axes.
4. Settings catalog + `ReasoningSettings` / `ReasoningPolicy` wire neural budgets and adaptive clamp thresholds.

## Next

**F3 — Native reasoning adapters** (provider effort fields; no unknown knobs on generic).
