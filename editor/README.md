# Leviathan Layout Builder

Standalone visual editor for the **real** Leviathan UI. Not part of the main app docs.

## Start (Windows)

From `D:\leviathan\editor\` (or your repo clone):

Double-click `EDIT_LAYOUT.bat`

That starts:
- Editor API on http://127.0.0.1:5199 (reads/writes CSS)
- Real Vite frontend on http://127.0.0.1:5173 with the builder overlay

## How to edit

1. Click elements on the real layout (header, sidebar, cards, …)
2. Drag the yellow handles to resize
3. Use the right panel for padding / gap / sizes
4. The code panel updates live and **auto-saves** into:

`Data/frontend/src/styles/` (`tokens.css`, `leviathan.css`, `pages.css`, `chat.css`)

## Shortcuts

- `Ctrl+S` — force save
- `Esc` — deselect
- Top bar — toggle Edit / Panel / Code

## Note

Requires Node.js (npm) and Python 3. First run may run `npm install` in `Data/frontend`.
