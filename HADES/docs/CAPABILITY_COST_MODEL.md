# Capability cost model

Optimize for the **minimum sufficient reasoning** that still produces a verified result.

## Escalation order

1. Deterministic code
2. Cached/reusable result
3. Indexed / lexical retrieval
4. Semantic retrieval (when embeddings are available; currently optional)
5. One bounded model/specialist decision
6. Broader multi-agent reasoning only when justified

Never spend a model call on work deterministic code can perform.
Never spawn an extra agent unless it adds a distinct capability, independent verification, safe parallel work, or specialist knowledge.

## Ranker penalties

Explainable components in `capability_intel.ranking.WEIGHTS`:

- plus: exact reference, lexical, synonym/semantic expansion, intent, domain, kind (only with another signal), health, bounded reliability
- minus: cost class, latency, side-effect class, agent/workflow kind, known failure

Historical metrics influence routing only with sample size; agents cannot write persistent weights.

Token fields are stored as exact provider values or `NULL` (unknown). They are never invented.

## Fast paths

| Situation | Model/agent behavior |
|---|---|
| Explicit eligible provider | No LLM routing call |
| Policy block | No downstream execution/model call |
| Static skill/knowledge | No subprocess |
| Simple explanation | No multi-agent coding workflow |
| Repair/implement Work task with a valid composition | Deterministic Work plan — no planner LLM |
| Unchanged routing cache key+state hash | Reuse |
| Deterministic verification sufficient | No verifier-model call |

Simple tasks with many plugins installed must **not** invoke every plugin.

Cross-domain and MCPMarket cost rules: `docs/INTELLIGENCE_COST_MODEL.md`.
