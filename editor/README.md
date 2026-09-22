# Leviathan Visual Editor

Admin-studio om de echte Leviathan-layout te bewerken. Hoort niet bij de normale start.

```
EDIT_LAYOUT.bat
```

Opent http://127.0.0.1:5173 met de overlay. API: http://127.0.0.1:5199.
Zonder `LEVIATHAN_EDITOR=1` is er geen editor-UI. Opgeslagen wijzigingen blijven wel staan.

## Zonder editor

Gebruik de normale start (`run_leviathan.bat` / installer / build).
Dan is er geen editor-UI. `editorContentRuntime.ts` laadt alleen `lv-editor-content.json`.

- Editor alleen bij `LEVIATHAN_EDITOR=1` (via `EDIT_LAYOUT.bat`)
- Vite-plugin `apply: "serve"` — geen overlay in een production build
- API op `127.0.0.1:5199`; writes alleen binnen `Data/frontend`

## Architectuur

`canvas.js` is de enige inject (`type="module"`). De rest zijn plain ES-modules die `server.py` statisch serveert. Geen build-step voor de editor zelf.

| Module | Rol |
| --- | --- |
| `js/state.js` | store |
| `js/commands.js` | undo/redo max 100, gestures on pointer-up; export/import stack per page |
| `js/selection.js` | primary + multi, shell, deep-select |
| `js/geometry.js` | `resizeRect`, guides, spacing, measure, snap, align |
| `js/layout.js` | `ensureFreeTransform`, capture, commit, align/nudge |
| `js/interactions.js` | pointer machine (unchanged contract) |
| `js/camera.js` | zoom 0.1×–8×, pan, fit |
| `js/scene-graph.js` | screen-space drawable primitives |
| `js/renderer-webgpu.js` | WebGPU instance rects + Canvas2D labels |
| `js/renderer.js` | paint facade: WebGPU when available, DOM/CSS fallback |
| `js/diagnostics.js` | FPS / heap / GPU samples + JSON schema |
| `js/pages.js` | SPA route switcher; per-page history + selection stash |
| `js/chrome.js` | docks, page switcher, session mirrors → renderer |
| `js/widgets.js` | insert, group, flip, components, Alt-duplicate |
| `js/panels/*` | inspector, layers, components, diagnostics, AI, help… |

Shell (`.lv-app .lv-body .lv-header .lv-sidebar .lv-footer .lv-right .lv-main`) wordt niet verwijderd of verplaatst. Maten via CSS-variabelen.

### Paint path (Option B)

1. Interactions / selection / camera update session + store.
2. `chrome.schedulePaint()` → rAF → `renderer.paint(ui)`.
3. Renderer builds a screen-space scene-graph (selection, handles, guides, marquee, measure, drop, labels).
4. **WebGPU** draws solid instances; labels on a Canvas2D overlay. DOM selection box stays hit-only for pointer capture.
5. Without `navigator.gpu` / adapter / device → identical visuals via DOM/CSS (`paintDomFallback`).
6. Pixel + 12-column grids remain camera-synced DOM layers (zoom-aware).

## Page / route switcher

Top bar: quick links (Command / Chat / Research / Settings) + **Pagina** `<select>` with every Leviathan SPA route (`/`, `/chat`, `/coding`, `/research`, `/settings`, media, agents, …).

- Navigates via `history.pushState` + `popstate` so React stays mounted and app behaviour (chat, research, LLM, …) keeps working.
- Content overrides re-apply after route paint.
- Undo history, selection keys, and camera are **scoped per pathname**.
- Shell protection rules unchanged on every page.

Command palette: `Pagina: …` entries under group **Pagina's**.

## Diagnostics

Right dock tab **Diagnostics** (`Mod+Alt+D`):

- Live sparklines: FPS, frame ms, scene nodes, JS heap
- Editor counters: selection, guides, content nodes, history depth, dirty / auto-save, page, phase
- GPU: adapter info, draw count, VRAM estimate (when WebGPU active)
- Full JSON schema: **Kopieer JSON**

## Free-transform model

Werkt op de **live DOM**:

- Shell → CSS variables only
- Widgets / promoted page nodes → absolute box via `ensureFreeTransform` (geen sprong)
- Persistence via `content.applyProp` / `commitBox` (entries + nodes)
- Camera transform op `#root` nooit opgeslagen
- Resize schrijft `width`/`height` — nooit `transform: scale()` op het element
- Rotated resize (MVP): axis-aligned op geschreven box

## Shortcuts & gestures

