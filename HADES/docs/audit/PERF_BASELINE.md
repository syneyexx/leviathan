# Performance baseline (frontend)

Recorded on Linux Cloud Agent, branch `cursor/astra-continuation-performance-2026-09-14`, `npm run build` (Vite 8).

## Bundle entry (main chunk)

| Snapshot | `index-*.js` (min) | gzip |
|---|---:|---:|
| Before template/CSS split (pre perf commit) | 644.37 kB | 188.44 kB |
| After template/CSS split | `index-DrvKoZu_.js` 233.68 kB + lazy `hades-app-*.js` 368.88 kB | 70.86 + 109.44 kB gzip |

Entry chunk reduced **644 → 234 kB** (~64%) by lazy-loading Obsidian/V3/V4/BETA shells.

## Notes

- **Production runtime:** when `dist/index.html` exists and `HADES_FRONTEND_MODE` is not `dev`, Windows launchers use `npm run start` (`vite preview` on port 3000). Dev remains `npm run dev`.
- **CSS:** Obsidian/V3/V4 styles load with their lazy shell chunks. BETA reference CSS stays eager in `main.tsx` because the multi-file cascade order is intentional for mockdata shell parity.
- **Training workspace:** job polling refreshes jobs only (3s, paused when `document.hidden`); capabilities/datasets use longer `staleTime` and invalidate on mutations.
