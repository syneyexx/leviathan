# Trading Center WAVE 2 — PRIMARY chrome densify + beyond-legacy wiring

**Depends on:** WAVE 1 scaffold  
**Branch base:** `cursor/trading-center-wave1-workspace-scaffold-3b35`

## Goals

1. Densify **PRIMARY** workspace chrome toward screenshot hierarchy (KPIs, ops panels, CTAs) using **backend-backed** values only — `UNMEASURED` when unknown.
2. Wire first beyond-legacy COMPLETE capabilities:
   - Candidate explainability drawer (Strategy Lab)
   - Agent / paper wallets panel (Trading Desk PRIMARY)
3. Keep WAVE 1 surface tabs (legacy embedded) as SECONDARY/ADVANCED fallback — no capability loss.
4. Still exactly **four** workspaces.

## Non-goals

- Pixel-perfect mock recreation with fake Bullish/High KPIs
- Deleting legacy modules
- Live trading enablement
- Full Q01–Q11 inspector polish (WAVE 3+)

## Deliverables

| Item | Workspace |
|---|---|
| Command Hub overview KPIs + CTAs + attention strip | Command Hub PRIMARY |
| Strategy Lab KPI strip + validation ladder teaser | Strategy Lab PRIMARY |
| Trading Desk wallets panel | Trading Desk PRIMARY |
| Candidate explain API client + drawer | Strategy Lab ADVANCED |
| Market Data KPI strip from indexed sources | Market Data PRIMARY |
