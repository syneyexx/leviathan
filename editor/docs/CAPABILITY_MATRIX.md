# Capability matrix — LEVIATHAN STUDIO

Statuses: **verified** (deterministic tests or browser acceptance), **implemented but unverified** (code present, no browser evidence this run), **partial**, **unavailable**, **blocked**.

Baseline for this ledger: `d66c044` + frontier work on `cursor/editor-frontier-daad`.

| ID | Status | Evidence / blocker |
| --- | --- | --- |
| identity-v3 | verified | `js/identity.js` + unit tests |
| scoped-history-entries | verified | cross-page entry undo tests |
| scoped-history-structural | verified | `test/patches.test.mjs` identity node/component ops |
| save-coordinator | verified | `test/save.test.mjs` — queue base stamp, coalesce, gen≠rev, conflict pause, waiter timing |
| api-session | verified | `test_api.py` 401/403/409/410/400 |
| api-write-contract | verified | `test_concurrency.py` — same-base 200+409; PUT `/api/file` requires base; journal rollback |
| journal-recovery | verified | pending journal rolled back before writes; absent prior file not invented |
| text-no-global-replace | verified | API 410; client `replaceText` rejects; media path no longer calls it (#48 + frontier) |
| clear-styles | verified | BEGIN/END util test |
| studio-shell | implemented but unverified | graphite/ice-blue chrome — no browser screenshots this run |
| viewport-preview | partial | Design↔Preview restores iframe.hidden; still boots editor-enabled route in iframe |
| gesture-cancel | verified (unit) / implemented but unverified (browser) | `gesture-draft.js` + Escape/pointercancel/blur wiring; browser restore unverified |
| ai-copilot | unavailable | 501 + honest UI; no provider contract |
| stress-lab | partial | container-width probe — **not** viewport media-query runner |
| constraints-intel | implemented but unverified | `explainLayout` |
| design-problems | implemented but unverified | Problems panel |
| history-timeline | partial | named checkpoints still occupy command stack with no-op undo |
| visual-compare | partial | `compareToCheckpoint` is document diff, not rendered visual compare |
| design-branches | partial | Map + snapshot checkout; structural merge conflicts incomplete |
| states-studio | partial | outline/classes preview ≠ component hover/focus design proof |
| content-scenarios | partial | fixtures exist; must not alter parent root font-size (still risk) |
| token-theme-studio | partial | list/copy/apply; not full authoring/theme system |
| recipes | implemented but unverified | dry-run/apply present |
| handoff-package | implemented but unverified | export/import present |
| precision-hud | implemented but unverified | selection HUD + dimensions |
| workspace-recovery | partial | recovery draft; uncommitted gesture marked separately in draft export |
| multi-select-resize | verified (unit) | `resize.test.mjs` |
| keyboard-resize | verified (unit) | `layout.resizeByKeyboard` → `resizeRect` |
| image-replace | partial | Fit/Fill/Stretch + target token on upload; browser path unverified |
| zoom-handles | verified (unit) | west/north zoom cases |
| equal-spacing-snap | implemented but unverified | guides + density |
| media-library-meta | implemented but unverified | dims/bytes/mtime/usage badge |
| change-impact-review | partial | `planImpact` / `planTokenRename` + confirm before apply; recipes/import not fully wired |
| layout-intent-lens | unavailable | not started |
| design-preflight | unavailable | not started |
| stress-lab | partial | labeled **container-probe**; unsupported MQ/vw/fixed reported; gen stamped |
| content-scenarios | partial | text-200 scoped to `#root` (no parent `<html>` font-size) |
| token-theme-studio | partial | rename with impact preview; not full theme authoring |
| visual-compare | partial | returns `{ kind: "document-diff", visualCompare: false }` |

## Browser / Windows / GPU

Not verified in this environment. Capability claims above that require screenshots remain **implemented but unverified**. Windows launch: `editor/EDIT_LAYOUT.bat` (loopback Vite + API).
