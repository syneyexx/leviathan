# HADES Neural Memory — honest status

# HADES NEURAL V1 STATUS: COMPLETE (lifecycle + toy fixture)
# HADES NEURAL V2 STATUS: IN PROGRESS (not COMPLETE)

Status claims use three levels per capability:

| Level | Meaning |
|---|---|
| **module tested** | Unit/integration tests pass for the module in isolation |
| **API reachable** | HTTP/settings can observe or configure it |
| **production path** | Exercised on the live Chat/Work path with a real consumer |

A "PASS" below means **production path** only when explicitly stated. Otherwise it
is module-tested or API-reachable. **Do not claim V2 COMPLETE** without a host
embedding provider and measured recall.

## V1 vs V2

| | V1 | V2 (this work) |
|---|---|---|
| Encoder | Hash tokenizer + toy transformer (vocab/hidden/seq ≈ 32–64) | Frozen local LM Studio embeddings (`lm_studio_embedding`) |
| Role | Lifecycle + research fixture | Associative layer that HELPS LM Studio with recall |
| Chat dual retrieval | Inject hooks for tests only | Wired when `neural_allow` + READ/SHADOW + encoder ready |
| Experience | Verified → reward signals | + negative Slow samples; offline/batch + post-task hook |
| Eval | Phase benchmarks | `docs/neural/v2_eval.json` (UNMEASURED without provider) |

Neural is **not** an LLM. LM Studio remains chat/tool runtime (ADR-N4 / ADR-N22).
Toy remains importable under explicit `encoder=toy` for unit tests only — never
a silent production fallback.

## Defaults (conservative — unchanged)

| Setting | Default |
|---|---|
| `neural_allow` | `false` |
| `neural_mode` | `off` |
| LEARN as ModelGateway primary | **refused** |
| READ as ModelGateway primary | **refused** (F-06 — no LM fusion yet; dual-retrieval inject is separate) |
| SHADOW | diagnostics beside Standard when explicitly enabled |
| Trading domain | disabled |
| Checkpoint schema | **2** (`parametric_mlp_v2_embedding`); dim=32 toy schema-1 fails closed |

## Capability matrix

| Capability | Module tested | API reachable | Production path |
|---|---|---|---|
| Toy transformer encode/infer | yes | yes (research) | **no** — toy / test-only |
| LM Studio embedding encoder | yes (torch-free list path) | yes | when allow + `embedding_model_id` + provider |
| Runtime selection OFF | yes | yes | **yes** (default; no torch at FastAPI startup) |
| Runtime selection SHADOW | yes | yes | yes when enabled (Standard primary) |
| Runtime selection READ primary | yes (refusal) | yes (`research_only`) | **no** — refused until LM fusion |
| Chat dual retrieval READ inject | yes (fake embed) | yes | when allow + mode=read + encoder ready |
| Chat dual retrieval SHADOW | yes | yes | scores only; no `neural_association` inject |
| Verified-experience ingest | yes | POST `/api/neural/experience-ingest` | post-task hook when allow + read/shadow |
| Negative Slow samples (failures) | yes | via ingest | no durable Slow train without consolidation gates |
| Continual learning / consolidation | yes | research | evaluate-then-promote only; default OFF |
| Text association eval | harness | `v2_eval.json` | **UNMEASURED** without embedding provider |
| FINALBETA Neural control panel | — | component exists | **no imports / not mounted** |

## F-06 READ honesty (ModelGateway)

`mode=read` must **not** replace LM Studio output as ModelGateway primary.
Selection refuses READ as primary (`neural_read_not_product_ready`); Chat keeps
Standard/LM content. API status labels READ as `research_only` /
`not_product_ready=true`.

Separately, V2 dual retrieval may inject bounded `neural_association`
ContextItems (`trusted=False`) when allow + READ + encoder ready. That is
prompt-side associative recall — not Neural-as-LLM.

## What V2 changes when explicitly enabled

```
Normal HADES (Neural OFF)
  -> unchanged Standard Runtime (no torch at startup)

Neural enabled (explicit allow + mode read|shadow)
  -> production encoder = LM Studio embeddings (never silent toy)
  -> Exact + Neural dual retrieval wired in Chat/Work compiler path
  -> SHADOW: metrics only; READ: bounded neural_association inject (max 2)
  -> verified_experience ingest → Fast / negative Slow (batch + post-task)
  -> evaluate-before-promote unchanged; LEARN not gateway primary
```

## What is intentionally not claimed

- V2 COMPLETE / quality PASS without a real embedding provider
- Self-learning that improves underlying LM weights
- Vector DB replacement for FTS5/BM25
- Online LEARN during tool rounds
- Production Neural UI controls (“FINALBETA Neural controls PASS”)
- Dual retrieval on the default Chat path without explicit settings

## Architecture pointer

See `docs/neural/ARCHITECTURE.md` ADR-N1…N22.
ADR-N22: production encoder = frozen local embeddings; toy is test-only;
Neural is not an LLM.
