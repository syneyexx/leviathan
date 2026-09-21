# HADES next implementation — P0 tool engine / chat / telemetry

**Branch:** `cursor/p0-tool-engine-chat-telemetry-7004`  
**Base HEAD:** `93dd8f94988064c56104dcac6b0ae14e4681edcd`  
**Historical scan baseline:** `5f25035538f12a2df2521c33a0cd167987ea0ab4`

## Work packages

### P0-UPLOAD — Plugin ZIP / .HadesPlugin import
- **Status:** PASS (tests)
- **Root cause:** Default deps install + `network_policy=block` hard-failed import; HTTPException swallowed to 400; LFS pointers opaque.
- **Fix:** Soft-skip deps with warning; preserve HTTPException; validate zip/LFS/empty; sanitize filename.
- **Evidence:** `PluginZipImportApiTests`, `PluginZipEmptyRejectTests`

### P0-A — Universal Tool Engine
- **Status:** PASS (unit/integration with fakes + Humanizer PluginManager E2E)
- **Root cause:** Text-only protocol; `content` empty raised before inspecting `tool_calls`.
- **Design:** `tool_protocol` state machine; `tool_registry` schemas/validation/exact discovery; `tool_engine` shared loop; native primary + text fallback; multi-tool per turn with `max_parallel_tool_calls`; discover hydration; MCP remote rows use same PluginManager spine; failure honesty (failed/timeout/cancelled/blocked).
- **Evidence:** `tests.test_tool_engine_p0` (40+), including 8-tool chain, Humanizer native E2E, parallel limit, discover, MCP spine, failure matrix.

### P0-CAP — Model tool capability detection
- **Status:** PASS (tests)
- **Design:** fingerprint(endpoint, model); invalidate on active model switch; no model-name hardcodes.
- **Evidence:** `ToolCapabilityCacheTests` + Humanizer native success path marks verified.

### P0-B — Chat repetition
- **Status:** PASS (regression)
- **Root cause:** `index_conversation` → knowledge search re-injected active transcript into system context while history already contained the turns (plus working_state goal).
- **Fix:** `filter_circular_knowledge(..., active_conversation_id=...)` + treat `conversation`/`conversation:` URI as derived.
- **Evidence:** `ChatRepetitionTests`; regenerate/`revise_message_id` single user-turn; FE optimistic replace + provisional stream source contracts.

### P0-C / P1 — Live usage telemetry
- **Status:** PASS (API + UI wired)
- **Design:** `usage_telemetry` process snapshot; SSE `model_usage`; Chat `ModelUsageCard` with CURRENT/PEAK/TOTAL sparkline; exact vs estimate vs unavailable labeled. Peak/session are process-local (survive React rerenders, reset on process restart).
- **Evidence:** `ChatTelemetryApiTests`, `UsageEstimateAndStatusTests`; typecheck green.

## Host
- LM Studio live native tools: UNVERIFIED_ON_HOST in this environment.

## Verification
- `backend.tests.test_tool_engine_p0` → **40 PASS**
- `python3 verify_hades.py --quick` on `3f08897` → **[OK]** (660 tests, 7 skipped)
- Live LM Studio → UNAVAILABLE / UNVERIFIED_ON_HOST
- MAIN push → not performed until PR CI green + merge authority
