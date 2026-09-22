# LEVIATHAN STUDIO — Architecture

## Identity

Document schema **v3** (`js/identity.js`):

| Key form | Scope | Meaning |
| --- | --- | --- |
| `node:<id>` | `page` / `component-master` | Stable `data-lvb-node` on the live element |
| `shell:<selector>` | `global-shell` | Shell regions (`.lv-header`, …) |
| legacy CSS selector | flagged `ambiguous` | Migrated from v2; applied only when exactly one DOM match |

Selection, layers, commands, CSS overrides, and runtime (`editorContentRuntime.ts`) share the same keys.

## History

One **global** command stack. Gestures/`capture` store a **scoped patch** (`js/patches.js`) — only changed entry keys, nodes, components, and CSS files. Undo of page A never replaces page B entries.

Page bags keep selection + camera only (no stack swap).

## Save

`js/save.js` + `POST /api/save`:

- One active save; newer snapshots queue (latest wins)
- `localRevision` bumps on every edit; clean only after server ack when revisions match
- States: clean / dirty / saving / saved / error / conflict / offline
- Optimistic concurrency via `baseRevision` + `baseHash` → HTTP 409
- Server: session token, Origin allow-list, write lock, journal + `os.replace` temp files, last-good checkpoint
- Multi-file + JSON is journal/rollback recoverable — **not** crash-atomic across files as a single OS transaction

Corrupt JSON is **not** silently replaced with an empty document.

## Viewport

- **Design**: live DOM; breakpoint overrides from the document model
- **Preview**: same-origin iframe sized to 390 / 834 / custom — real `@media` / vw / fixed

Camera transform stays on `#root` and is never written into exported document CSS.

## Recovery

`localStorage` key `lvb.recovery.v1` — draft with base revision/hash; user chooses apply / compare / discard via Studio menu.
