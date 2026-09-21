# LEVIATHAN Functions

On-demand / cold-path capabilities.

## Ownership

| Concern | Location |
|---|---|
| Function implementations (dormant until loaded) | `Data/functions/<name>/` |
| Registry + runtime (lazy load, timeout, cleanup) | `Data/modules/function_runtime/` |

## Builtin functions (Phase 8)

- `text_file_read` — UTF-8 text read
- `csv_inspector` — CSV header/sample inspection
- `pdf_parser` — PDF text extraction (optional `pypdf`)

Default lifecycle: **ON_DEMAND** (load → execute → unload).

Do not place long-lived stateful managers here.
