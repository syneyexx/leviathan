# Coding OmniRoute (optional)

OmniRoute is an **optional** model-routing backend for HADES Coding. It is off by default. Chat, Trading, Media and the normal LM Studio path are unchanged.

## What the toggle does

On the Coding page:

**Use OmniRoute** `[toggle]`

- **Off:** Coding uses the existing LM Studio / configured coding model. Same orchestration, tests and verification as before.
- **On:** Coding still runs the existing specialists and context compiler. Each coding model call is sent to a discovered OmniRoute OpenAI-compatible route instead of (or, on failure, falling back from) the normal coding model.

Model selection happens **in code**, not in the coding prompt. The coding model never sees the OmniRoute catalog.

## Requirements

The toggle is usable only when the OmniRoute plugin is **in the Plugin Manager registry** and:

1. the plugin exists (installed/imported — not merely `plugins/omniroute/` on disk)
2. it is **enabled**
3. status is **Ready** (no structural `failure_state`)
4. its `chat` / `complete` / `list_routes` tools are registered
5. trust / global policies / permissions allow autonomous use of its network+subprocess tools (network tools require **verified** trust)

| State | Toggle | Status |
|---|---|---|
| Not installed | disabled | OmniRoute plugin not installed |
| Installed, disabled | disabled | Enable OmniRoute in Plugins |
| Installed, not Ready | disabled | Actual reason (`status=…`, `failure_state=…`, trust) |
| Enabled + Ready | available | OmniRoute ready |

## Routing

1. Coding request (existing classification / specialists).
2. Cheap structured requirements from the specialist role (investigation prefers large context, implementation prefers high coding strength, and so on). No extra LLM call.
3. Cached `list_routes` discovery (OpenAI-compatible `/models` on local LM Studio plus operator-configured extra URLs).
4. Deterministic pick: explicit coding `model_id` if present in inventory, else auto among **eligible** routes.
5. Completion via OpenAI-compatible `POST /chat/completions` on the selected route.
6. Existing coding execution, tests and verification.

Remote (non-loopback) routes are excluded unless `models.allow_cloud_fallback` is enabled. Privacy policy is not bypassed by turning OmniRoute on.

If OmniRoute does not report the final backend model, the UI shows **OmniRoute · Auto** rather than guessing.

Streaming: Coding already awaits a full completion object. The OmniRoute coding path is non-streaming (honest limitation).

## Fallback

Control setting `coding.omniroute.allow_fallback` (default **true**).

When OmniRoute was requested but cannot complete (missing plugin, not Ready, unreachable, no eligible route, auth, rate limit, timeout, provider error):

- fallback permitted → normal coding model is used; job state records `fallback_used` and `fallback_reason`
- fallback disabled → honest failure (`RuntimeError` with the status code)

A cancelled coding job does not start a new OmniRoute completion after the cancel checkpoint.

## Token efficiency

- Full inventory is **never** inserted into coding prompts (0 catalog tokens).
- Routing adds **0 extra LLM calls**.
- Discovery/health are TTL-cached (`coding.omniroute.inventory_cache_ttl_seconds`, default 30s) and invalidated on plugin registry generation and provider failure.
- Specialists still use the existing coding context compiler (repo map, relevant files, diffs, failures) — OmniRoute does not dump the repository or plugin catalog.

## Secrets and observability

API keys stay in environment / provider settings. They are redacted from job status, events, routing snapshots, errors and UI payloads.

Bounded job metadata:

- OmniRoute requested / available / used
- routing mode auto or selected
- selected model/provider when reported
- local or remote
- fallback yes/no + reason

## Debugging

`GET /api/build/omniroute/status` — plugin-registry readiness for the toggle.

Coding job field `omniroute` and events `MODEL_ROUTING` — live routing snapshot (no secrets, no chain-of-thought, no raw API bodies).
