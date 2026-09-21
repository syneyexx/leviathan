# Leviathan Visual Editor (admin tool)

Losstaande admin-tool om de **echte** Leviathan-layout te bewerken.
Hoort **niet** bij de normale Leviathan-start.

## Start de editor

```
D:\leviathan\editor\EDIT_LAYOUT.bat
```

Opent http://127.0.0.1:5173 met de Dreamweaver-achtige overlay.

## Start Leviathan zonder editor

Gebruik je normale start (`run_leviathan.bat` / installer / build).
Dan zie je **geen** editor-UI — wel al je opgeslagen wijzigingen.

## Wat wordt opgeslagen (blijft in Leviathan)

| Actie | Bestand |
|------|---------|
| Maten, kleuren, styles | `Data/frontend/src/styles/*.css` |
| Tekst / image-paden (waar mogelijk) | bron-`.tsx` via replace |
| Overrides + nieuwe widgets | `Data/frontend/public/lv-editor-content.json` |
| Geüploade images | `Data/frontend/public/assets/uploads/` |

In normale Leviathan laadt een kleine runtime (`editorContentRuntime.ts`)
alleen `lv-editor-content.json` — geen editor-UI.

## Functies (editor)

- Sleep · resize · snap · nudge (pijltjes)
- Rechtsklik-menu · copy/paste/duplicate/delete/lock/align
- Insert: tekst, titel, image, box, knop, lijn
- Image upload / drop vanuit Explorer
- Layers · Undo/Redo · inline tekst
- Auto-save (Ctrl+S forceert)

## Scheiding

- Editor alleen bij `LEVIATHAN_EDITOR=1` (via `EDIT_LAYOUT.bat`)
- Vite-plugin `apply: "serve"` → zit niet in production build overlay
- Leviathan blijft een aparte app; editor is admin tooling
