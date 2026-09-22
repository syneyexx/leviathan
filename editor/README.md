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
| `js/commands.js` | undo/redo max 100, gestures on pointer-up |
| `js/selection.js` | primary + multi, shell, deep-select |
| `js/geometry.js` | `resizeRect`, guides, spacing, measure, snap, align |
| `js/layout.js` | `ensureFreeTransform`, capture, commit, align/nudge |
| `js/interactions.js` | pointer machine |
| `js/camera.js` | zoom 0.1×–8×, pan, fit |
| `js/chrome.js` | docks, selection chrome, rotate handle, status |
| `js/widgets.js` | insert, group, flip, components, Alt-duplicate |
| `js/panels/*` | inspector (multi-select), layers, components, AI, help… |

Shell (`.lv-app .lv-body .lv-header .lv-sidebar .lv-footer .lv-right .lv-main`) wordt niet verwijderd of verplaatst. Maten via CSS-variabelen.

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

- Smart guides: edge, center, equal-spacing, parent/frame, viewport; labels bij spacing
- Selection chrome: 8 handles, rotation handle, multi outlines + shared AABB, dims in statusbar
- Inspector: multi-select mixed values (“Gemengd”), batch apply, typography transform/decoration, tokens, X/Y/W/H/rotate
- Layers: type icons, rename, before/after/into drop, ancestor-preserving search, virtualization >200, context menu
- Components: variants map, instance detach, local override preserve on master update, library previews
- Measure: live rubber-band + orthogonal dims; Alt-hover element gaps
- AI: selection scope, graceful 501, undo-backed apply
- Docks: Studio / Focus / Code / Full; float positions restored

## Persistence

| Actie | Bestand |
| --- | --- |
| Desktop styles | `Data/frontend/src/styles/*.css` |
| Content / widgets / breakpoints | `Data/frontend/public/lv-editor-content.json` |
| Uploads | `Data/frontend/public/assets/uploads/` |

Breakpoint decls → JSON only. Zoom/pan nooit opgeslagen.

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

## CHANGELOG — frontier studio

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
