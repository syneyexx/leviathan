# HADES UI Style System

The default product GUI is **HADES Lux Atelier**.

`HadesApp` mounts `components/hades/lux/lux-shell.tsx` around the canonical
Classic product pages under `components/hades/pages/*` when `ui_style` is Lux.

An optional isolated Phase 1 visual variant **FINALBETA** lives under
`components/hades/finalbeta/` and is selectable from Settings → Interface.
FINALBETA is **not** the default and does not replace Lux functionality yet.

## Presets

| Preset | Setting value | Shell |
|---|---|---|
| HADES Lux | `ui_style = "lux"` (default) | `components/hades/lux/lux-shell.tsx` |
| FINALBETA | `ui_style = "finalbeta"` | `components/hades/finalbeta/finalbeta-app.tsx` |

Legacy stored values (`classic`, `obsidian`, `beta`, `beta2`) remain accepted by
the settings API for migration safety and are coerced to Lux in the UI provider.

## Motion

`motion_level`: `reduced` | `standard` | `cinematic`

Applied as `document.documentElement.dataset.motion`. `prefers-reduced-motion`
always wins.

## Architecture

```
AppSettings / UiStyleProvider
        │
        └─ HadesApp
              ├─ LuxShell (Werk / Kennis / Systeem)  [default]
              └─ FinalBetaApp (isolated Phase 1 shell)  [opt-in]
```

Styles:
- Lux: `components/hades/styles/lux/` (tokens, shell, pages-bridge), imported from `main.tsx`
- FINALBETA: `components/hades/styles/finalbeta/`, imported only by `FinalBetaApp` and scoped under `.fb-root`

Design references: `docs/design/hades-lux-concept.png`, `hades-pixel-ui-v3` (FINALBETA Phase 1).
