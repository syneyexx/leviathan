# LEVIATHAN STUDIO — eindrapport

Datum: 2026-09-22  
Branch: `cursor/leviathan-studio-ac7e`  
Basis: `main` / `e701e0a`

## Wat is veranderd

P0 documentintegriteit: `clearStyles` (BEGIN/END), save-coordinator met revisie/queue/conflict, stabiele node/shell-identiteit (v3), scoped patch-history (cross-page undo), globale bron-textreplace uit (410), API sessie+Origin+atomische writes.

Studio-shell: mission-control tokens (grafiet/ijsblauw), nieuwe compositie (48px bar, 44px rail, docks, statusbar), SVG-iconen, Design/Preview viewport, Problems/History/Pages panels, wave-capabilities (stress lab, branches, recipes, recovery, HUD, …).

Runtime: `editorContentRuntime.ts` respecteert `node:` / `shell:` keys en `data-lvb-node`.

## Aantoonbaar getest

```
node --test editor/test/*.mjs   → 30 pass
python3 editor/test/test_api.py → ok (401/403/409/410/501/save)
```

Browser/GPU/Windows-start: **niet** in deze omgeving geverifieerd tot Vite+deps beschikbaar; capability matrix markeert die items als implemented but unverified.

## Blockers / beperkingen

- AI blijft **unavailable** (geen modelcontract) — eerlijke 501 + review UI
- Preview-iframe deelt editor-env; nested chrome wordt verborgen, geen aparte productie-preview-build
- Multi-file save is journal/rollback, niet single-syscall atomair
- Visuele polishronde op echte desktopformaten vereist lokale `EDIT_LAYOUT.bat`
- Performance fixtures 1000/5000 nodes: niet gemeten op hardware in deze run

## Geen claims

Geen “100/10” of “production ready” op alleen unit-tests.
