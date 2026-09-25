# Frontier Reasoning Program State

**Active phase:** F1 (Context / Trust — complete; next F2)  
**Date:** 2026-09-25  
**Branch:** `cursor/frontier-reasoning-f1-context-trust-4064`  
**Base:** `cursor/frontier-reasoning-f0-audit-4064`  
**Program:** Master Implementation Program (Frontier Reasoning + Inference-Time Compute + Verified Learning)  
**Audit:** [`frontier_reasoning_f0_audit.md`](./frontier_reasoning_f0_audit.md)  
**Gates manifest:** `Data/backend/tests/frontier_reasoning_gates.json`  
**Verifier:** `scripts/verify_frontier_reasoning.py`  
**Completion report:** [`frontier_reasoning_completion_report.md`](./frontier_reasoning_completion_report.md)

Status values: `NOT_STARTED` | `IN_PROGRESS` | `PASS` | `FAIL` | `NOT_TESTED` | `AUDIT_ONLY`

Never mark `PASS` without evidence actually run.

**Note:** `frontier_program.md` is the *trading* frontier program. This file is the *reasoning* program.

---

## Phase table

| Phase | Status | Notes |
|---|---|---|
| F0 Audit | PASS / complete | Architecture maps, gap report, gates, verifier skeleton |
| F1 Context / Trust | PASS | BehaviorProfile + ContextBuilderV3 authority separation |
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
| R01 Canonical CognitiveRuntime | IN_PROGRESS | preserved owner | Sole orch owner maintained |
| R02 Context authority separation | PASS | `test_frontier_reasoning_f1_context.ContextV3AuthorityTests` + anti-fold scan | V3 uses reference_context |
| R03 BehaviorProfile identity | PASS | `CognitionBehaviorIdentityTests` + chat wire | Settings → Cognition |
| R04 Two-axis compute | NOT_STARTED | — | |
| R05 Reasoning capability profile | NOT_STARTED | — | |
| R06 Native reasoning adapter | NOT_STARTED | — | |
| R07 TTC fallback | NOT_STARTED | — | |
| R08 Adaptive compute | NOT_STARTED | Partial orch adaptive | |
| R09 Structured reasoning state | NOT_STARTED | Partial Belief/Plan | |
| R10 Neural TaskModel | NOT_STARTED | | |
| R11 Neural planner | NOT_STARTED | | |
| R12 HypothesisBoard | NOT_STARTED | | |
| R13 Critic mesh | NOT_STARTED | | |
| R14 Independent verification | NOT_STARTED | | |
| R15 CapabilityState | NOT_STARTED | | |
| R16 Iterative tools | NOT_STARTED | | |
| R17 Async workers | NOT_STARTED | | |
| R18 Steering | NOT_STARTED | | |
| R19 Restart/resume | NOT_STARTED | | |
| R20 Experience v2 | NOT_STARTED | | |
| R21 Active learning | NOT_STARTED | | |
| R22 Training export | NOT_STARTED | | |
| R23 Candidate training lifecycle | NOT_STARTED | | |
| R24 Evaluation/ablation | NOT_STARTED | | |
| R25 Frontend reasoning controls | NOT_STARTED | | |
| R26 Observability | NOT_STARTED | | |
| R27 Resource pressure | NOT_STARTED | | |
| R28 Security | PASS | F1 injection / authority suite | F1 scope; expand later |
| R29 No hidden CoT leakage | NOT_STARTED | | |
| R30 Tests/typecheck/lint/build | NOT_STARTED | | |

### F0/F1 skeleton evidence

| Check | Status | Evidence |
|---|---|---|
| F0 audit document | PASS | `frontier_reasoning_f0_audit.md` |
| F0 program state | PASS | this file |
| F0 verifier | PASS | `scripts/verify_frontier_reasoning.py` |
| F1 ContextBuilderV3 authority | PASS | no fold-into-system; reference block |
| F1 BehaviorProfile wiring | PASS | chat + resolver + submit |

---

## F1 changes (summary)

1. `ContextBuilderV3` serializes SYSTEM / TRUSTED CONTROL / CONVERSATION / UNTRUSTED REFERENCE.
2. Brain, Memory, tools, neuro, beliefs never become system authority.
3. Role/FIM markers escaped via `escape_role_markers`.
4. Effective BehaviorProfile from Settings/Chat is canonical; seed only as default fallback.
5. Tests: `Data/backend/tests/test_frontier_reasoning_f1_context.py`

---

## Next action

**F2 — Two-axis compute:** `NeuralComputeBudget`, `ReasoningCapabilityProfile`, Settings schema, requested/effective modes, resource clamps.
