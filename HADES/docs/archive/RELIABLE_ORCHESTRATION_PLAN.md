# HADES reliable orchestration — execution plan

> **HISTORICAL / SUPERSEDED.** This inventory predates the shipped Work Runtime scheduler, ModelRouter, streaming events, specialist contracts and practice scenarios. Keep only as archaeology. See `docs/HADES_GEN2_ROADMAP.md` for the active roadmap and `docs/REASONING_ARCHITECTURE.md` for the live kernel.

Reference baseline: `b26d1d8` (real orchestration, evidence, budgets).

## Inventory (verified against source, not docs alone)

| Area | Status | Notes |
|---|---|---|
| Shared reasoning kernel (`backend/reasoning/`) | Working | contracts, understanding, profiles, context, tools, verification, budgets |
| Chat ↔ Work/verification wiring | Working | `ExecutedRoute`, evidence gate, tool-budget exhaustion |
| Conversation `working_state` | Partial | Exists but treats completed answers as decisions; weak correction |
| Specialist agents | Partial | Profiles seeded; routing is keyword-only; no full specialist contracts |
| Work plan dependencies / parallel steps | Missing | Sequential `for` over steps; no `depends_on` column |
| ModelRouter / per-role models | Missing | Single model_id path; no fallback queue |
| Shared retrieval pipeline | Partial | Lexical memory + FTS knowledge; no hybrid/semantic/filters |
| Research ↔ shared planner | Partial | `ResearchRunner` separate from Work specialists |
| Evidence claim coverage | Partial | `evidence_refs` existence checks; no support-level typing |
| Multi-plugin validated handoffs | Partial | Tool loop exists; no typed artifact handoff |
| Pause / redirect / resume control | Partial | Cancel/retry; no pause-safe / redirect invalidation |
| Streaming / event protocol | Missing | `streaming` setting unused (`stream: false`) |
| Config for new knobs | Missing | Defaults incomplete for concurrency/embeddings/etc. |
| Brain from live run data | Partial | Static seed graph + external links |
| Scenario evals A–E | Missing | Deterministic reasoning eval exists (narrower) |

## Dependencies

1. Fix remaining foundation gaps (working_state corrections, plan contracts).
2. Specialist contracts + ModelRouter + atomic budgets → enable scheduler.
3. Retrieval + memory → Research/Evidence quality.
4. Run control + events + settings → UI scenarios.
5. Evals/scenarios last, against the integrated path.

## Acceptance per milestone

See user brief §§2–16. Each milestone ships storage + service + API (+ UI when needed) with focused tests before the next layer.
