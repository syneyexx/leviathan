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
7. Multimodal attachments use ArtifactStore IDs only. Chat resolves IDs into
   MultimodalSession / ContextBuilder `parts` (text inlined when readable; images as
   typed parts). Vision understanding is claimed only when a vision-capable path exists.
8. Historic assistant messages hydrate per-message `ChatTurn` metadata; live Activity
   remains on the active turn. Missing metrics stay UNMEASURED (never coerced to zero).
   Bounded `tool_calls` summaries may be stored on turn metadata for historic
   CapabilityResultCards; Activity is only re-shown when an activity projection was
   persisted (activity_ref alone does not invent a timeline).
9. Mobile drawers (history + inspector) are mutually exclusive, Escape/backdrop close,
   focus enters the panel, Tab is trapped, focus restores to the trigger.
10. Invariant A: cognition-owned responses skip the authoritative direct model call;
    `ResponseOwner` / `ExecutionPath` stay aligned (`cognition` ↔ `cognition_owned`).
11. CANCELLED ≠ FAILED end-to-end (durable turn state + UI streaming badge).
12. Cognition-owned SSE is honest when the runtime buffers the final answer: meta reports
    `streaming_degraded=true` / `degrade_reason=cognition_buffered_output` and emits a
    single public token plus operational events — never private CoT. Live incremental
    cognition tokens require CognitiveRuntime public-sink support when the provider can stream.
13. Historic turns surface `artifact_ids` as ArtifactStore links (no local filesystem paths).

## Consequences
- Old conversations/messages remain readable without turn rows.
- New turns hydrate per-assistant-message metadata on reload (including artifact refs).
- Startup reconciles stale ACCEPTED/RUNNING/STREAMING turns → INTERRUPTED.
- CANCELLED ≠ FAILED is durable and idempotent.
- Empty New Chat does not create a durable conversation until first Send (or scoped
  attachment requiring identity).
- Attachment MIME from the browser is treated as untrusted; server stores declared MIME
  as metadata and classifies artifact_type independently.
- Legacy `chat.css` (`.lv-chat-app`) remains imported for residual V1 chrome only;
  Chat V2 styles live exclusively in `leviathan-v2.css`.
