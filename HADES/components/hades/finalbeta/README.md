# FINALBETA — pixel-reference interface

FINALBETA is the isolated visual HADES interface based on the canonical `hades-pixel-ui-v3` reference. This stage is intentionally **visual-first**: pages must exist and remain selectable before production capabilities are migrated into them.

## Entry

- Mounted from `HadesApp` when `ui_style === "finalbeta"`.
- Select via Settings → Interface → **FINALBETA**.
- Switch back via FINALBETA Settings → Interface → **HADES Lux**.
- Hash namespace: `#/fb/<page>`.
- Default start page: **Dashboard** under HOOFDMENU **Hades AI**.

## Navigation

- **HOOFDMENU** (top): Hades AI · LLM · Media Control · TradingCenter · Onderzoek & kennis · Plugin & Runtime
- **SUBMENU** (bottom): depends on the active HOOFDMENU section
- Clicking a HOOFDMENU item opens that section’s home page and swaps the SUBMENU

### Sections

| HOOFDMENU | Home | SUBMENU |
|---|---|---|
| Hades AI | Dashboard | Chatten, Coding, Mission Control, Taken |
| LLM | Modellen | Modellen, Model training, Agents |
| Media Control | Media dashboard | Overzicht, Youtube, Tiktok, Instagram, Facebook |
| TradingCenter | Trading | _(geen submenu)_ |
| Onderzoek & kennis | Research | Research, Brain, Geheugen, Knowledge Library, Evidence Vault, Bestanden |
| Plugin & Runtime | Performance | Performance, Instellingen, Plugins, MCP, Workflows |

## Visual contract

The canonical comparison viewport is **1536 × 864 at 1× DPR**. FINALBETA remains quarantined from Lux/Tailwind global CSS. Navigation IA may evolve; do not casually alter shell geometry, tokens or page layouts unless the task requires it.

## Structure

- `finalbeta-app.tsx` — isolated app entry and route renderer.
- `shell/finalbeta-shell.tsx` — HOOFDMENU, scenic rail, inspector, status bar and section SUBMENU.
- `routes.ts` — page ids + `FINALBETA_HOOFDMENU` map.
- `pages/*` — page bodies and inspectors (new entries may be Phase 1 placeholders).
- `styles/finalbeta/*` — scoped FINALBETA styles.
