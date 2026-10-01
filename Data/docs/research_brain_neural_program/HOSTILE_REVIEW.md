# FINAL HOSTILE REVIEW PASSES

## Pass 1 (post-implementation)

| Question | Result |
|---|---|
| Button lies? | Run/plan/probe/url/report fail closed when external+no JobRuntime |
| Status inferred? | Brain mapComp uses exact tokens; cognition measured overrides config |
| Capability registered but cannot execute? | retrieve/synthesize marked UNSUPPORTED; consumers → advance |
| Heavy work in FastAPI fallback? | Closed via execution_gate |
| Exception swallowed? | Cancel kernel failures recorded; promotion errors persisted |
| Worker loss → false success? | Lease loss → INTERRUPTED / LEASE_LOST, not CANCELLED |
| Cancel only frontend? | Domain CANCELLING until kernel ack; cancel_ack_* fields |
| Queued called completed? | Frontend probeToastMessage + normalizeProbeResponse |
| PENDING orphan URL? | execute_fetch_url transitions reserved source_id |
| Count is bounded page? | Visible vs catalog counts; evidence ≥200 label |
| Heuristic as canonical? | linkedMemoriesHeuristic / evidenceForNodeHeuristic flags |
| Learning from client? | connect_dataset ignores client indexed authority |
| Silent fallback? | plan_provenance enrichment fields |
| Neural synthetic as production? | production_grade gate; toy refused; HF hash truth flags |
| Unknown → healthy? | statusTruth UNKNOWN default |
| Fixed limit starvation? | Research enqueue/reconcile paginated; dataset reconcile paginated |
| Duplicate authority? | No new DB/scheduler/JobRuntime |

## Pass 2 (chain retrace)

- **Chain A Research run:** UI → API → ResearchService.enqueue_run → JobRuntime research.advance → worker execute_queued_run → coordinator → terminal + knowledge_promotion_status
- **Chain B URL:** add_url_source → reserved PENDING → research.fetch_url → execute_fetch_url(source_id) → from_web_page(reserved) → Brain sync / FAILED
- **Chain C Dataset:** DatasetService.learning_state_for_dataset → connect_dataset rejects REGISTERED even if client indexed=true
- **Chain D Brain:** catalog pages → truth metadata (no invented complete) → unclassified types → statusTruth
- **Chain E Neural:** supports_residuals ≠ production_grade; deterministic toy refused outside allow

## Remaining intentional limitations

| Item | Reason |
|---|---|
| Real HF/vLLM/llama.cpp production residual payload injection | Requires real model weights + hook-compatible artifacts; Leviathan marks experimental rather than fabricating learned memory |
| ResearchMockPage kept | Non-routed reference fixture; not production capability |
| SourceIngestor alias kept | Compatibility for external scripts/tests |
