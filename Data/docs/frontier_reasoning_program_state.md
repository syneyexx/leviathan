# Frontier Reasoning Program State

**Active phase:** F4 (TTC multi-candidate — complete; next F5)  
**Date:** 2026-09-25  
**Branch:** `cursor/frontier-reasoning-f4-ttc-4064`  
**Base:** `cursor/frontier-reasoning-f3-native-4064`  
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
| F3 Native reasoning | PASS | InferenceComputeController + provider maps; no CoT leak |
| F4 TTC multi-candidate | PASS | TTCExecutor fan-out + majority/longest select |
| F5–F18 | NOT_STARTED | |

---

## Gate highlights

| Gate | Status | Evidence |
|---|---|---|
| R02–R05 | PASS | F1/F2 suites |
| R06 | PASS | F3 native maps |
| R07 | PASS | `test_frontier_reasoning_f4_ttc` |
| R27–R29 | PASS | pressure / injection / CoT strip |
| R01 | IN_PROGRESS | Owner preserved |
| R08+ | NOT_STARTED | |

---

## F4 summary

1. `TTCExecutor` — fan-out N completions with diversity temperatures; respects `max_parallel_candidates`.
2. `select_ttc_candidate` — majority-normalized self-consistency, else longest valid public text; never fabricates.
3. TTC path clears `provider_hints` (no unknown knobs). Native path stays single-call.
4. Runtime accounts for `model_calls_consumed` from multi-candidate runs.

## Next

**F5 — Structured reasoning state** (public candidate summaries / persistence contract).
