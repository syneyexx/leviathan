# Frontier Reasoning Program State

**Active phase:** F3 (Native reasoning — complete; next F4)  
**Date:** 2026-09-25  
**Branch:** `cursor/frontier-reasoning-f3-native-4064`  
**Base:** `cursor/frontier-reasoning-f2-two-axis-4064`  
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
| F4–F18 | NOT_STARTED | |

---

## Gate highlights

| Gate | Status | Evidence |
|---|---|---|
| R02 | PASS | F1 authority tests |
| R03 | PASS | F1 BehaviorProfile tests |
| R04 | PASS | `test_frontier_reasoning_f2_two_axis.MetaTwoAxisTests` |
| R05 | PASS | `CapabilityProfileTests` — never guess from model name |
| R06 | PASS | `test_frontier_reasoning_f3_native` — native maps / TTC for generic |
| R27 | PASS | MAXIMUM → DEEP under GPU_RESOURCE_PRESSURE |
| R28 | PASS | F1 injection suite |
| R29 | PASS | strip private CoT + public normalize path |
| R01 | IN_PROGRESS | Owner preserved |
| R07+ | NOT_STARTED | |

---

## F3 summary

1. `InferenceComputeController` — inside CognitiveRuntime path (not a second runtime); native vs TTC plan.
2. `native_reasoning` — provider-family maps; generic sends **no** unknown knobs.
3. Provider adapters expose honest `reasoning_capability_profile()` (default: native unsupported).
4. Transport strips private reasoning/thinking fields; `reasoning_tokens` only when provider-reported else `UNMEASURED`.

## Next

**F4 — TTC multi-candidate** (execute candidate budget prepared in F3; verify/select without inventing native knobs).
