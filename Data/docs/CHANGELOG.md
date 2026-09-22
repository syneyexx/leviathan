# CHANGELOG

## 0.55.0-phase52 — 2026-09-22

### Neuro Layer — Grok-level depth jump (local-first, honest)

Frontier-feeling reasoning quality for complex queries without breaking LEVIATHAN invariants.

- **Residual adapters:** `HFTransformersResidualAdapter` can load real weights under `LEVIATHAN_NEURO_RESIDUAL_LOAD_WEIGHTS` (dev/high-memory). Injection modes ADDITIVE / GATED / DISABLED with full provenance receipts. Deterministic toy remains the CI-verified residual path. vLLM / llama.cpp stubs stay honest when hooks are absent.
- **Cortex:** Planner uses complexity, token budget, residual availability, memory coverage/quality, working-memory load, and critic flag. Runtime supports mid-forward critic re-steer and residual layer replay. Depth metadata is advisory only.
- **ProcessCritic:** Grounding collapses when Evidence/Knowledge IDs are available but uncited.
- **Memory tiers:** Priority eviction, high-trust Verification/human writes, budgeted retrieve, concurrent-safe snapshots, embedding-aware contrastive head (lexical UNMEASURED otherwise).
- **Training recipes:** Executable status machine with optional trainer backend; refuse fabricated COMPLETED metrics; human preference bridge.
- **Observability:** `category=neuro` telemetry; richer `/api/status` neuro posture.
- **Tests:** `Data/backend/tests/test_neuro_phase52.py`; full backend suite green (229).
- **Docs:** `neuro_layer_architecture.md`, `buildplan.md`, `leviathan_system.md` updated. Master `phase_span=0-52`.

### Honesty bar (unchanged)

- neural signal ≠ authority
- residual injection optional + degradable
- model output ≠ evidence
- registered ≠ trained
- unmeasured ≠ passed
- one SQLite / one Model Runtime / one Execution Gateway plane
