# Functional Hardening Campaign Report

**Branch:** `cursor/frontier-functional-hardening-edc2`  
**Base HEAD:** `0db9ebb` (origin/main)  
**Principle:** Architecture is not capability until measured.

## CURRENT HEAD

See `git rev-parse HEAD` on the branch tip after merge.

## BASELINE BEFORE CHANGES

Wave 0 runner (`python -m evals.functional.runner`) on pre-fix understanding:

| Area | Metric | Value |
|---|---|---|
| Intent | accuracy | 0.878 (36/41) |
| Intent | false_execution_rate | 0.024 (1 case) |
| Intent | weighted_safety_score | 0.800 |
| Tool use | selection accuracy | 0.667 |
| Retrieval | best hybrid Recall@K | 0.778 |
| Verification ablation | — | suite added; gate PASS after |
| Coding portable | verified repair (no LM) | 0.0 (fixture/wiring only) |
| Layer C | — | BLOCKED_MODEL_UNAVAILABLE |
| Layer D | — | NOT_RUN |

## FINAL BENCHMARK RESULTS

### INTENT / ROUTING

| | Before | After |
|---|---|---|
| intent_accuracy | 0.878 | **1.000** |
| false_execution_rate | 0.024 | **0.000** |
| execution_intent_recall | 0.800 | **1.000** |
| weighted_safety_score | 0.800 | **1.000** |
| sample_size | 41 | 41 |

Deterministic guards preserved; semantic classifier remains ambiguity-triggered
(Adaptive only) and never grants permissions. Shadow recorder:
`evals.functional.shadow`.

### CODING

| | Before | After |
|---|---|---|
| verified_repair_rate (no LM) | 0.0 | 0.0 |
| lifecycle | timeout wait=False | + cancel_signaled / worker_ownership meta |
| portable manifest | — | `coding_portable_v1` (Aider/Continue importable) |

Layer C coding quality: **BLOCKED_MODEL_UNAVAILABLE**.

### RAG

| Mode | Recall@K | Precision@K | nDCG@K |
|---|---|---|---|
| lexical | 0.819 | 0.543 | 0.809 |
| lexical+ml_expand | **0.889** | 0.479 | **0.861** |
| hybrid (default weights) | ~0.78 | ~0.55 | ~0.78 |

Production defaults **unchanged** (0.55/0.45). Opt-in
`retrieval_multilingual_expand=false` by default.

### TOOL USE

| | Before | After |
|---|---|---|
| HADES preselect accuracy | 0.667 | **1.000** |
| Layer C native/JSON modes | BLOCKED_MODEL_UNAVAILABLE | same |

### VERIFICATION

Critic ablation gate: noisy critic (C) and unavailable critic (D) **false_pass=0**.
Deterministic floor owns completion truth.

### CHAT ORCHESTRATION

Status: **partial extraction**. `reasoning.chat_coordinator.ChatRunContext` /
`ChatStage` bridged onto `BackendExecutionState` emits. `send_message` not rewritten.

### WINDOWS SANDBOX

Actual capability: Tier 0/1 path+env policy; Tier 2 Job Objects = process/resource
**not** FS/network jail. Escape suite: **HOST_REQUIRED**.

### SPECIALISTS

| Class | Examples |
|---|---|
| PROMPT_SPECIALIST | chat, executor, many coding reviewers |
| TOOL_SPECIALIST | research / tool-oriented contracts |
| RUNTIME_SPECIALIST | research_worker (loop) |
| DOMAIN_ENGINE | build, trading_specialist, coding_agent_runtime, trading_lab |

No measured specialist advantage claimed without scoreboard rows.

## MODEL(S) TESTED

Deterministic / fixture Layer B only. No LM Studio model on this host →
results must be read as **HADES + deterministic**, not **HADES + model X**.

## FILES CHANGED (primary)

- `backend/evals/functional/*` — campaign schema, suites, runner
- `backend/reasoning/understanding.py` — false-execution / follow-up fixes
- `backend/reasoning/retrieval.py` — opt-in multilingual expand
- `backend/reasoning/chat_coordinator.py` — stage machine
- `backend/reasoning/specialists.py` — `engine_class`
- `backend/coding_agent.py` — timeout cancel signaling
- `backend/main.py` — ChatStage bridge + opt-in expand wiring
- `backend/database.py` — `retrieval_multilingual_expand` default false
- `backend/tests/test_functional_campaign.py`
- `docs/CURRENT_STATUS.md`, this report

## MIGRATION IMPACT

None required. New setting defaults off. Eval package is additive.

## SECURITY IMPACT

Positive: lower false-execution; sandbox honesty matrix; critic cannot false-pass.
No permission / sandbox weakening.

## PERFORMANCE IMPACT

Intent path remains deterministic (0 unnecessary classifier calls on suite).
Multilingual expand opt-in only.

## TESTS ACTUALLY RUN

- PASS: `tests.test_functional_campaign` + `tests.test_intent_understanding` (29)
- PASS: `python -m evals.functional.runner`
- NOT RUN: full `verify_hades.py`, frontend, native CTest
- BLOCKED_MODEL_UNAVAILABLE: Layer C real-model suites
- HOST_REQUIRED: Windows escape suite
- BLOCKED_EXTERNAL: GitHub Actions billing

## FAILED TESTS

None in the focused suites above.

## UNVERIFIED AREAS

Real-model intent/coding/RAG/tool quality; Windows host escape; competitor
Layer D; full release gates.

## REGRESSIONS FOUND AND FIXED

- `do not execute` / walkthrough treated as execute → fixed
- Planning markers stole plugin execute (`meerdere stappen`) → tool_use first
- Dutch `Voer dat nu uit` elliptical follow-up → execute + tools with pending_tool
- Tool shortlist missed Dutch `zoek` → synonym expand in shortlist

## KNOWN LIMITATIONS

- Coding verified repair without LM remains 0 (honest)
- Semantic retrieval without embeddings is lexical proxy in Layer B
- Chat coordinator is bridged, not a full send_message extraction
- Job Objects are not a full jail

## MANUAL TEST CHECKLIST

See end of owner checklist in the PR / campaign brief §29 — high-value items:

1. Normal Dutch Chat
2. Normal English Chat
3. Mixed-language request
4. Follow-up (“Voer dat nu uit” after plugin suggestion)
5. “Explain” vs “execute” (`Leg uit hoe ik rm -rf zou uitvoeren`)
6. Plugin/tool execution + rejection + failure recovery
7. Coding bug repair (with local model)
8. Coding timeout/cancel
9. Memory / Knowledge retrieval; enable `retrieval_multilingual_expand` if desired
10. Verification failure; critic unavailable path
11. Streaming / attachments / vision if available
12. Long-running Work resume
13. Windows sandbox negative test on Windows host
