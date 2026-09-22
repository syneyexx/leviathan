# LEVIATHAN Cognitive Runtime

> Implementation truth for `Data/modules/cognition/`.
> When this document disagrees with code/tests, **code and tests win**.

## Purpose

The Cognitive Runtime is LEVIATHAN's **orchestration authority** for bounded iterative cognition:

```text
UNDERSTAND → PERCEIVE → BELIEVE → PLAN → ACT → OBSERVE → CRITIQUE → VERIFY → COMPLETE
```

It connects existing subsystems without replacing them:

| Concern | Owner |
|---|---|
| Orchestration / TaskModel / BeliefState / WorkingMemory | **Cognitive Runtime** |
| Advisory neural signals | Neuro (`Data/modules/neuro`) |
| Model selection / inference | Model Control Plane |
| Side effects | ExecutionGateway |
| Approvals | ApprovalService |
| Evidence | EvidenceService |
| Completion validation | VerificationEngine (+ CompletionEngine for cognitive runs) |
| Module lifecycle | ModuleManager |
| Legacy intent/complexity | ReasoningEngine (compatibility classifier) |

## Authority invariants

- Neuro is **advisory only** — neural associations never become exact facts automatically.
- Side effects only via **ExecutionGateway**.
- Approvals remain authoritative.
- Model calls must use the **Model Control Plane** (when a model caller is wired).
- Capability availability is **not** keyword-NLU gated.
- Model text does **not** decide completion.
- No private chain-of-thought persistence or API exposure.
- One central SQLite — no parallel cognition database.

## Feature flags

Parent: `LEVIATHAN_FEATURE_COGNITION` (default `false`)

Children (require parent):

| Flag | Role |
|---|---|
| `LEVIATHAN_FEATURE_COGNITION_SHADOW` | Shadow plan/decide without replacing chat answers |
| `LEVIATHAN_FEATURE_COGNITION_ITERATIVE_LOOP` | Multi-step reason/act/observe loop |
| `LEVIATHAN_FEATURE_COGNITION_BELIEF_STATE` | Persist/update BeliefState |
| `LEVIATHAN_FEATURE_COGNITION_NEURO` | Include Neuro advisory perception (also requires `LEVIATHAN_FEATURE_NEURO`) |
| `LEVIATHAN_FEATURE_COGNITION_ADAPTIVE_DEPTH` | MetaController adaptive budgets |
| `LEVIATHAN_FEATURE_COGNITION_DELEGATION` | Agent delegation envelope |
| `LEVIATHAN_FEATURE_COGNITION_EXPERIENCE_LEARNING` | VerifiedExperience admission |

## Public API

```text
POST /api/cognition/submit
GET  /api/cognition/health
GET  /api/cognition/runs/{run_id}
GET  /api/cognition/runs/{run_id}/events
POST /api/cognition/runs/{run_id}/cancel
POST /api/cognition/runs/{run_id}/steer
POST /api/cognition/runs/{run_id}/resume
```

Python: `CognitiveRuntime.submit/run/cancel/steer/status/events/resume`.

## Core types

- **TaskModel** — structured orchestration metadata (goal, domain, criteria, risk, unknowns).
- **CognitiveRun** — durable lifecycle (`CREATED` … `COMPLETED_VERIFIED` / `PARTIAL` / …).
- **BeliefState** — epistemic items with support/contradiction (not CoT).
- **WorkingMemory** — bounded workspace (distinct from Neuro tier-0 buffer and exact Memory).
- **PerceptionSnapshot** — typed provenance-aware retrieval.
- **Context Builder V3** — trust-labeled sections + token budgets.
- **MetaController** — real budget allocation (FAST/STANDARD/DEEP/…).
- **VerifiedExperience** — learning candidates only after admission policy.

## Chat integration

When cognition is enabled, `/api/chat` submits a cognitive run:

- **Shadow (default recommended migration):** structured plan/meta recorded; chat answer path unchanged.
- **Active (`COGNITION_SHADOW=false`):** cognitive loop may run with model caller when wired; still cannot bypass Gateway/Approvals.

Cognition failure never fails chat (caught and reported under `cognition` metadata).

## Persistence (migration v19)

Tables:

- `cognitive_runs`
- `cognitive_events`
- `cognitive_beliefs`
- `verified_experiences`

On process restart, non-terminal runs are reconciled as interrupted (`FAILED` + metadata) — persisted RUNNING ≠ live truth.

## External-first

Heavy coding/research/browser/training work should remain in supervised workers.

Cognitive Runtime decides **what/why/when**; domain workers execute.

Delegation uses `DelegateRequest` with authority ceilings. Handlers register on `DelegationService`.

## Experience / training bridge

`ExperienceAdmissionPolicy` rejects unverified / privacy-ineligible experiences.

`training_candidates()` always sets `auto_promote_forbidden=True` — no automatic model promotion from loss.

## Limitations (honest)

- Default path remains legacy chat orchestration until shadow comparison justifies switching.
- Coding/Research delegation handlers are not auto-registered as always-on workers in this phase.
- `INVOKE_CAPABILITY` records gateway requirement; callers must wire explicit CapabilityRequest for live tool execution.
- Frontend `/cognition` operator page is API-backed (health/submit/trace); decorative Brain page is unrelated mock UI.
- No private CoT, no fabricated progress percentages.

## Tests

`Data/backend/tests/test_cognitive_runtime.py`
