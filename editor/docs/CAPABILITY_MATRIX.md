# Capability matrix — LEVIATHAN STUDIO

| ID | Status | Evidence / blocker |
| --- | --- | --- |
| identity-v3 | implemented | `js/identity.js` + runtime query; unit tests |
| scoped-history | verified | unit: cross-page undo; commands gesture test |
| save-coordinator | verified | unit: dirty-during-save; API conflict 409 |
| api-session | verified | `test_api.py` 401/403/409/410 |
| text-no-global-replace | verified | API 410 |
| clear-styles | verified | BEGIN/END util test |
| studio-shell | verified | mission-control graphite + ice-blue chrome |
| viewport-preview | implemented | Preview mode screenshot; iframe bridge |
| gesture-cancel | implemented | Escape / pointercancel / blur / visibilitychange restore pre-gesture boxes |
| ai-copilot | unavailable | 501 + UI screenshot (honest unavailable) |
| stress-lab | implemented | `studio.runStressLab` + multi-page resize/image/undo preset |
| constraints-intel | implemented | `explainLayout` |
| design-problems | implemented | Problems: ambiguous, missing assets, constraints, visual-jump-risk |
| history-timeline | implemented | History panel + named checkpoints |
| visual-compare | implemented | `compareToCheckpoint` |
| design-branches | implemented | create/merge with conflict list |
| states-studio | implemented | CSS state preview classes |
| content-scenarios | implemented | Fixture bridge (local dataset) |
| token-theme-studio | implemented | Existing tokens panel + invalid-ref check |
| recipes | implemented | Declarative recipes + dry-run/apply |
| handoff-package | implemented | Export/import change package |
| precision-hud | implemented | Selection HUD + live dimension labels + aspect lock |
| workspace-recovery | implemented | Recovery draft + in-progress free-transform boxes |
| multi-select-resize | implemented | `resizeGroupMembers` scale/independent; unit tests |
| keyboard-resize | implemented | Alt+arrows via `layout.resizeByKeyboard` → `resizeRect` |
| image-replace | implemented | Context/inspector/DnD replace + Fit/Fill/Stretch/Original |
| zoom-handles | implemented | Handle hit ≥10px screen; west/north zoom cases tested |
| equal-spacing-snap | implemented | `equalSpacingGuides` + snap density Off/Sparse/Dense |
| media-library-meta | implemented | Dimensions, bytes, mtime, used-on-page badge, SVG/WebP |

Statuses: **verified** (browser acceptance), **implemented but unverified**, **unavailable**, **incomplete**.
Browser visual verification depends on a running `EDIT_LAYOUT.bat` / Vite session in the agent environment.
