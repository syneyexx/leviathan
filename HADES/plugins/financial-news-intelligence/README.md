# Financial News Intelligence — HADES plugin

A direct-source financial news collector for HADES. The packaged catalog contains **480 unique websites** and intentionally does **not** use Google News or Google Search as an aggregator.

## Coverage

The catalog is balanced across:

- official regulators, central banks, statistical agencies and international institutions;
- exchanges and market infrastructure;
- corporate newsrooms / investor-news sources;
- global and regional financial/business publishers;
- investment, banking, PE/VC, real-estate and market-specialist publishers;
- crypto/blockchain publishers, exchanges and research organizations;
- sector/trade publications covering technology, semiconductors, energy, autos, aerospace/defence, healthcare, retail, logistics, mining, telecom and cybersecurity.

`max_sources` is hard-limited to **300..500**. Default: **480**. A run reports both `attempted` and `websites_with_items`, because a website can be temporarily unavailable, block automated clients, change markup or return no recent article candidates. The plugin never fabricates source success.

## Collection strategy

For each source the collector:

1. checks `robots.txt` when enabled;
2. fetches the configured direct newsroom/news/markets URL;
3. uses RSS/Atom immediately when the seed is a feed;
4. discovers RSS/Atom from `<link rel="alternate">`;
5. tries a small set of common feed paths when needed;
6. falls back to article-like links from the configured news section;
7. optionally fetches public article HTML and extracts bounded text;
8. canonicalizes URLs, removes common tracking parameters and deduplicates;
9. assigns heuristic event types and a 0–100 market-impact priority score;
10. stores seen IDs in SQLite so `new_only=true` returns only unseen stories.

No login/paywall bypass is attempted.

## Event classes

- earnings / guidance
- merger, acquisition, takeover, strategic deal
- IPO / financing / debt / capital raise
- bankruptcy / default / restructuring
- regulatory / legal / antitrust
- management / governance changes
- products / operations / supply chain / major contracts
- cybersecurity incidents
- rates / inflation / GDP / labour / central-bank decisions
- commodities / energy
- crypto / blockchain
- analyst upgrades / downgrades / price targets

Impact scores are prioritization heuristics only; they are not predictions of market direction or trading advice.

## Manual usage

```bash
python financial_news_intelligence.py sources --max-sources 480 --show 50
python financial_news_intelligence.py audit --max-sources 480 --workers 24 --show 100
python financial_news_intelligence.py fetch --max-sources 480 --max-articles 1500 --since-hours 48
```

Useful filters:

```bash
python financial_news_intelligence.py fetch --max-sources 480 --query "NVIDIA"
python financial_news_intelligence.py fetch --max-sources 480 --min-impact 50
```

A category filter is supported, but it is rejected if it leaves fewer than 300 websites because the plugin contract requires a 300-site minimum.

## Outputs

Every fetch produces:

- `.jsonl` — one normalized intelligence record per line;
- `.json` — full batch including health/coverage metrics;
- `.md` — HADES Knowledge-friendly evidence report.

Each record includes source provenance, URL, timestamps, discovery/crawl method, bounded article evidence when available, event types, impact score/reasons, detected tickers and common crypto symbols.

## HADES Knowledge

`feed_hades` uploads the generated Markdown batch through HADES `/api/files/upload`. It requires `approved_file_write=true`.

## Packaging

```bash
python pack_hadesplugin.py --out dist
```
