# LEVIATHAN Frontier Reasoning — F0 Audit

> **Phase:** F0 — AUDIT ONLY (no feature code)  
> **Date:** 2026-09-25  
> **Branch intent:** `cursor/frontier-reasoning-f0-audit-4064`  
> **Program state:** [`frontier_reasoning_program_state.md`](./frontier_reasoning_program_state.md)  
> **Verifier:** `scripts/verify_frontier_reasoning.py`  
> **Related (distinct):** `frontier_program.md` is the *trading* frontier program — do not conflate.

When this document disagrees with code/tests, **code and tests win**.

---

## 0. Absolute preservation confirmation

Inspected live owners under `Data/modules/`. The following exist and must remain canonical:

| Owner | Path / symbol | Status |
|---|---|---|
| CognitiveRuntime | `cognition/runtime.py` | Present (~1.5k LOC) |
| ReasoningEngine | `reasoning/engine.py` | Present (legacy classifier) |
| MetaController + ReasoningPolicy | `cognition/meta_controller.py`, `intelligence/policy.py` | Present — orchestration budgets only |
| CognitivePlanner | `cognition/planner.py` | Present (templates) |
| ActionSelector | `cognition/action_selector.py` | Present (deterministic VoI) |
| WorkingMemory / BeliefState / Perception | `cognition/working_memory.py`, `belief_state.py`, `perception.py` | Present |
| ContextBuilder / ContextBuilderV3 | `context/builder.py`, `cognition/context_v3.py` | Present — **authority divergence** (see Gap G02) |
| Brain / Knowledge / RAG | `brain/`, `knowledge/` | Present |
| Memory | `memory/` | Present |
| Neuro / Cortex | `neuro/` | Present (advisory) |
| Evidence | `evidence/` | Present |
| CapabilityBroker / Catalog / ExecutionGateway | `cognition/capability_broker.py`, `execution/` | Present |
| Policy / Approvals | `approvals/` | Present |
| AgentFleet / coding / research | `agents/`, `coding/`, `research/` | Present |
| Model Control Plane + adapters | `models/`, `model_runtime/` | Present |
| JobRuntime + workers | `jobs/`, `workers/` | Present |
| Datasets / Training / Evaluation | `datasets/`, `training/`, `evaluation/` | Present |
| Settings Control Plane | `settings/` | Present |
| VerifiedExperience | `cognition/experience.py` | Present (v1 admission) |
| Observability | `observability/` | Present |
| Frontend Chat / Settings / Status | `frontend/src/pages/*` | Present |

**No greenfield duplicate runtimes found** named CognitionV2 / FrontierRuntime / ReasoningRuntime2 / etc.

---

## 1. Current cognition architecture map

```text
Chat /api/chat  (main.py composition + routes)
      |
      +-- BehaviorSettingsResolver → BehaviorProfile snapshot  [CHAT path]
      +-- ReasoningEngine (legacy intent/complexity)
      +-- ContextBuilder (authority-separated serialization)   [CHAT path]
      +-- Knowledge / staged retrieval / Deep Recall / Atlas
      +-- Memory search
      +-- Neuro advisor / Cortex / residual (feature-flagged)
      +-- Model Control Plane → provider adapters → inference
      |
      +-- CognitiveRuntime.submit  (feature-flagged; often SHADOW)
            |
            +-- TaskModelBuilder (deterministic)
            +-- PerceptionService → knowledge / memory / evidence / neuro
            +-- BeliefState / WorkingMemory
            +-- MetaController → ReasoningMode + CognitiveBudgets (ORCHESTRATION axis only)
            +-- CognitivePlanner
            +-- ActionSelector → RETRIEVE | MODEL_CALL | INVOKE | DELEGATE | VERIFY | ...
            +-- ContextBuilderV3  ⚠ folds data sections into system_prompt
            +-- model_adapter → Model Control Plane
            +-- CompletionEngine + VerificationEngine
            +-- ExperienceStore (admission)
            +-- steer / resume / cancel (API: /api/cognition/*)
```

Loop (documented + implemented):

```text
UNDERSTAND → PERCEIVE → BELIEVE → PLAN → ACT → OBSERVE → CRITIQUE → VERIFY → COMPLETE
```

Reasoning modes (orchestration): `FAST | STANDARD | DEEP | MAXIMUM | ADAPTIVE`.

---

## 2. Ownership map (do not duplicate)

