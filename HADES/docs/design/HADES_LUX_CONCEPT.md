# HADES Lux Atelier — product GUI concept

Reference: [`hades-lux-concept.png`](./hades-lux-concept.png)

## Intent

Exclusive luxury, professional, calm local AI workspace. Lux Atelier is the
**sole** product shell. Obsidian / BETA / BETA 2 are retired.

## Palette

| Role | Value |
|---|---|
| Canvas | `#070708` |
| Panel | `#101114` / `#161418` |
| Champagne | `#B8955A` |
| Text | `#F1EDE3` |
| Muted | `#8F97A3` |
| Online | `#3D9B78` |

## Layout

1. Left menu — HADES Atelier brand + Werk / Kennis / Systeem (all pages)
2. Top bar — breadcrumb, search, model chip, lokaal-online
3. Main — full product pages (Chat keeps conversation + context rails)

## Product mapping

- Shell: `components/hades/lux/lux-shell.tsx`
- Pages: `components/hades/pages/*` (unchanged product logic)
- Styles: `components/hades/styles/lux/`
