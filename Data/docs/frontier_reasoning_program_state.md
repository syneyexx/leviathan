# Frontier Reasoning Program State

**Active phase:** F6 (Neural TaskModel / planner advisors — complete; next F7/F8)  
**Date:** 2026-09-25  
**Branch:** `cursor/frontier-reasoning-f6-neural-advisors-4064`  
**Base:** `cursor/frontier-reasoning-f5-structured-4064`  
**Program:** Master Implementation Program (Frontier Reasoning + Inference-Time Compute + Verified Learning)  
**Audit:** [`frontier_reasoning_f0_audit.md`](./frontier_reasoning_f0_audit.md)  
**Gates manifest:** `Data/backend/tests/frontier_reasoning_gates.json`  
**Verifier:** `scripts/verify_frontier_reasoning.py`

---

## Phase table

| Phase | Status | Notes |
|---|---|---|
| F0–F5 | PASS | Audit → structured state |
| F6 Neural advisors | PASS | Validated TaskModel + plan advice; owners remain |
| F7–F18 | NOT_STARTED | |

---

## Gate highlights

| Gate | Status | Evidence |
|---|---|---|
| R02–R07, R09 | PASS | Prior phases |
| R10 | PASS | `TaskAdviceValidationTests` |
| R11 | PASS | `PlanAdviceValidationTests` |
| R27–R29 | PASS | |
| R01 | IN_PROGRESS | Owner preserved |
| R08 / R12+ | NOT_STARTED | |

---

## F6 summary

1. `neural_advisors` — `validate_task_advice` / `validate_plan_advice` with allowlists; reject `risk_class` / `hard_constraints` / unknown capabilities.
2. `TaskModelBuilder` + `CognitivePlanner` optional advisor hooks; template/deterministic base remains owner.
3. Heuristic advisors enabled by default in CognitiveRuntime (no surprise extra LLM calls).
4. Model-backed advisors available (`Callable*Advisor`) and still validated.

## Next

**F7/F8 cluster** — adaptive compute (R08) and/or HypothesisBoard / critic mesh (R12–R13). Program table points F8 at HypothesisBoard.
