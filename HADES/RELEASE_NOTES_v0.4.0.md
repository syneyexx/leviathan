# HADES v0.4.0 Release Notes

## Nieuw
- Persistente chat rename.
- Per-chat system prompt override met globale Settings-fallback.
- Persistente modelkeuze per chat.
- Centrale globale system prompt en actieve bot-inferenceparameters in Settings.
- Multi-round autonome Plugin Tool Router.
- Automatische web-refresh voor actuele vragen wanneer netwerk expliciet op Allow staat.
- Pluginlabels/categorieën in API + GUI.
- JSON of CLI-input bij handmatige Plugin-tooluitvoering.
- Automatische plugin-dependency voorkeur vanuit Settings.
- Extra geplande agents zichtbaar met `(*)`.
- Expert Research uitgebreid tot grotere, instelbare evidence-cycli/mastery-target.
- PPTX + XLSX/XLSM research/knowledge extractie.
- SQLite online backup API in plaats van een gewone file-copy.
- One-click `HADES.bat`, Python launcher en optionele Windows `HADES.exe` builder.

## Verification in build environment
- 18/18 Python backend tests passed.
- 6/6 source-contract tests passed.
- Python compileall passed.
- 78 TypeScript/TSX sources parsed without syntax diagnostics.
- Local TypeScript/CSS import graph check passed.
- package.json/package-lock root dependency contract passed.

## Environment limitation
De sandbox waarin deze ZIP is gebouwd heeft geen npm-registry tarball-cache voor Vite 8.0.13, waardoor `npm ci` en dus de echte Vite/typecheck-run hier niet opnieuw uitgevoerd konden worden. Op Windows voert `PREPARE_HADES.bat` die checks verplicht uit en stopt het bij iedere frontendfout.
