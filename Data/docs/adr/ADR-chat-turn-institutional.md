# ADR: Chat Turn Persistence & Institutional Chat Hardening

## Status
Accepted

## Context
LEVIATHAN Chat historically treated a turn as "message rows + volatile lastTurn UI state".
That is insufficient for institutional conversational runtime: reload lost rich metadata,
cancellation closed transport without cancelling logical runs, conversation catalog was
bounded/local, telemetry collapsed unknown→zero, and CognitiveRuntime vs fallback ownership
needed durable recording.

## Decision
1. Introduce CONTROL-owned `chat_turns` table (migration 62) storing identity/reference/
   summary metadata — not duplicated Knowledge/Activity/Artifact payloads.
2. `ChatTurnStore` + `ChatTurnCoordinator` accept/complete/fail turns; cancel adapts over
   RunStore / CognitiveRuntime / TEAM (no parallel execution gateway).
3. Canonical SSE meta includes `turn_id`, `chat_run_id`, requested/effective runtime fields.
4. Conversation catalog uses cursor pagination + server search; messages use before_id pages.
5. Frontend: shared reasoning modes (auto/fast/standard/deep), shared prompt presets,
   turn state machine, safe markdown, telemetry unknown≠zero, draft New Chat until first send.
6. Response contract normalizes on `assistant_message`; legacy `message` alias kept temporarily
   with `_compatibility` marker for verified older clients.

## Consequences
- Old conversations/messages remain readable without turn rows.
- New turns hydrate per-assistant-message metadata on reload.
- Startup reconciles stale ACCEPTED/RUNNING/STREAMING turns → INTERRUPTED.
- CANCELLED ≠ FAILED is durable and idempotent.
