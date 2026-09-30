# Reasoning / Activity Observability — Wave 0 Implementation Map

> Internal engineering map produced before implementation. Canonical long-form docs remain `Leviathan_system_backend.md` / `Leviathan_system_frontend.md`; this file records ownership decisions for the observability program and is folded into those docs in Wave 8.

**Base revision:** `4e4f17a4` (`origin/main` after Training V2 merge)  
**Branch:** `cursor/reasoning-activity-observability-0c8a`

---

## Current authority (verified)

| Concern | Owner | Path |
|---|---|---|
| Chat turn planning (intent/complexity/steps) | ReasoningEngine | `Data/modules/reasoning/` |
| Reasoning mode (auto/fast/standard/deep) | ReasoningMode | `Data/modules/reasoning/mode.py` |
| Cognitive orchestration | CognitiveRuntime | `Data/modules/cognition/runtime.py` |
| Turn lifecycle + durable run events | RunStore / EventEnvelope | `Data/modules/run/` |
| Cross-cutting telemetry + SSE broker | ObservabilityHub | `Data/modules/observability/` |
| Capability side effects | ExecutionGateway | `Data/modules/execution/` |
| Durable heavy work | JobRuntime / Worker Fabric | `Data/modules/jobs/`, `Data/modules/workers/` |
| Agent missions/events | AgentFleetService | `Data/modules/agents/` |
| Research timeline | ResearchStore | `Data/modules/research/` |
| Trading decision packets | DecisionPacket / DecisionLedger | `Data/modules/market_sim/institutional_core/` |
| Artifacts | ArtifactStore | existing artifact module |
| Frontend chat stream | `api.chatStream` | `Data/frontend/src/api/client.ts` |
| Current reasoning UI | `ReasoningCard` in MessageList | `Data/frontend/src/pages/chat/MessageList.tsx` |
| Global V2 design | leviathan-v2.css | `Data/frontend/src/styles/leviathan-v2.css` |
| Redaction | observability.redaction | `Data/modules/observability/redaction.py` |

## Current data flow (reasoning display)

```text
POST /api/chat
  → ReasoningEngine.analyze → RetrievalDecision.steps/complexity
  → RunStore.append_event(REASONING_COMPLETED)   # plan snapshot, not live steps
  → SSE meta{reasoning: plan.public_summary()}
  → token* → done{reasoning}
ChatPage (ignores onMeta) → lastTurn.reasoning on done
MessageList.ReasoningCard → shows complexity ("low") + raw step ids
```

## Gaps

1. Steps are **plan-time intent labels**, not live operational lifecycle.
2. No hierarchical ActivityEvent contract shared by backend/frontend.
3. ChatPage does not consume mid-stream `meta` / operational events for the reasoning panel.
4. Progress/counts are not carried with measured/estimated/unknown semantics.
5. No reusable ActivityTimeline component (page-local ReasoningCard only).
6. Multi-agent / research / trading activity exist in domain stores but are not projected into chat activity UI.
7. DecisionPacket exists for institutional trading — no chat/operator DecisionReceipt view bridging it.

## Reuse plan (no parallel authorities)

| Need | Reuse / extend |
|---|---|
| Event identity, causality, versioning | Extend `EventEnvelope` + `EventType`; add `ActivityEvent` projection in `Data/modules/run/activity.py` |
| Live fan-out | Chat SSE (`activity` event) + ObservabilityHub emit (category `activity`) |
| Durability | Persist significant activity via `run_events` payloads + hub `observability_events` (CONTROL). **No new DB.** |
| Redaction / visibility | Existing `redact_payload`; add visibility class on ActivityEvent |
| Cognition ops | Map allowlisted `_public_operational_events` → ActivityEvent |
| Trading decisions | Project `DecisionPacket` → DecisionReceipt public view (no second ledger) |
| Frontend | Replace ReasoningCard body with shared `components/activity/*` using V2 CSS |
| Compatibility | Keep `reasoning.steps` / `ReasoningSummary` during migration; UI prefers activity stream when present |

## Schema impact

- New typed module: `Data/modules/run/activity.py` (+ `__init__` exports).
- New `EventType` values only if missing and mapped to real transitions (prefer payload-shaped ACTIVITY events under existing types + dedicated `ACTIVITY` where needed).
- Frontend types: `ActivityEvent`, progress, visibility; extend chat stream handlers.
- **No new SQLite database.** Optional: no migration if activity rides existing `run_events.payload` + observability store.

## Migration impact

- Idempotent: old clients ignore unknown SSE `activity` events.
- Old `reasoning.steps` remain populated for compatibility.
- Non-empty CONTROL DB unchanged structurally if we avoid new tables.

## Frontend impact

- New reusable activity primitives under `src/components/activity/`.
- MessageList uses ActivityTimeline; ReasoningCard becomes thin wrapper or is removed.
- ChatPage aggregates activity from stream + done payload.
- Display levels: compact / detailed / developer (UI preference; compute modes unchanged).

## Risk areas

- High-frequency token events must **not** become timeline rows (aggregate/coalesce).
- Stale/disconnected must not look completed.
- Secrets in tool payloads — must pass redaction before USER_VISIBLE.
- Cancellation: request → propagating → cancelled from RunStore truth only.
- Do not invent strategy-discovery stages absent from MarketSim/Research Lab.

## Forbidden (confirmed avoided)

- No ReasoningRuntimeV2, second scheduler, second worker manager, reasoning SQLite DB, page event bus, page design system, fake progress, raw CoT persistence.
