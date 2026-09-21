# HADES Neural Memory — architectural decisions (Phase 0–1)

## ADR-N1 — Base model stays frozen in early phases

Full fine-tuning is deferred until neural memory itself shows measurable value.
Phase 1 does not touch any LLM weights.

## ADR-N2 — Neural runtime stays isolated / optional

PyTorch remains outside normal FastAPI import/startup (same philosophy as
`training_worker.py`). `neural_available()` is truthful. Default mode is OFF
with a hard bypass (not “gate ≈ 0”).

## ADR-N3 — Exact Brain remains separate from Neural Memory

Dataset Brain / Knowledge Library stay authoritative for provenance and exact
facts. Neural memory stores learned associations/patterns only.

## ADR-N4 — LM Studio path unchanged

OpenAI-compatible chat APIs do not expose hidden states. Prompt injection is not
neural integration. A future `NeuralModelRuntime` must sit beside ModelGateway.

## ADR-N5 — Checkpoint compatibility is fail-closed

Checkpoints bind schema, architecture version, dim, and config. Integrity hash
mismatch or incompatible dim/arch raises typed errors; no silent load.

## ADR-N6 — Modes are explicit

OFF / SHADOW / READ / LEARN. Online LEARN writes are experimental and unused by
production orchestration in Phase 1–2.

## ADR-N7 — Neural samples inherit Brain trust boundaries

Sample compilation reads only materialized Brain snapshots + registry mapping.
It reuses Brain hidden-reasoning exclusion and `redact_secrets`. Fingerprint
drift after job creation fails closed. Dataset content never executes and never
changes permissions/policy.

## ADR-N8 — Phase 3 runtime stays beside ModelGateway

`NeuralModelRuntime` is research-only, process-local, and default OFF. It does
not replace LM Studio. OFF is a hard bypass (no hooks). Base toy weights are
frozen and checksum-verified; LEARN is rejected at this boundary.

## ADR-N9 — Slow memory trains from frozen encodings only

Phase 4 updates slow neural-memory parameters using mean-pooled hidden states
from a frozen backbone. Gradients must not enter base weights. Fast memory
stays frozen unless explicitly enabled for an experiment.

## ADR-N10 — Fast memory is bounded, verified, and non-authoritative

Phase 5 session writes may update fast parameters only under an explicit
policy (verified experience, reliability, surprise threshold, write budget).
Unverified model text must not become memory. Slow weights and base weights
stay protected. Surprise is defined as reconstruction mismatch
``1 - cosine(encode(key), value)``.

## ADR-N11 — Neural experiences reuse verified-experience admission

Phase 6 does not create a second run-event store. It projects
``gen2.verified_experience`` records into neural learning signals with
explicit rewards. Hidden reasoning is rejected. Unverified completions are
ineligible for durable memory updates.

## ADR-N12 — Consolidation promotes only after evaluation gates

Phase 7 candidate slow checkpoints must pass recall/retention/base-freeze
gates before promotion. Training loss decrease alone is insufficient. Failed
evaluation restores the previous good memory and rejects the candidate.

## ADR-N13 — Neural Runtime is a lifecycle boundary, not ModelGateway

Phase 9 introduces `NeuralRuntimeBoundary` beside (not inside) ModelGateway.
Lifecycle owns start/stop/health/load/infer/metrics/cancel. Optional subprocess
isolation reuses the training_worker philosophy so worker crashes do not take
down FastAPI/SQLite. Checkpoint compatibility is validated before tensors
attach. `ready` means inference-ready. Default mode remains OFF; LEARN stays
rejected at this boundary. Production chat wiring is deferred to Phase 10.

## ADR-N14 — Runtime selection is explicit; Standard remains default

Phase 10 adds `select_model_runtime` + `gateway_chat_with_runtime` beside
ModelGateway. Callers must opt in. Neural PREFERRED falls back to Standard with
`fallback_reason=neural_runtime_unavailable`. Neural REQUIRED fails closed.
SHADOW never changes user-visible choices. LEARN is rejected at selection.
No second reasoning engine and no ModelGateway2.

## ADR-N15 — Exact and Neural retrieval stay categorically distinct

Phase 11 dual retrieval never merges Exact Brain and Neural Memory into one
bag of “context”. Neural candidates carry `provenance_status=neural_association`
and ContextItem `kind=neural_association` with `trusted=False`. Exact candidates
remain evidence-grade with real source provenance. Experiment matrix A/B/C/D
measures token/char tradeoffs without assuming D wins.

## ADR-N16 — Continual learning uses an explicit fail-closed lifecycle

Phase 12 forbids durable learning from raw model output. Experiences must pass
Candidate → Verification → Accepted before TrainingEligible. Hidden reasoning is
rejected. LEARN stays disabled by default. Promotion still requires Phase 7
evaluation gates; loss-only promotion remains forbidden.

## ADR-N17 — Real chat path stays OFF by default

Phase 10/11 real integration wires `main.gateway_chat` through
`dispatch_model_chat` and optional dual retrieval in
`assemble_chat_context_messages`. Activation requires explicit `neural_allow`
plus mode settings. OFF remains a hard Standard Runtime bypass. Neural Runtime
honestly reports no streaming and no tool protocol yet.

## ADR-N18 — Continual learning is gated, bounded, and reversible

Phase 12 `ContinualLearningPipeline` connects verified experiences to Fast
Memory and evaluate-then-promote Slow Memory without enabling online LEARN.

```
Experience
  -> Eligibility (verification / secret / personal-data)
  -> Fast Memory (bounded, rollback on unstable write)
  -> Consolidation Candidate
  -> Evaluation gates (not loss-only)
  -> Promote OR Reject (restore known-good)
```

Secrets never enter Slow Neural Memory. Identifiable personal facts prefer Exact
Memory. Failed experiences may be failure-memory signals but must not become
positive success memory. Base LLM checksum must remain unchanged.

## ADR-N19 — Domain memory is isolated and inspectable

Phase 13 keeps General / Coding / Research / Trading banks independently
versioned. Domain routing selects relevant memory only; it never grants
permissions. Fusion is bounded (`max_fused_domains`). Trading stays opt-in.

## ADR-N20 — Product controller hardens runtime for HADES

Phase 21 `NeuralProductController` owns capacity, persistence manifest, typed
OOM mapping, cancel metrics, and start/stop/restart without allocating PyTorch
when Neural is disabled. Ready means inference-ready.

## ADR-N21 — FINALBETA displays Neural; it does not own Neural logic

Phase 22 wires `/api/neural/*` through `hadesApi` into FINALBETA Neural panels.
Visual reference layout is preserved. Unavailable backend yields truthful empty
state — never fabricated ready.

## ADR-N22 — Production encoder is frozen local embeddings; toy is test-only

Neural Memory is associative memory beside Exact Brain — **not** an LLM.
LM Studio remains the chat/tool runtime (ADR-N4). V2 production encoding uses
frozen vectors from the existing local embeddings client
(`LmStudioClient.embeddings` / `backend/embeddings.py`). Dimension follows the
provider (typically 384–4096). Mixing unequal dimensions fails closed.

The Phase 1–V1 hash tokenizer + toy transformer (vocab/hidden/seq ≈ 32–64)
remains importable under an explicit `encoder=toy` flag for unit tests and
research fixtures. It must not be the silent production fallback: when
`neural_allow` is on and embeddings are unavailable, Neural reports not ready;
PREFERRED falls back to Standard (`neural_runtime_unavailable`); REQUIRED fails
closed.

Checkpoint schema_version ≥ 2 binds embedding-backed architecture ids. Legacy
dim=32 toy checkpoints must not load into embedding-dim memory.