| Concern | Canonical owner | Must not become |
|---|---|---|
| Cognitive orchestration | CognitiveRuntime | Second cognition runtime |
| Legacy classification | ReasoningEngine | Parallel NLU gate for tools |
| Reasoning budgets (orch) | MetaController + ReasoningPolicy | Cosmetic mode labels |
| Plan representation | CognitivePlanner | Unvalidated free-form plans as authority |
| Action selection | ActionSelector | Model inventing arbitrary exec actions |
| Model routing / residency | Model Control Plane | Per-route ad-hoc clients |
| Model transport | model_runtime + providers | Bypass gateway |
| Retrieval | Brain / Knowledge | RAG as system authority |
| Durable memory | Memory module | Merged with Brain / experience |
| Neural associations | Neuro / Cortex | Exact facts / completion authority |
| Tool discovery | CapabilityBroker / CapabilityCatalog | Keyword-NLU gating |
| Side effects | ExecutionGateway + Approvals | Direct tool side effects from model text |
| Agents | AgentFleet / specialists | Parallel agent OS |
| Research / coding long work | Research + Coding + JobRuntime + workers | Sync 3-min work in FastAPI chat |
| Evidence | EvidenceService | Model claim as evidence |
| Completion truth | VerificationEngine + CompletionEngine | Model self-declaration |
| Experience learning | VerifiedExperience / ExperienceStore | Unverified training truth |
| Training / evaluation | Training + Evaluation modules | Invisible weight mutation / auto-promote |
| Settings / identity | Settings Control Plane / BehaviorProfile | Hardcoded cognition identity |

---

## 3. Model routing map

```text
CognitiveRuntime._call_model / Chat stream
        |
        v
build_control_plane_model_caller (cognition/model_adapter.py)
        |
        v
ModelControlPlane (models/control_plane.py)
  +-- router / measured_routing / profiles / residency
  +-- capability_probe (exists; reasoning often UNKNOWN)
        |
        v
Providers: openai_compatible | llama_cpp | ollama | lm_studio | vllm_class
        |
        v
model_runtime transport (OpenAICompatibleLLM, managed adapters, streaming)
```

**Gap:** No `ReasoningCapabilityProfile`, no provider-native effort / reasoning-token mapping, no `InferenceComputeController`. Provider adapters do not send native reasoning fields; `ModelCapabilities.reasoning` is typically `UNKNOWN`.

---

## 4. Brain / RAG flow

```text
Query
  → ReasoningEngine / retrieval gate (chat)
  → Knowledge staged retrieval / BrainFacade
  → optional rerank worker
  → Deep Recall / Atlas / Why (when enabled)
  → ContextBuilder packs as kind=knowledge (data_only)
  → Chat: serialize_reference_block on USER turn (authority OK)
  → Cognition Perception: EpistemicType.KNOWLEDGE_SOURCE
  → ContextBuilderV3: labeled sections then ⚠ folded into system_prompt
```

Brain stays. RAG stays. Authority bug is serialization in V3, not presence of Brain.

---

## 5. Memory flow

```text
Conversation history  → ContextBuilder messages / cognition history
WorkingMemory         → cognition only (bounded workspace)
Durable Memory store  → Perception EXACT_FACT / ContextBuilder memory sections
Brain knowledge       → KNOWLEDGE_SOURCE (separate)
VerifiedExperience    → learning admission (not ordinary memory)
Neuro tiers           → advisory associations (not exact memory)
```

Concepts remain separate — preserve this separation.

---

## 6. Neuro / Cortex flow

```text
Feature flags: LEVIATHAN_FEATURE_NEURO (+ COGNITION_NEURO)
  → neuro.advisor.assess / cortex_runtime / residual_orchestrator
  → Perception NEURAL_ASSOCIATION (trust-labeled, advisory)
  → Context: kind=neuro / ADVISORY_NEURAL_ASSOCIATION
Invariant: neural_signal_is_not_authority (tests + truth flags)
```

Neuro must stay integrated and advisory. Do not replace with RAG.

---

## 7. Tool execution flow

```text
ActionSelector → SEARCH_CAPABILITY / INVOKE_CAPABILITY
  → CapabilityBroker shortlist (discoverable ≠ authorized)
  → ExecutionGateway + Approvals + receipts
  → Observation TOOL_RESULT (untrusted data)
  → BeliefState / WorkingMemory update
  → VerificationEngine when claims require receipts
```

Capability catalog exists; **cognitive CapabilityState** (generation vs execution vs network vs authority matrix) is not yet a first-class cognition object (Gap G15).

---

## 8. Agent / specialist flow

