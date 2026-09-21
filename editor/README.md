# Leviathan Visual Builder (admin tool)

Losstaande full-freedom layout editor over de **echte** Leviathan UI.
Hoort **niet** bij de normale Leviathan-start.

## Start de editor

```
D:\leviathan\editor\EDIT_LAYOUT.bat
```

Opent http://127.0.0.1:5173 met de visual builder overlay.

## Start Leviathan zonder editor

Gebruik je normale start (`run_leviathan.bat` / installer / build).
Dan zie je **geen** editor-UI — wel al je opgeslagen wijzigingen.

## Capabilities

- Vrije layout: drag, 8-handle resize, rotate, multi-select (Shift), reparent (drop-zones)
- Snap + guides + optioneel grid; aspect lock; min/max constraints
- Dockable panels: Inspector, Layers, Assets, Insert, Tokens, Code, History
  (slepen / float / dock L-R-B / tabs / maximize; presets in `localStorage`)
- Insert: tekst, titel, image, knop, divider, spacer, frame, custom HTML
- Styles + live tokens.css; shell regio-sliders (header/sidebar/right/footer)
- Inline text, image upload/library/replace, undo/redo, lock, group/ungroup
- Shell containers (`.lv-app`, `.lv-body`, …) blijven protected

## Wat wordt opgeslagen (blijft in Leviathan)

| Actie | Bestand |
|------|---------|
| Maten, kleuren, styles | `Data/frontend/src/styles/*.css` |
| Tekst / image-paden (waar mogelijk) | bron-`.tsx` via replace |
| Overrides + nieuwe widgets | `Data/frontend/public/lv-editor-content.json` |
| Geüploade images | `Data/frontend/public/assets/uploads/` |

In normale Leviathan laadt `editorContentRuntime.ts` alleen
`lv-editor-content.json` — geen editor-UI.

## Scheiding

- Editor alleen bij `LEVIATHAN_EDITOR=1` (via `EDIT_LAYOUT.bat`)
- Vite-plugin `apply: "serve"` → zit niet in production build overlay
- API op `127.0.0.1:5199`; writes alleen binnen `Data/frontend`
