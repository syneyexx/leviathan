# Leviathan Studio — AI Editor Architecture (V5)

## Vision

OmniRoute Editor Gateway is the capability router between Studio, AI providers,
vision/image models, and a future MCP tool adapter. Image generation is the
flagship capability; the same contracts cover text rewrite, style analysis, and
allowlisted structured layout actions.

## Data flow

```
User
 → AI Inspector / command / context menu
 → Context Collector (Editor Context Protocol v1)
 → Snapshot Service (page / selection / region)
 → POST /api/editor-ai
 → OmniRoute Editor Gateway
 → Provider Registry (capability resolve + optional fallback)
 → Provider Adapter (mock | openai-images | openai-compatible text)
 → Normalized Editor Result Protocol v1
 → Preview State (non-destructive)
 → Accept → promote temp asset → commands.capture → save coordinator
```

Reject cleans temp previews and creates **no** history entry.

## Four layers

| Layer | Location | Role |
| --- | --- | --- |
| A. Editor Context Protocol | `js/ai/context.js`, `ai/protocol.py` | Versioned structured context |
| B. OmniRoute Editor Gateway | `ai/gateway.py`, `ai/providers/*` | Validate → route → normalize |
| C. Result / Action Protocol | `ai/protocol.py`, `ai/actions.py` | Preview kinds + allowlisted actions |
| D. Editor Tool Layer | `js/ai/tools.js` | Shared ops for UI + future MCP |

## OmniRoute relationship

HADES ships an **OmniRoute plugin** (`HADES/plugins/omniroute`) used optionally by
**Coding** for OpenAI-compatible LLM completions (`HADES/backend/coding_omniroute.py`).
That contract is coding-specific and does **not** expose image generation.

Studio therefore implements an **editor-facing OmniRoute gateway** with capability-based
provider adapters. It does not duplicate HADES coding routing, and does not pretend
the coding plugin is an image provider. Future binding can add an adapter that calls
a real multimodal OmniRoute without rewriting Studio contracts.

## Trust boundaries

- Loopback Studio API + session token + origin checks (unchanged)
- Provider secrets: env only; never returned in errors/UI/diagnostics
- Model output is untrusted: actions allowlisted; SVG sanitized; raster magic-bytes checked
- Temp AI previews live under `editor/.studio-ai-temp/` — not the permanent asset library
- Accept copies bytes through `/api/editor-ai/accept-asset` → `/assets/uploads/`
- Generation **must not** mutate `lv-editor-content.json` (server invariant check)
- No SSRF: image adapter requires `b64_json`; remote URL fetch refused
- WRITE_LOCK is **not** held during provider calls

## Preview lifecycle

```
GENERATED → TEMP PREVIEW → ACCEPTED → IMPORTED → APPLIED
                      ↘ REJECTED → CLEANED
```

Target fingerprint (`nodeKey`, page route, bounds, generation) is retained on the
preview. Selection changes do not retarget. Accept revalidates identity; missing
targets block apply.

## Visual snapshots

`js/ai/snapshots.js` rasterizes `#root` / selection via SVG `foreignObject` → canvas,
bounded to ≤1280px edge, JPEG-compressed. Studio chrome (`#lvb-root`) is refused.
Design vs Preview sources are explicit. Snapshots are ephemeral request context —
not history, not autosave, not permanent assets.

## Providers

| Provider | Enable | Capabilities |
| --- | --- | --- |
| `mock` | `LEVIATHAN_EDITOR_AI_MOCK=1` | `image.generate`, `image.variation`, text, analyze (deterministic placeholders, labeled MOCK) |
| `openai_images` | `LEVIATHAN_EDITOR_AI_IMAGE_ENDPOINT` + API key | `image.generate` only (no true edit/outpaint in this adapter) |
| `openai_compatible_text` | `LEVIATHAN_EDITOR_AI_*_LLM_*` or `LEVIATHAN_LLM_*` | `text.*`, `layout.reason` |

Unavailable capabilities are reported honestly via `GET /api/editor-ai/capabilities`.

## MCP readiness

`js/ai/tools.js` exposes a stable tool surface (`get_selection`, `capture_*_snapshot`,
`generate_asset`, `accept_preview`, …). Do **not** expose an unrestricted MCP server yet.
A future adapter should map MCP tools → this layer → preview → approval policy.

## Endpoints

| Method | Path | Notes |
| --- | --- | --- |
| GET | `/api/editor-ai/capabilities` | Discovery (origin-checked) |
| POST | `/api/editor-ai` | Generate / analyze (session) |
| POST | `/api/editor-ai/cancel` | Client abandon (honest: provider may not cancel) |
| GET | `/api/editor-ai/preview/:id` | Temp preview bytes |
| POST | `/api/editor-ai/preview/cleanup` | Cleanup temps |
| POST | `/api/editor-ai/accept-asset` | Promote temp → uploads (no doc mutation) |

## Limitations (honest)

- True image edit / outpaint / background removal: protocol + UI exist; **no real provider wired** → unavailable
- Layout/component generation: action schema validated; real LLM path optional; mock does not invent layout actions
- Browser snapshot quality depends on SVG foreignObject support; failures degrade honestly
- Real OpenAI Images smoke is optional and not part of the default suite
- HADES Coding OmniRoute is a separate boundary

## Tests

```bash
python3 editor/test/test_ai_gateway.py
python3 editor/test/test_api.py
python3 editor/test/test_concurrency.py
node --test editor/test/*.mjs
```