| Toets | Actie |
| --- | --- |
| `V` `H` `R` `M` | select, hand, rotate, measure |
| Spatie / middelste muis | pan |
| Ctrl/Cmd + scroll | zoom naar cursor (0.1×–8×) |
| `0` `1` `2` | 100%, breedte, selectie |
| Cmd/Ctrl+K / S / Z | palette / save / undo |
| Cmd/Ctrl+G / Shift+G | group / ungroup |
| Cmd/Ctrl+Alt+D | Diagnostics-paneel |
| **Shift + resize** | aspect lock |
| **Alt + resize** | from center |
| **Alt + drag start** | duplicate then move |
| **Ctrl/⌘ + drag** | reparent widgets |
| **Alt + hover** | spacing measure tussen selectie en hover |
| Shift + rotate | 15° |
| Rotate-handle boven selectie | zonder R-tool |
| Pijltjes / Shift | nudge 1 / 10 |
| F2 in lagen | hernoemen |

## Frontier capabilities

- WebGPU scene-graph chrome with DOM fallback
- Page switcher for every Leviathan route; app stays live
- Diagnostics: FPS / GPU / heap graphs + schema
- Smart guides: edge, center, equal-spacing, parent/frame, viewport; labels bij spacing
- Selection chrome: 8 handles, rotation handle, multi outlines + shared AABB, dims in statusbar
- Inspector: multi-select mixed values (“Gemengd”), batch apply, typography, tokens, X/Y/W/H/rotate
- Layers: type icons, rename, before/after/into drop, virtualization, context menu
- Components: variants, detach, override-preserving master update
- Measure: live rubber-band + orthogonal dims; Alt-hover element gaps
- AI: selection scope, graceful 501, undo-backed apply
- Docks: Studio / Focus / Code / Full; float positions restored

## Persistence

| Actie | Bestand |
| --- | --- |
| Desktop styles | `Data/frontend/src/styles/*.css` |
| Content / widgets / breakpoints | `Data/frontend/public/lv-editor-content.json` |
| Uploads | `Data/frontend/public/assets/uploads/` |

Breakpoint decls → JSON only. Zoom/pan nooit opgeslagen. Save contract unchanged.

## Tests

```bash
cd editor && node --test test/core.test.mjs test/resize.test.mjs
```

## Manual QA

1. Insert image → right handle: width↑, height same  
2. Left handle: right edge pinned, no fly-left  
3. Min-size clamp: no walk  
4. Corner + Shift: aspect; Alt: from center  
5. Zoom 50%/200% + pan: same layout math  
6. Page `<img>` promote: no jump on pointerdown  
7. Alt-drag duplicates; Ctrl-drag reparents  
8. Rotate handle works; Shift snaps 15°  
9. Multi-select inspector shows Gemengd / batch writes  
10. Layers rename + into-drop  
11. Save / reload persists box + rotate  
12. Shell region resize still CSS vars  
13. Pagina-switcher: `/chat` → edit → terug naar `/` zonder SPA reload; undo scoped per page  
14. Diagnostics toont backend (`webgpu` of `dom`) + live FPS  
15. Browser zonder WebGPU: DOM chrome identiek  

## CHANGELOG — frontier studio

### WebGPU scene-graph (Option B)
- Custom ES-module WebGPU paint path (`renderer-webgpu.js` + `scene-graph.js`); no Pixi/bundler
- Progressive enhancement: graceful DOM/CSS fallback when GPU missing
- Hit-only DOM handles preserve pointer capture while GPU draws chrome
- Camera / zoom / pan drive screen-space scene correctly; grids stay zoom-aware DOM

### Full-page editing
- Route switcher for every Leviathan SPA page; React app stays fully functional
- Per-page undo history, selection restore, camera stash
- Content overrides + shell rules re-applied after navigation

### Diagnostics
- Live FPS / frame / heap / scene-node sparklines
- GPU adapter / draw / VRAM schema + copyable JSON
- Dock tab + `Mod+Alt+D`

### Transform & precision
- Opposite-edge `resizeRect` (P0 west-fly / east-scale fixed)
- Free-transform promote without visual jump
- Rotation handle on selection chrome; live angle
- Zoom range 0.1×–8×; fit to multi-select union
- Guides: spacing + equal-distance + parent/viewport; resize snap
- Alt-duplicate, Ctrl-reparent, Alt-hover measure, live measure rubber-band

### Inspector & layers
- Multi-select mixed values + batch property apply
- Typography: text-transform, text-decoration
- Layers: icons, F2 rename, before/after/into DnD, virtualization, context menu

### Components & AI
- Variant map, detach instance, override-preserving master update
- AI panel: scope label, 501 handling, undo apply

### Chrome & polish
- Status bar: dims + dirty pulse
- Shared multi-select AABB
- Float restore; Full dock preset
- Help rows runnable; gesture legend

Boot model unchanged: one `canvas.js` inject, `EDIT_LAYOUT.bat` → :5199 + :5173, no production overlay.
