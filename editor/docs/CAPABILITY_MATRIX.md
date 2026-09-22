# Capability matrix — LEVIATHAN STUDIO

| ID | Status | Evidence / blocker |
| --- | --- | --- |
| identity-v3 | implemented | `js/identity.js` + runtime query; unit tests |
| scoped-history | implemented | `js/patches.js` + `commands.js`; cross-page undo test |
| save-coordinator | implemented | `js/save.js` + `/api/save`; dirty-during-save test |
| api-session | implemented | Origin + `X-LVB-Session`; `test_api.py` |
| text-no-global-replace | implemented | `/api/replace-text` → 410 |
| clear-styles | implemented | BEGIN/END import; util test |
| studio-shell | implemented | `canvas.css` tokens + chrome composition |
| viewport-preview | implemented | `js/studio/viewport.js` Design/Preview |
| gesture-cancel | implemented | Escape / pointercancel / blur |
| ai-copilot | unavailable | No Leviathan model binding (501) |
| stress-lab | implemented | `studio.runStressLab` |
| constraints-intel | implemented | `explainLayout` |
| design-problems | implemented | Issues panel + checks |
| history-timeline | implemented | History panel + named checkpoints |
| visual-compare | implemented | `compareToCheckpoint` |
| design-branches | implemented | create/merge with conflict list |
| states-studio | implemented | CSS state preview classes |
| content-scenarios | implemented | Fixture bridge (local dataset) |
| token-theme-studio | implemented | Existing tokens panel + invalid-ref check |
| recipes | implemented | Declarative recipes + dry-run/apply |
| handoff-package | implemented | Export/import change package |
| precision-hud | implemented | Selection HUD in chrome |
| workspace-recovery | implemented | Recovery draft localStorage |

Statuses: **verified** (browser acceptance), **implemented but unverified**, **unavailable**, **incomplete**.
Browser visual verification depends on a running `EDIT_LAYOUT.bat` / Vite session in the agent environment.
