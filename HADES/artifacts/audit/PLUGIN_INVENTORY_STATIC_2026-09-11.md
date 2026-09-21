# Plugin inventory — refreshed 2026-09-11 (static)

Count: **46** plugins with `hades-plugin.json` + `_shared`.

Matches `artifacts/audit/PLUGIN_INVENTORY.md` (prior). No new/missing plugin dirs vs that inventory.

Runtime column: all **RUNTIME_UNVERIFIED** this pass (no CLI plugin E2E).

Notable static fixes this audit tip:
- deep-web-downloader — SSRF hop validation
- ultimate-news-feeder / financial-news-intelligence — SSRF
- patchright / puppeteer / scrapling — private host block
- searxng bridge **template** doctor fail-closed (live already fixed)
