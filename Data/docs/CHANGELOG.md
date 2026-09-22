# CHANGELOG

## 0.60.0-phase54 — 2026-09-22

### Residual production + Contrastive InfoNCE + Chat SSE

- **Residual production path:** vLLM / llama.cpp adapters require `/v1/residuals/hooks` before `supports_residuals()`; HTTP read/inject/forward when confirmed; receipts always carry implemented/applied/degraded/reason/truth; health≠support.
- **ResidualOrchestrator:** mid/late layer policy, `max_total_alpha` budgeting, multi-inject coordination, degrade_reasons telemetry, `streaming_degraded` truth when adapters cannot stream forward.
- **Contrastive:** EmbeddingProvider InfoNCE-style ranking (`method=embedding`); lexical UNMEASURED fallback; EXTERNAL-FIRST ephemeral recipe worker unchanged honesty.
- **Chat SSE:** `LEVIATHAN_FEATURE_CHAT_STREAMING` + child `CHAT_SSE`; real token stream on `/api/chat`; frontend consumes SSE; residual+stream degrades honestly.
- **API/UI:** `GET /api/neuro/status`; Status panel posture; Master `phase_span=0-54`.
- **Tests:** `test_neuro_phase54.py`.

### Explicitly NOT claimed
- Default production GPU residual path; multi-hour HBM/power SLO; residual-aware stream without degrade; contrastive always improves retrieval.

---

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