```text
CognitiveRuntime DELEGATE_AGENT
  → DelegationService + specialist handlers (coding/research registered optionally)
  → AgentFleet / AgentRuntime / CodingControlPlane / Research
  → JobRuntime + workers (coding/research pools) for long work
  → Observation AGENT_RESULT
```

---

## 9. Worker flow

```text
API / CognitiveRuntime
  → JobStore lease + budgets + priority
  → WorkerSupervisor pools (research, coding, knowledge_*, evaluation, training, provider_io, …)
  → Entrypoints under workers/entrypoints/*
  → Result event / observation
```

**Gap:** No `cognition.advance` job kind — CognitiveRuntime still advances in-process (also noted in trading `frontier_program.md` B4). Deep cognition should externalize long research/diagnostics/candidate batches.

---

## 10. Verification flow

```text
Model / tool / research claim
  → Evidence refs + CapabilityReceipt / process output / filesystem evidence
  → VerificationEngine
  → CompletionEngine → COMPLETED_VERIFIED | COMPLETED_UNVERIFIED | PARTIAL | …
Invariant: model claim ≠ verified fact
```

Critics today: lightweight `_process_critic` inside CognitiveRuntime — **not** a named Critic mesh (Factual/Logic/Constraint/…).

---

## 11. Training / experience flow

```text
Cognitive run terminal
  → ExperienceStore.build_from_run
  → ExperienceAdmissionPolicy (verification + privacy)
  → admitted VerifiedExperience
  → training_candidates() always auto_promote_forbidden=True
  → Training service (SFT / DPO preference paths exist)
  → Evaluation / promotion gates (operator activation)
```

**Gaps:** Aggregate statistics (N, CI, rates by domain/mode/effort) are thin; trajectory export for structured public cognition (no private CoT) not fully specified; active learning queue exists but not wired to full capture triggers.

---

## 12. Settings ownership map

| Setting domain | Owner | Notes |
|---|---|---|
| BehaviorProfile / system identity | `settings/behavior*` + resolver | Chat uses effective snapshot |
| ReasoningPolicy (orch budgets) | `intelligence/policy.py` via Settings | Wired into MetaController |
| Cognition feature flags | env / config | Parent `LEVIATHAN_FEATURE_COGNITION` |
| Model residency / routing | Model Control Plane + Settings | |
| Workers | `workers/settings.py` | |
| Learning / auto-train | Training settings | Auto-promotion forbidden |

**Gap:** Cognition ContextBuilderV3 uses `SEED_SYSTEM_PROMPT` fallback, not effective BehaviorProfile (Gap G03). No NeuralComputeBudget settings schema yet.

---

## 13. Frontend map (current)

| Surface | Current | Gap |
|---|---|---|
| ChatPage | Shows cognition mode/status tags; legacy reasoning steps | No AUTO/FAST/STANDARD/DEEP/MAXIMUM selector; no public activity panel of backend events; no native-reasoning telemetry |
| Settings | `reasoning_mode_default` on BehaviorProfile | No neural budgets, adaptive thresholds, learning capture controls |
| Status / Performance | System telemetry | Not two-axis compute observability |
| Model UI | Capabilities include coarse `reasoning` | No native effort / token budget truth |

---

## 14. Context authority finding (critical for F1)

### Chat `ContextBuilder` (good)

- System = behavior core + pinned constraints  
- Knowledge / tools / neuro → `serialize_reference_block` on **user** turn  
- Provenance: `knowledge_in_system_role: False`, `knowledge_authority: untrusted_reference_data`  
- Covered by `test_chat_brain_boundary.py`, `test_context.py`

### Cognition `ContextBuilderV3` (bug)

```text
# context_v3.py — current serialization
system_prompt = join(sections where kind == system)
system_prompt += join(ALL other sections)   # ← elevates RAG/memory/tools into system string
```

Epistemic labels exist (`EpistemicType`, trust labels) but are undermined by concatenation into `system` role content.

Also: system identity seeded from `SEED_SYSTEM_PROMPT`, not BehaviorProfile effective snapshot.

---

## 15. Two-axis compute finding

Present: **Orchestration compute** via `CognitiveBudgets` (iterations, model calls, tokens, tools, agents, retrieval, critics, workers, wall time, context).

Absent: **Neural inference compute** (`NeuralComputeBudget`: native_effort, max_reasoning_tokens, candidates, branch width/depth, self-consistency, reflection, critic/verifier/repair passes, diversity_temperature).

