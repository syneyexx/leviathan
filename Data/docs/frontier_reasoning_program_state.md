# Frontier Reasoning Program State

**Active phase:** F7 (Adaptive compute — complete; next F8)  
**Date:** 2026-09-25  
**Branch:** `cursor/frontier-reasoning-f7-adaptive-4064`  
**Base:** `cursor/frontier-reasoning-f6-neural-advisors-4064`  
**Program:** Master Implementation Program (Frontier Reasoning + Inference-Time Compute + Verified Learning)  
**Audit:** [`frontier_reasoning_f0_audit.md`](./frontier_reasoning_f0_audit.md)  
**Gates manifest:** `Data/backend/tests/frontier_reasoning_gates.json`  
**Verifier:** `scripts/verify_frontier_reasoning.py`

---

## Phase table

| Phase | Status | Notes |
|---|---|---|
| F0–F6 | PASS | Audit → neural advisors |
| F7 Adaptive compute | PASS | expected_gain + neural-axis adaptation |
| F8–F18 | NOT_STARTED | |

---

## Gate highlights

| Gate | Status | Evidence |
|---|---|---|
| R02–R11 | PASS | Prior + F7 |
| R08 | PASS | `test_frontier_reasoning_f7_adaptive` |
| R27–R29 | PASS | |
| R01 | IN_PROGRESS | Owner preserved |
| R12+ | NOT_STARTED | |

---

## F7 summary

1. `calibrate_expected_gain` — heuristic gain from uncertainty / evidence / contradictions / diminishing returns.
2. `adapt_neural_budget` — escalate / de-escalate / clamp neural candidates & effort independently of orch mode.
3. `MetaDecision` exposes `expected_gain`, `expected_gain_detail`, `neural_adaptation`.

## Next

**F8 — HypothesisBoard + critic mesh** (R12 / R13).
