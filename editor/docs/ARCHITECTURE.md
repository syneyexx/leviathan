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

One **global** command stack. Gestures/`capture` store a **scoped patch** (`js/patches.js`):

- Entries by identity key
- Nodes/components via identity-addressed ops (`insert` / `delete` / `update` / `reorder`)
- Meta by top-level key diff
- CSS files as whole-file ownership (not fine-grained block isolation)

Undo of page A must not replace unrelated nodes introduced on page B.

Page bags keep selection + camera only (no stack swap).

Gestures use a **gesture draft** (`js/gesture-draft.js`) that captures style/attribute chrome before the first DOM mutation. Cancel / failed promotion restores DOM and model; autosave skips while a gesture is active.

## Save

`js/save.js` + `POST /api/save`:

- Distinct counters: `localGeneration`, `acknowledgedLocalGeneration`, `serverRevision`, `serverHash`
- One active immutable snapshot; newer intents coalesce
- Queued drain **re-stamps** `baseRevision`/`baseHash` from the last acknowledgement
- Callers resolve only when their generation (or a later superseding one) is acknowledged
- Conflict/offline pauses automatic drain until explicit retry
- Cleanliness compares the live buffer to the **acknowledged** baseline (not local vs server counters)

Server (`server.py`):

- Metadata read, precondition check, canonical hash, and persistence share one `WRITE_LOCK` critical section
- Every write endpoint (`/api/save`, `/api/content`, `/api/file`) requires the revision contract
- Startup rolls back incomplete journals before accepting writes
- Process lock refuses a second API process on the same project
- Journal + `os.replace` is **not** crash-atomic as a single OS transaction

Client FNV `hashDocument` must never substitute for the server concurrency hash.

Corrupt JSON is **not** silently replaced with an empty document.
Future schema versions are rejected — never silently normalized to v3.

## Viewport

- **Design**: live DOM; breakpoint overrides from the document model
- **Preview**: same-origin iframe sized to 390 / 834 / custom — real `@media` / vw / fixed

Camera transform stays on `#root` and is never written into exported document CSS.

## Recovery

`localStorage` key `lvb.recovery.v1` — draft with base revision/hash; user chooses apply / compare / discard via Studio menu.
