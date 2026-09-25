# Frontier Reasoning Program State

**Active phase:** F0 (AUDIT COMPLETE — STOP; no feature code in F0)  
**Date:** 2026-09-25  
**Branch:** `cursor/frontier-reasoning-f0-audit-4064`  
**Program:** Master Implementation Program (Frontier Reasoning + Inference-Time Compute + Verified Learning)  
**Audit:** [`frontier_reasoning_f0_audit.md`](./frontier_reasoning_f0_audit.md)  
**Gates manifest:** `Data/backend/tests/frontier_reasoning_gates.json`  
**Verifier:** `scripts/verify_frontier_reasoning.py`  
**Completion report:** [`frontier_reasoning_completion_report.md`](./frontier_reasoning_completion_report.md)

Status values: `NOT_STARTED` | `IN_PROGRESS` | `PASS` | `FAIL` | `NOT_TESTED` | `AUDIT_ONLY`

Never mark `PASS` without evidence actually run. F0 may only mark audit/skeleton gates.

**Note:** `frontier_program.md` is the *trading* externalization program. This file is the *reasoning* program.

---

## Phase table

| Phase | Status | Notes |
|---|---|---|
| F0 Audit | AUDIT_ONLY / complete | Architecture maps, gap report, gates, verifier skeleton |
| F1 Context / Trust | NOT_STARTED | BehaviorProfile + authority separation |
| F2 Two-axis compute | NOT_STARTED | NeuralComputeBudget + settings |
| F3 Native reasoning | NOT_STARTED | Provider adapters |
| F4 Test-time compute | NOT_STARTED | Candidates / pruning |
| F5 Structured state | NOT_STARTED | Persist public cognitive state |
| F6 Neural TaskModel + planner | NOT_STARTED | Advisors + validation + fallback |
| F7 Action ranking | NOT_STARTED | Neural advisory + hard filters |
| F8 Hypotheses + critics | NOT_STARTED | HypothesisBoard + critic mesh |
| F9 Verification | NOT_STARTED | Receipts / completion classes |
| F10 CapabilityState | NOT_STARTED | Generate vs execute vs network |
| F11 Async cognition | NOT_STARTED | cognition.advance workers |
| F12 Long horizon | NOT_STARTED | Steering / compaction / restart |
| F13 Experience learning | NOT_STARTED | Aggregates / active learning |
| F14 Training bridge | NOT_STARTED | Verified trajectories |
| F15 Post-training | NOT_STARTED | Existing Training only |
| F16 Evaluation | NOT_STARTED | Ablations / benchmarks |
| F17 Frontend / Settings | NOT_STARTED | Mode selector / activity / caps UI |
| F18 Final hardening | NOT_STARTED | R30 full green |

---

## Gate table (R01–R30)

| Gate | Status | Evidence | Notes |
|---|---|---|---|
| R01 Canonical CognitiveRuntime | NOT_STARTED | — | Runtime exists; must remain sole orch owner |
| R02 Context authority separation | NOT_STARTED | F0 audit G02 | V3 folds data into system — F1 |
| R03 BehaviorProfile identity | NOT_STARTED | F0 audit G03 | V3 uses SEED — F1 |
| R04 Two-axis compute | NOT_STARTED | F0 audit G04 | Orch only today |
| R05 Reasoning capability profile | NOT_STARTED | F0 audit G05 | |
| R06 Native reasoning adapter | NOT_STARTED | F0 audit G06 | |
| R07 TTC fallback | NOT_STARTED | F0 audit G07 | |
| R08 Adaptive compute | NOT_STARTED | Partial orch adaptive | Extend to neural axis |
| R09 Structured reasoning state | NOT_STARTED | Partial Belief/Plan | |
| R10 Neural TaskModel | NOT_STARTED | Deterministic builder only | |
| R11 Neural planner | NOT_STARTED | Templates only | |
| R12 HypothesisBoard | NOT_STARTED | Module exists; wire + align statuses | |
| R13 Critic mesh | NOT_STARTED | Inline critic only | |
| R14 Independent verification | NOT_STARTED | Engine exists; harden receipts | |
| R15 CapabilityState | NOT_STARTED | Cognition matrix missing | |
| R16 Iterative tools | NOT_STARTED | Loop supports; deepen interleaving | |
| R17 Async workers | NOT_STARTED | No cognition.advance | |
| R18 Steering | NOT_STARTED | API exists; scoped invalidate | |
| R19 Restart/resume | NOT_STARTED | Partial reconcile | |
| R20 Experience v2 | NOT_STARTED | v1 admission present | |
| R21 Active learning | NOT_STARTED | Queue stub | |
| R22 Training export | NOT_STARTED | | |
| R23 Candidate training lifecycle | NOT_STARTED | Training promotion exists; unwired | |
| R24 Evaluation/ablation | NOT_STARTED | | |
| R25 Frontend reasoning controls | NOT_STARTED | | |
| R26 Observability | NOT_STARTED | | |
| R27 Resource pressure | NOT_STARTED | Partial MetaController clamp | |
| R28 Security | NOT_STARTED | Chat tests stronger than V3 | |
| R29 No hidden CoT leakage | NOT_STARTED | Policy stated; native channel N/A | |
| R30 Tests/typecheck/lint/build | NOT_STARTED | Verifier skeleton only in F0 | |

### F0 skeleton evidence gates (non-PASS program gates)

| Check | Status | Evidence |
|---|---|---|
| F0 audit document present | PASS | `Data/docs/frontier_reasoning_f0_audit.md` |
| F0 program state present | PASS | this file |
| F0 gates JSON present | PASS | `Data/backend/tests/frontier_reasoning_gates.json` |
| F0 verifier skeleton present | PASS | `scripts/verify_frontier_reasoning.py` |
| F0 no feature code | PASS | docs + gates + verifier only |

---

## Preservation checklist (must stay true every phase)

- [x] CognitiveRuntime remains owner (present)  
- [x] Neuro / Cortex present  
- [x] Brain / RAG present  
- [x] Memory present  
- [x] Model Control Plane present  
- [x] ExecutionGateway present  
- [x] AgentFleet present  
- [x] Workers / JobRuntime present  
- [x] Settings present  
- [x] Training / Evaluation present  
- [ ] Two-axis compute  
- [ ] Context authority correct in cognition path  
- [ ] R01–R30 PASS  

---

## Next action

Proceed to **F1 — Context / Trust** only after this F0 PR is accepted. Do not implement NeuralComputeBudget or native adapters before F1.
