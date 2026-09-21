# HADES FINALBETA v2 — volledige UI mockup

Standalone HTML/CSS mockup van **alle** FinalBeta-pagina's.
Niet geïntegreerd in de app — later porten naar de React shell.

## Pixel-referenties

| Pagina | Bestand |
|--------|---------|
| **Login** | [`login.html`](login.html) |
| **Dashboard** | [`pages/dashboard.html`](pages/dashboard.html) |
| **Training Control** | [`index.html`](index.html) |

## Openen

- **Index van alle pagina's:** [`hub.html`](hub.html)
- Lokaal serveren (aanbevolen ≥ 1440px breed):

```powershell
python -m http.server 8765 --directory docs/mockups/finalbeta-v2
```

Daarna: http://127.0.0.1:8765/hub.html

## Alle 26 FinalBeta-pagina's

Bron: `components/hades/finalbeta/routes.ts` → `FINALBETA_PAGES`

| Sectie | Pagina's |
|--------|----------|
| **Hades AI** | dashboard, chat, coding, mission-control, tasks |
| **LLM** | models, model-training, agents |
| **Media Control** | media, youtube, tiktok, instagram, facebook |
| **TradingCenter** | trading |
| **Onderzoek & kennis** | research, brain, memory, knowledge, evidence, files |
| **Plugin & Runtime** | performance, settings, tools, mcp, workflows, system |

Bestanden: `pages/<id>.html`

## Structuur

```
finalbeta-v2/
  hub.html                 # overzicht alle pagina's
  index.html               # Training Control (pixel reference)
  css/hades.css            # design system
  js/hades.js
  assets/
  pages/*.html             # 26 FinalBeta pages
  _generate-all-pages.mjs  # regenerate all pages
```

## Regenereren

```powershell
node docs/mockups/finalbeta-v2/_generate-all-pages.mjs
```

## Volgende stap

Als de mockup er goed uitziet → port naar `components/hades/finalbeta/` (React + CSS).
