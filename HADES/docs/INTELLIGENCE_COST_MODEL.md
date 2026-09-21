# Intelligence cost model

Optimize **verified outcome per unit of reasoning cost**.

Not maximum reasoning, agents, or context. Not minimum tokens at the expense of quality.

Capability-layer details: `docs/CAPABILITY_COST_MODEL.md`. One Brain adds the same invariant across domains and MCPMarket.

## Escalation

1. Deterministic code
2. Valid cache / reuse
3. Metadata / indexed / lexical retrieval
4. Semantic retrieval (when embeddings exist)
5. One bounded model decision
6. One specialist
7. More agents only with a recorded reason
8. Expensive multi-agent reasoning last

If two approaches are similarly reliable, prefer fewer model calls, agents, context, tokens, tool rounds, retries, latency, and compute.

## Hard rules

A model call needs a reason deterministic infrastructure cannot satisfy.

Never send full plugin/MCP/agent/skill catalogs, the repository, or a full mission transcript to a model by default.

Large content travels as `artifact_ref` / `evidence_ref` / `file_ref` / `dataset_ref` / `run_ref` / `summary_ref`.

## Fast paths (must stay cheap)

| Situation | Expected cost |
|---|---|
| Explicit eligible provider | Zero routing LLM |
| Policy block | Zero downstream model/tool calls |
| Deterministic exact capability match | Zero semantic/model routing |
| Known exact skill | Unrelated skills not loaded |
| Simple chat/explain | No multi-agent team |
| One-agent task | No second agent without a recorded reason |
| Deterministic verification (tests/stats/render checks) | No verifier LLM by default |
| MCP server with many tools | Bounded shortlist; full schemas only for candidates |
| Same unresolved marketplace requirement in a mission | Cached; no duplicate query/model reasoning |
| Cross-domain handoff | Refs/deltas, not upstream transcript |

## Observability

`hades_brain.cost.CostLedger` tracks model calls, tokens (exact / estimated / unknown — never fabricated), context chars, agents, tool rounds, retries, cache hits/misses, skill loads, schema loads.

No single opaque cost score.

Decision records answer why capability/provider/model/agent/node/model-call/context/cache/evidence — never private chain-of-thought.

## Cache invalidation

Reuse routing, retrieval, skill selection, tool observations, and marketplace discovery when the state hash is unchanged (workspace revision, file hash, plugin version, skill hash, provider version, dataset version).

Summarize only when future token savings exceed summarization cost.
