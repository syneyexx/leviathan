# Leviathan Studio (visual editor)

Admin studio to edit the real Leviathan layout. Not part of normal app start.

```bat
EDIT_LAYOUT.bat
```

Opens http://127.0.0.1:5173 with the overlay. API: http://127.0.0.1:5199.
Without `LEVIATHAN_EDITOR=1` there is no editor UI. Saved content still applies via `editorContentRuntime.ts`.

## Without editor

Use normal start (`run_leviathan.bat` / installer / build). No editor chrome. Camera transforms are never persisted into document CSS.

## Start / test / verify

```bash
# API smoke (no Vite, temp content)
python3 editor/test/test_api.py

# Unit / regression
node --test editor/test/core.test.mjs editor/test/resize.test.mjs editor/test/studio.test.mjs

# Full studio (Windows)
editor\EDIT_LAYOUT.bat

# Full studio (Linux/mac — from repo root)
LEVIATHAN_EDITOR_NO_BROWSER=1 python3 editor/server.py
# then open http://127.0.0.1:5173
```

Visual checklist: workspace overview, selection+inspector, layers/components, Design/Preview breakpoints, command palette (⌘K), save conflict, AI unavailable state. Screenshots: `editor/artifacts/` when captured.

## Architecture

See `docs/ARCHITECTURE.md`, `docs/STUDIO_PLAN.md`, `docs/CAPABILITY_MATRIX.md`.

| Module | Role |
| --- | --- |
| `js/identity.js` | Stable node/shell keys, v2→v3 migration |
| `js/patches.js` | Scoped history patches |
| `js/save.js` | Save coordinator + revision queue |
| `js/studio/viewport.js` | Design vs Preview iframe |
| `js/capabilities/*` | Issues + capability registry |
| `js/studio/features.js` | Stress lab, branches, recipes, recovery, … |
| `server.py` | Session auth, transactional save, no global text replace |

Shell (`.lv-app` …) is never deleted or reparented. Free-transform widgets use `data-lvb-node` / `data-lvb-id`.
