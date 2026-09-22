# RAG V3 Architecture — Dual Cold + Deep Recall

## Claimed / not claimed

**Claimed**
- Knowledge V2/V3 documents + chunks live in the central LEVIATHAN SQLite database.
- Chunks carry content hashes, span offsets, provenance, confidence, and source_type.
- Directional relation atoms are first-class rows (not a parallel graph DB).
- HybridRetriever fuses lexical FTS with dense vectors when an EmbeddingProvider is available.
- LocalHashEmbeddingProvider is always available (deterministic, not a neural model).
- SentenceTransformersEmbeddingProvider is optional; unavailable deps degrade honestly.
- Cold Atlas is mutable interpretation; evidence chunks remain immutable when atlas is revised.
- Deep Recall is a first-class host operation with budget/stop conditions.
- Why Library stores advisory assimilation records with evidence-gated parent inheritance.
- Cognitive Economy Governor limits depth / Deep Recall by default (“depth on demand”).

**Not claimed**
- Sentence-transformers quality without installing optional deps.
- Residual stream production without `LEVIATHAN_NEURO_RESIDUAL_LOAD_WEIGHTS` + loadable model.
- Atlas summaries as authoritative truth.
- Neural / Why / Deep Recall signals as side-effect authority.

## Dual-cold layout

```text
Hot / lukewarm working memory
        ↓
Cold Atlas (mutable summaries, entities, unresolved, contradictions)
        ↓ selective hydrate
Cold Evidence Log (immutable chunks + provenance + relation atoms)
```

## Deep Recall flow

1. Economy governor decides whether Deep Recall is allowed.
2. ReasoningEngine may set `use_deep_recall` from precision cues + coverage gaps.
3. Atlas search (cheap) → hydrate only needed evidence refs → optional hybrid fill.
4. Budget / stop conditions halt hydration; result reports `stopped_reason` honestly.

## Feature flags

| Flag | Parent | Default |
|------|--------|---------|
| `LEVIATHAN_FEATURE_RAG_V3` | — | false |
| `LEVIATHAN_FEATURE_DEEP_RECALL` | RAG_V3 | false |
| `LEVIATHAN_FEATURE_WHY_LIBRARY` | RAG_V3 | false |
| `LEVIATHAN_EMBEDDING_PROVIDER` | — | `hash` when RAG_V3 else `null` |
| `LEVIATHAN_EMBEDDING_MODEL` | — | unset |
| `LEVIATHAN_RERANKER_MODEL` | — | unset |

## Optional dependencies

See `Data/modules/knowledge/requirements-embeddings.txt` for sentence-transformers.
Core requirements stay minimal; missing optional deps → capability UNAVAILABLE.

## External-first note

Dense embedding / reranker / residual weight loads are optional heavy paths.
Execution stays contract-driven through Core Knowledge / Neuro facades.
No parallel vector database; embeddings live as BLOBs in central SQLite.
