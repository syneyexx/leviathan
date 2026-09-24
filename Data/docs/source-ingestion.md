# Source Ingestion Architecture

LEVIATHAN Source Ingestion is the durable subsystem that accepts files and archives, inspects them safely, routes members to the correct parsers, and syncs useful knowledge into Brain — without loading large payloads into the API process.

## Pipeline

```
UPLOAD (streamed) → DURABLE RAW STORE → JobStore enqueue (source_ingestion.process)
        → worker claim/lease → detect → [archive inspect | single parse]
        → child sources + manifest checkpoints → Brain upsert (per child)
        → aggregate status (completed | partial | failed | cancelled)
```

Research Source Ingestion is a **facade** over this subsystem (`ResearchService` → `SourceIngestionService`). Datasets remain the canonical path for large training corpora; ingestion **routes** dataset-like members rather than duplicating Dataset Management.

## Supported source types

| Category | Formats |
|----------|---------|
| Documents | `.pdf`, `.txt`, `.md`, `.markdown`, `.rst`, `.log`, `.html`, `.htm`, `.xhtml`, `.xml` |
| Structured | `.json`, `.csv`, `.tsv`, `.yaml`, `.yml`, `.toml`, `.ini`, `.cfg`, `.conf`, `.properties` |
| Source code | Common languages (`.py`, `.ts`, `.js`, …) + project files (`README`, `Dockerfile`, `Makefile`, …) |
| Office | `.docx`, `.xlsx`, `.pptx` (requires `python-docx` / `openpyxl` / `python-pptx`) |
| Dataset-like | `.parquet`, large `.jsonl`/`.ndjson` → **routed to Dataset** |
| Images | Recognized; OCR/vision only when genuinely configured (otherwise skipped honestly) |
| Archives | `.zip`, `.tar`, `.tar.gz`/`.tgz`, `.tar.bz2`/`.tbz2`, `.tar.xz`/`.txz`, single-file `.gz` |

**Not supported:** `.rar` (no reliable cross-platform parser claimed). `.7z` only when `allow_7z` is enabled and a mature dependency is integrated (default off). Legacy binary `.doc`/`.xls`/`.ppt` are not claimed.

Unknown extensions with strong UTF-8 text detection can ingest via `PlainTextHandler` when `allow_unknown_text` is true.

## Archive security

Never uses `extractall()`. Controls (env-tunable via `LEVIATHAN_SOURCE_INGESTION_*`):

| Control | Default |
|---------|---------|
| `max_upload_bytes` | 8 GiB |
| `max_member_count` | 50 000 |
| `max_member_bytes` | 512 MiB |
| `max_total_uncompressed_bytes` | 8 GiB |
| `max_compression_ratio` | 200 |
| `max_nested_archive_depth` | 2 |
| `max_path_depth` | 64 |
| `max_filename_length` | 255 |

Defenses: Zip Slip / absolute / UNC / drive-letter paths; symlink/hardlink skip; zip-bomb declared-size checks; encrypted member quarantine; corrupt archive → honest failure with parent retained.

## Secret policy

Default `secret_policy=quarantine`:

- High-confidence filenames: `.env`, `.env.*`, `id_rsa`, `id_ed25519`, `*.pem`, `*.key`, `credentials.json`, `service-account*.json`, …
- Private-key PEM blocks
- Never log or Brain-index secret contents; reasons only

## Skip policy (codebase archives)

Default ignore dirs: `.git`, `node_modules`, `__pycache__`, `.venv`, `dist`, `build`, `coverage`, `target`, …  
Default binary extensions: `.exe`, `.dll`, `.so`, `.pyc`, …

Every skip is recorded on the manifest with an explicit reason.

## Worker model

- Capability IDs: `source_ingestion.process`, `source_ingestion.brain_retry` (JobStore, EXTERNAL provider)
- API `JobRuntime` **excludes** these capabilities so it cannot steal them
- Runner modes: `LEVIATHAN_SOURCE_INGESTION_RUNNER=inprocess|external|none`
- External: `python scripts/source_ingestion_worker.py`
- Unique worker IDs + leases/heartbeats; cooperative cancel between members

## Parent / child + Brain

- Archive = container source (`metadata.is_container`)
- Each useful member = child `ResearchSource` with `parent_source_id` / `container_source_id` / `relative_path` in provenance
- Brain document id: `research-upload:{content_hash}` (content dedupe; path provenance retained)
- Title form: `project.zip/docs/architecture.pdf`
- Parse OK + Brain FAILED is allowed; Brain-only retry supported

## Retry / cancel

- Cancel: cooperative, preserves completed children
- Retry failed children without re-parsing successes
- Brain-only retry for parsed members
- Crash/resume via durable `source_ingestion_members` checkpoints

## Adding a handler

1. Implement `can_handle` / `inspect` / `ingest` returning `NormalizedArtifact`
2. Register in `handlers/base.py` → `build_default_registry()`
3. Extend detection signals if needed
4. Add tests

Do **not** grow a hard-coded `if ext ==` chain in Research uploads.

## OCR / vision honesty

Images and scanned PDFs without extractable text are marked unsupported (`ocr_unavailable` / `PDF_NO_EXTRACTABLE_TEXT`). No fabricated OCR.

## Configuration

See `Data/modules/source_ingestion/settings.py` and `.env.example` (`LEVIATHAN_SOURCE_INGESTION_*`).
