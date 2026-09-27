# Paper Trading Visual Spec

Canonical reference: `paper-trading-reference-screen1.png` (1536 × 1024).
Broken baseline: `paper-trading-broken-screen2.png`.

Baseline SHA at rebuild start: `86386fbb251849e9db946df75d97aef9bcee2e8d`.

## Root-cause of Screen 2 collapse

1. `PaperTradingPage` used `.lv-tp-wrap` / `.lv-tp-grid-*` without importing `trading-simulation-reference.css` (those rules lived only on SimulatiePage).
2. Page omitted `<main className="lv-main lv-tp-main">`, so it did not participate correctly in the wide AppShell body grid.
3. Content was a narrow session/order ticket, not the Screen 1 operator layout.

## Measured regions (reference 1536×1024)

| Region | Approx Y span | Height | Notes |
|--------|---------------|--------|-------|
| App chrome (outside page content) | 0–72 | ~72px | Preserve AppShell header/nav |
| Hero / page banner | 72–210 | ~138px (~13.5% of viewport) | Full content width |
| Symbol + timeframe toolbar | 210–252 | ~42px | Chips left, TF + tools right |
| Mid grid (chart + right rail) | 252–620 | ~368px | Chart ~58% / right ~42% |
| Lower data grid | 620–1024 | ~404px | Three columns |

### Mid grid

| Panel | Width share | Height share within mid |
|-------|-------------|-------------------------|
| Main chart | ~58% | 100% |
| Agent Orchestrator | ~42% | ~58% |
| Paper Portfolio | ~42% | ~42% |

### Lower grid

| Panel | Column | Notes |
|-------|--------|-------|
| Agent Fleet | left (~36%) | Dense table |
| Open Positions + Pending Orders | center (~32%) | Stacked |
| Performance + Risk + Activity | right/bottom | Perf+Risk bottom row; Activity spans |

Target CSS architecture uses explicit grid areas (no absolute page positioning):

```
hero
toolbar
chart | orchestrator
chart | portfolio
fleet | positions | activity
perf  | risk      | activity
```

## Spacing & chrome

| Token | Value |
|-------|-------|
| Panel gap | 10–12px |
| Panel padding | 10–12px |
| Panel radius | `var(--lv-radius-md)` (~8–10px) |
| Panel border | `1px solid rgba(214,169,87,0.22–0.35)` |
| Gold accent | `#D4AF37` / `var(--lv-gold-bright)` |
| Emerald positive | `#34d399` / `#50C878` |
| Cyan secondary | `#22c9d6` / `#00CED1` |
| Obsidian base | `#050706`–`#0a0c0b` |

## Typography

| Role | Font | Size | Tracking |
|------|------|------|----------|
| Hero title | `var(--lv-font-display)` (Cinzel-class) | clamp(28px, 3vw, 42px) | 0.28–0.32em |
| Hero kicker | display | 11–12px | 0.24em |
| Panel titles | sans | 10px uppercase | 0.12em |
| Metrics | sans / tabular | 13–22px | normal |
| Table cells | sans | 11–12px | normal |

## Chart panel

- Candle body + wick (emerald up / muted red down)
- Volume bars under price pane (~18% of chart height)
- MA overlays: 20 (cyan), 50 (gold), 200 (rust) — derived from bar closes client-side for display only
- Left tool rail ~36px
- Header: symbol, last, Δ, OHLC, Vol

## Responsive contract

- Primary: desktop ≥1280px faithful to reference proportions
- 1080p–ultrawide: fluid `fr` tracks; minmax(0,1fr) prevents empty collapse
- <1100px: stack mid columns; keep full-width panels (never a left strip void)
