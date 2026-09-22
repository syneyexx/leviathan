# LEVIATHAN STUDIO — Execution Plan

Scan basis: `main` / `e701e0a`. Primary work in `editor/`. Outside changes only for identity + viewport + runtime persistence.

## Inventory (verified)

| Area | Status |
| --- | --- |
| Commands / gestures / resize / zoom-pan | Present |
| Layers, inspector, tokens, docks | Present |
| WebGPU + DOM fallback | Present |
| `clearStyles` BEGIN/END | **Broken** (P0) |
| Save queue / revision | **Missing** (P0) |
| History vs pages | **Broken semantics** (P0) |
| Stable node identity | **Weak** (P0) |
| Global text replace | **Unsafe** (P0) |
| API auth / CORS | **Open** (P0) |
| Real viewport media queries | **Missing** (P1) |
| AI | Honest 501 |

## Order

1. **P0 integrity** — identity, patch history, save coordinator, API harden, kill implicit source replace, clearStyles
2. **Studio shell** — token layer, chrome composition, icon set, status/save states
3. **P1 direct manipulation** — gesture cancel, pointer lifecycle, free-position mode, diagnostics honesty
4. **P1 viewport** — Design vs Preview iframe bridge
5. **Shared registries** — issues, capabilities, checks, recipes, fixtures
6. **Waves 1→3** — Stress Lab → Constraints → Problems → History → Compare → Branches → States → Fixtures → Tokens → AI modes → Recipes → Handoff → HUD → Recovery
7. **Verify** — unit/API/browser acceptance + screenshots + capability matrix

## Architecture decisions

- **Identity**: document v3 with `nodeId` (`data-lvb-node`), `page`, `scope` (`page` \| `global-shell` \| `component-master`). Legacy selector keys migrate; ambiguous matches surface in Problems.
- **History**: one global stack; undo/redo apply **scoped patches** (entry keys / nodes / file deltas), never full-doc restore that clobbers other pages.
- **Save**: single coordinator — active save + queued newest revision, dirty while in-flight edits, optimistic concurrency (revision+hash), server lock + temp/replace, CSS+JSON journal.
- **Text**: visual edits write to content entries only; `/api/replace-text` disabled for editor visual path.
- **Preview**: Design = live DOM; Preview = same-origin iframe sized to viewport so media queries match runtime.
- **AI**: unavailable until model contract exists; Generate → Review → Apply only.

## Outside `editor/` (only if required)

- `Data/frontend/src/editorContentRuntime.ts` — node-id apply + v3
- Vite/plugin unchanged unless session token handoff needs it
