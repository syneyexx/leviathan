# Web PDF Harvester

Multi-hop PDF/document discovery plugin for HADES. Discovery builds a persistent index; downloading is always a separate explicit action.

## Purpose

Crawl public websites, follow several navigation hops (category → listing → detail → download landing → viewer → PDF), record provenance, and later download selected or all confirmed resources.

This is **not** a naive `.pdf`-only scraper. It scores links, follows external resource hosts with a hop budget, detects PDFs via URL / Content-Type / Content-Disposition / magic bytes, and can escalate to Playwright when installed.

Related but different: `deep-web-downloader` downloads during crawl. This plugin keeps discovery and download separated for HADES tool orchestration.

## Architecture

- **HTTP-first**: `httpx` async client, HTML parser, redirect tracking, priority BFS queue
- **Browser-second** (optional): Playwright when pages are JS shells or clicks reveal download URLs
- **Index**: SQLite canonical store + JSONL export + `pdf_links.txt`
- **Downloads**: streaming to `.part` then atomic rename, SHA-256, dedupe by hash

```
data/pdf_harvester/
  indexes/
    discovered_resources.sqlite3
    discovered_resources.jsonl
    pdf_links.txt
  downloads/<hostname>/
  state/
    crawl_state.json
    last_session.json
    cancel.flag
  logs/
```

## Permissions

Manifest permissions (enforced by HADES Plugin Manager):

- `subprocess`
- `network`
- `filesystem`

Isolation: `restricted_env`. Trust default: `untrusted`. Manual runs require Plugin Manager approval. Autonomous use is disabled (`autonomous: false`).

## Installation

1. Import `plugins/web-pdf-harvester` (folder) or the packed `.HadesPlugin` from `dist/`.
2. Install dependencies via Plugin Manager (creates plugin-local venv from `requirements.txt`).
3. Optional browser escalation: install `requirements-browser.txt` inside the plugin venv and run `playwright install chromium`.

```bat
python plugins\web-pdf-harvester\pack_hadesplugin.py
```

## Actions

| Tool | Role |
|---|---|
| `discover` | Crawl and index (no PDF body download) |
| `status` | Last session / queue / counts |
| `list_resources` | Filter/paginate index |
| `download_selected` | Download by resource id |
| `download_all` | Download all confirmed pending (or `estimate_only`) |
| `resume_downloads` | Resume failed/partial |
| `verify` | Lightweight revalidation |
| `cancel` | Cooperative cancel flag |
| `health` | Dependency / data-dir check |
| `run` | Single JSON payload dispatcher |

### Discover example

```json
{
  "start_urls": ["https://www.example.com/books"],
  "max_depth": 6,
  "max_pages": 5000,
  "same_domain_first": true,
  "allow_external_resource_hosts": true,
  "respect_robots_txt": true,
  "rate_limit_ms": 750,
  "resume": false
}
```

FreeBookCentre-style sites work as a **use case** (multi-hop + external hosts). The crawler uses generic heuristics only — no site-specific selectors.

### Download later

```json
{ "estimate_only": true }
```

```json
{ "resource_ids": ["res_..."] }
```

```json
{}
```

for `download_all` after the user/HADES confirms size.

## CLI

```bash
python harvester_cli.py discover --start-urls '["http://127.0.0.1:8765/"]' --allow-private-hosts true --data-dir data/pdf_harvester
python harvester_cli.py status --data-dir data/pdf_harvester
python harvester_cli.py download_all --data-dir data/pdf_harvester --allow-private-hosts true
```

## Crawl limits (defaults)

- `max_depth=6`, `max_pages=5000`, `max_external_hops=3`
- `max_concurrent_requests=8`, `max_browser_pages=2`
- `rate_limit_ms=750`, `max_retries=3`, `max_redirects=10`
- Private/localhost hosts blocked unless `allow_private_hosts=true`

## Download behaviour

- Never runs implicitly from `discover`
- Streaming chunked I/O, `.part` temp files, atomic rename
- SHA-256 + `%PDF-` validation
- Hash dedupe keeps provenance, reuses one physical file
- Second `download_all` skips valid existing files

## Resume / cancellation

- `resume=false` by default so a new discover does not silently no-op on prior visited state
- `resume=true` reloads visited/queued URLs from `state/crawl_state.json`; if the queue is empty (seeds already visited) the action returns `success=false` with an explicit error
- `cancel` writes `state/cancel.flag`; workers stop new work, flush index/state, leave `.part` resumable
- Cancelled runs return `success=false` / exit `130` — not success
- `download_all` / `resume_downloads` return `success=false` when there is nothing to download (empty index / no failed partials)

## Security

- Page content is untrusted data, never instructions
- Blocks `file://`, `javascript:`, `data:`, private IP ranges, cloud metadata hostnames
- No login/paywall/CAPTCHA/DRM bypass
- Safe-click classifier only follows read-only resource navigation labels
- Path sanitization against traversal and Windows reserved names

## Knowledge ingestion

Downloaded files are left on disk with index metadata (`local_path`, `sha256`). HADES Knowledge ingestion is an explicit later step — this plugin does not auto-ingest.

## Troubleshooting

| Symptom | Check |
|---|---|
| Plugin not Ready | Repair dependencies / review permissions |
| 0 PDFs found | Increase `max_depth`, allow external hosts, inspect `status` |
| Browser never used | Optional Playwright not installed |
| Local fixture fails | Set `allow_private_hosts=true` |
| Large crawl killed | Raise Plugin Manager invoke timeout; use `resume=true` |

## Tests

```bash
cd plugins/web-pdf-harvester
pip install -r requirements.txt
python tests/test_harvester.py
```

Local fixture proves ≥5-hop discovery, loop protection, fake `.pdf` rejection, download + idempotent re-download without contacting external websites.
