# UltimateNewsFeeder 1.2.0

`UltimateNewsFeeder` is the worldwide news-ingestion plugin for HADES Knowledge. Version 1.2 moves beyond feed-only collection and uses a bounded multi-layer pipeline:

1. **Direct publisher feeds** — curated RSS/Atom sources remain the fastest discovery path.
2. **Publisher website discovery** — direct publishers are explored through `robots.txt` sitemap declarations, common sitemap/news-sitemap endpoints, nested sitemap indexes, and article-like homepage links.
3. **Article crawl** — discovered URLs are fetched from the publisher itself and bounded article text/metadata is extracted from HTML, `<article>`, `<main>` and NewsArticle/Article JSON-LD.
4. **Canonical deduplication** — duplicate feed/sitemap/homepage discoveries of the same publisher URL collapse to one evidence record while preserving provenance.
5. **Cross-source story intelligence** — similar headlines are clustered across publishers. HADES receives publisher count, country spread, evidence-quality and a corroboration signal.
6. **Knowledge ingestion** — the final Markdown batch is uploaded through HADES `/api/files/upload` and indexed by KnowledgeService.

Google News remains an optional fallback; direct publisher sources are preferred and Google fallback can be disabled.

## Discovery controls

Defaults are deliberately bounded even when 300–500 feed sources are selected:

- `discover_sites=true`
- `discovery_sites=150`
- `discovery_urls_per_site=6`
- `discovery_workers=12`
- `crawl_pages=true`
- `max_article_chars=6000`
- `story_clustering=true`
- `respect_robots=true`

The site layer does **not** recursively mirror entire websites. It discovers a small number of likely current article URLs per publisher, then crawls only the selected article pages. This keeps runs finite and reduces navigation/tag/archive noise.

## Story intelligence

Story clustering is intentionally a retrieval aid, not a fact checker. A story supported by several independent publishers receives a stronger corroboration signal, but that number is **not** stored as a truth probability. Each article retains its own provenance and evidence quality so HADES can retrieve the underlying evidence.

Article records can contain:

- article URL and canonical URL;
- feed URL and publisher homepage;
- discovery path (`feed`, `sitemap`, `homepage`, or combined);
- publisher, country, region and language;
- published/fetched timestamps;
- bounded crawled article evidence;
- crawl status/extraction method/paywall hint;
- stable provenance ID and duplicate provenance URLs;
- story ID, cluster size and independent-publisher/country counts;
- evidence-quality and corroboration signals.

## Tools

### `fetch_latest`
Runs the full feed → website discovery → article crawl → dedupe → clustering pipeline and writes JSONL + Markdown.

### `feed_hades`
Runs the same pipeline and uploads the final Markdown batch to HADES Knowledge. `approved_file_write=true` is required.

### `source_status`
Shows the worldwide feed registry and distribution by source kind/country/region.

### `discover_websites`
Inspects the website-discovery layer by itself and shows URLs found from publisher sitemaps/homepages.

## CLI

```bash
python ultimate_news_feeder.py sources --refresh-sources true --max-sources 300
python ultimate_news_feeder.py discover-sites --max-sources 300 --discovery-sites 150 --show-sites 20
python ultimate_news_feeder.py fetch --max-sources 300 --since-hours 24
python ultimate_news_feeder.py fetch --allow-google-fallback false --discovery-sites 250
python ultimate_news_feeder.py feed-hades --max-sources 300 --approved-file-write true
```

## Operational boundaries

- Python standard library only.
- Feed/site/article requests have timeout and response-size limits.
- `robots.txt` and `X-Robots-Tag` indexing restrictions are respected by default.
- No paywall or login-wall bypass is attempted.
- One failing source does not abort the global run.
- Seen IDs **and URLs** are persisted to suppress repeated ingestion across discovery methods.
- The source selection hard cap remains **500**.
- News is stored in HADES **Knowledge**, not silently promoted into durable Memory/model weights.

## Packaging

```bash
python pack_hadesplugin.py
```

This produces `dist/ultimate-news-feeder-1.2.0.HadesPlugin` with SHA-256 integrity entries for every packaged source file.
