# Leviathan Visual Builder

Standalone full visual editor for the **real** Leviathan UI (website-builder style).

## Start (Windows)

From `D:\leviathan\editor\`:

Double-click `EDIT_LAYOUT.bat`

Opens the real app at http://127.0.0.1:5173 with the builder overlay.

## What you can edit

- **Tekst** — klik + bewerk in panel, of **dubbelklik** direct op de layout
- **Images** — URL plakken of bestand uploaden
- **Layout** — sleep gele handles (header / sidebar / panels)
- **Styles** — kleur, font, padding, border, shadow, background, display, …
- **Verberg/toon** elementen

Alles auto-save’t naar:
- `Data/frontend/src/styles/` (CSS)
- `Data/frontend/public/lv-editor-content.json` (tekst/images)
- bron-`.tsx` bestanden wanneer tekst/image-paden matchen

Uploads komen in `Data/frontend/public/assets/uploads/`.

## Shortcuts

- `Ctrl+S` — force save
- `Esc` — deselect
- Dubbelklik — inline tekst edit
- Enter — inline edit afronden
