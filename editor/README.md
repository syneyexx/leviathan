# Leviathan Layout Editor

Standalone visual editor for the Leviathan UI layout. Not part of the main app build.

## Start

Double-click `EDIT_LAYOUT.bat` (Windows), or:

```bash
python3 editor/server.py
```

Open http://127.0.0.1:5199

## What it does

- Live preview of the Leviathan shell (header / sidebar / content / right panel / footer)
- Edit `tokens.css`, `leviathan.css`, `pages.css`, `chat.css` with instant preview
- Drag layout edges or use sliders — the CSS updates immediately
- Save writes back to `Data/frontend/src/styles/`

## Shortcuts

- `Ctrl+S` — save dirty files
- Click a zone in the preview to select it
- Viewport chips — test Desktop / 1280 / 1024 / Tablet widths