Absent: `InferenceComputeController` inside CognitiveRuntime for native vs TTC fallback.

---

## 16. Gap report (program-aligned)

| ID | Gap | Target gate | Severity |
|---|---|---|---|
| G01 | CognitiveRuntime canonical path often SHADOW; chat still owns deep inline enrichment | R01 | High |
| G02 | ContextBuilderV3 folds untrusted data into system_prompt | R02 | **FIXED in F1** |
| G03 | Cognition uses seed prompt, not effective BehaviorProfile | R03 | **FIXED in F1** |
| G04 | No NeuralComputeBudget / two-axis modes | R04 | High |
| G05 | No ReasoningCapabilityProfile resolution | R05 | High |
| G06 | No provider-native reasoning adapters | R06 | High |
| G07 | No TTC candidate/diversity/pruning path for local models | R07 | High |
| G08 | Adaptive exists for orch mode only; no neural axis / expected_gain calibration | R08 | Medium |
| G09 | Structured state partial; missing candidate summaries / full public persistence contract | R09 | Medium |
| G10 | TaskModelBuilder deterministic only — no neural semantic advisor | R10 | Medium |
| G11 | Planner templates only — no validated neural plan proposal | R11 | Medium |
| G12 | HypothesisBoard exists but statuses/fields differ from program; not deep-branched in runtime | R12 | Medium |
| G13 | No Critic mesh (named domain critics) | R13 | Medium |
| G14 | Verification present; receipt truth coverage uneven for research/files | R14 | Medium |
| G15 | No cognition CapabilityState matrix (generate vs execute vs network) | R15 | High |
| G16 | Iterative tools exist in loop; interleaving with native reasoning not present | R16 | Medium |
| G17 | No cognition.advance worker externalization | R17 | High |
| G18 | Steering API exists; invalidation scoping for mid-turn corrections incomplete vs program | R18 | Medium |
| G19 | Resume/reconcile exists; restart-safe deep runs not fully durable for pending workers | R19 | Medium |
| G20 | Experience v1 — weak aggregates / procedural N statistics | R20 | Medium |
| G21 | Active learning queue only — trigger coverage incomplete | R21 | Low |
| G22 | Training export not structured trajectory bridge | R22 | Medium |
| G23 | Candidate lifecycle exists in training; not wired from cognition trajectories | R23 | Medium |
| G24 | Evaluation/ablation modules exist; no frontier reasoning suite | R24 | Medium |
| G25 | Frontend reasoning controls missing | R25 | Medium |
| G26 | Observability missing two-axis / native token fields | R26 | Medium |
| G27 | Resource clamps partially in MetaController; requested≠effective reason codes incomplete | R27 | Medium |
| G28 | Security/injection tests cover chat ContextBuilder more than V3 | R28 | High |
| G29 | No CoT leakage tests for native reasoning channels | R29 | Medium |
| G30 | Verifier/gates/docs skeleton = this F0 deliverable | R30 | F0 |

---

## 17. Baseline benchmark notes (honest)

No frontier reasoning benchmark was executed in F0 (audit-only). Existing related suites that establish baseline capability:

| Suite | Role |
|---|---|
| `test_cognitive_runtime.py` | Cognition loop, beliefs, experience admission |
| `test_chat_brain_boundary.py` / `test_context.py` | Chat context authority |
| `test_neuro*.py` | Neuro advisory invariants |
| `test_verification.py` | Verification engine |
| `test_wave1_cognition_agents.py` | Cognition + agents wave |
| `evaluation/` ablations / harness | General eval platform (not yet R24 suite) |

Baseline claim for F0: **architecture is present and connected; two-axis inference compute and V3 authority separation are not yet implemented.** Mark any latency/token numbers as **UNMEASURED** until measured.

---

## 18. What must not be done next

- Do not create parallel runtimes (`*V2`, `FrontierRuntime`, …).
- Do not remove Neuro, Brain, Memory, Workers, Training, Evaluation, Settings.
- Do not treat F0 docs as PASS for R01–R30.
- Do not start F2+ before F1 context/identity trust fixes.

---

## 19. Recommended next phase

**F1 — Context / Trust** only:

1. Pass effective BehaviorProfile into CognitiveRuntime → ContextBuilderV3.  
2. Split serialization: SYSTEM / TRUSTED CONTROL / CONVERSATION / UNTRUSTED REFERENCE.  
3. Prompt-injection + authority tests for V3 parity with chat ContextBuilder.  
4. Keep epistemic types; fix authority, do not remove RAG/Neuro/Memory.
