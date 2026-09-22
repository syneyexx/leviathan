# FRONTIER execution ledger

Baseline revision: `d66c044` (predecessor PR #48).  
Working branch: `cursor/editor-frontier-daad`.  
Reference scan commit (findings origin): `19cbdd3`.

## Existing work retained (predecessor #48)

| Area | Status | Evidence |
| --- | --- | --- |
| `geometry.resizeRect`, group resize, min/max, opposite-edge, aspect, keyboard resize | verified (unit) | `editor/test/resize.test.mjs` |
| Selection HUD, zoom handles, equal-spacing guides, gesture cancel wiring | implemented but unverified (browser) | retained; draft restore strengthened |
| Image replace / bg-image / upload progress / asset meta | partial → improved | replaceText removed in #48; async target token added |
| Dark graphite/ice-blue chrome | implemented but unverified | retained |
| Stress fixtures / crash draft hooks | partial | stress still container probe |

## P0 status after this run

| ID | Status | Evidence |
| --- | --- | --- |
| P0-A Save queue / generations | **fixed + verified** | `js/save.js`, `test/save.test.mjs` (8) |
| P0-B Server race / journal | **fixed + verified** | `server.py`, `test_concurrency.py`, `test_api.py` |
| P0-C Structural patches | **fixed + verified** | `js/patches.js`, `test/patches.test.mjs` |
| P0-D Gesture DOM restore | **fixed + unit verified** | `js/gesture-draft.js`, layout promote rollback, autosave skip while gesturing; browser unverified |
| P0-E Image async identity | **partial → improved** | `widgets.replaceImageWithUrl` captures target key/el at upload start |

## Checks executed

```
node --test editor/test/*.mjs          → 56 pass
python3 editor/test/test_api.py        → ok
python3 editor/test/test_concurrency.py → ok (200+409, file contract, journal rollback)
```

Browser screenshots / Windows / GPU: **not run** this environment.

## Durability honesty

Journal + per-file `os.replace` is **not** a single filesystem transaction. Startup rolls back incomplete journals. Threading `WRITE_LOCK` is not inter-process; process lock file refuses a second API process on the same project. Client FNV `hashDocument` is diagnostic only — concurrency token is always the server SHA-256 hash from acknowledgements.

## Open limitations / next concrete tasks

1. Controlled preview bridge (no nested editor/autosave) + real MQ stress runner  
2. Inspector caret-stable updates + action registry polish  
3. Component identity/overrides + token rename transactions  
4. Checkpoints outside no-op undo stack; honest local variants  
5. Change Impact Review / Layout Intent Lens / Design Preflight  
6. Browser acceptance screenshots at 1280/1440/1920 + 200% zoom  
7. Windows verification via `EDIT_LAYOUT.bat`

## Next concrete task

Preview lifecycle: draft-generation bridge without nested editor boot; replace stress-lab container probe with sequential viewport runner.
