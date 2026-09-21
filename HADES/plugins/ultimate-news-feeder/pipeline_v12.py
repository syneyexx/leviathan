from __future__ import annotations

import json
import urllib.parse
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import news_core as core
from site_discovery import discover_sources
from story_intelligence import build_story_clusters, deduplicate_articles

VERSION = "1.2.0"
USER_AGENT = f"HADES-{core.PLUGIN_ID}/{VERSION}"


def _read_seen_urls(state_dir: Path) -> set[str]:
    payload = core.read_json(state_dir / "seen-urls-v12.json", {})
    if not isinstance(payload, dict):
        return set()
    urls = payload.get("urls", [])
    if not isinstance(urls, list):
        return set()
    return {core.normalize_url(x) for x in urls if isinstance(x, str) and core.normalize_url(x)}


def save_seen_urls(state_dir: Path, urls: list[str] | set[str]) -> None:
    current = _read_seen_urls(state_dir)
    current.update(core.normalize_url(x) for x in urls if core.normalize_url(x))
    core.write_json(state_dir / "seen-urls-v12.json", {"updated_at": core.iso(), "urls": list(current)[-100_000:]})


def _obj(row: dict[str, Any]) -> SimpleNamespace:
    obj = SimpleNamespace(**row)
    defaults = {
        "discovery_method": "feed",
        "provenance_urls": [],
        "duplicate_count": 0,
        "story_id": "",
        "story_cluster_size": 1,
        "corroborating_publishers": 1,
        "corroborating_countries": 1,
        "evidence_quality": 0.0,
        "corroboration_score": 0.0,
    }
    for key, value in defaults.items():
        if not hasattr(obj, key):
            setattr(obj, key, list(value) if isinstance(value, list) else value)
    return obj


def _from_discovery(source: core.FeedSource, item: Any) -> core.Article:
    url = core.normalize_url(getattr(item, "url", ""))
    title = core.clean(getattr(item, "title", ""), 1000)
    if not title:
        slug = urllib.parse.urlsplit(url).path.rstrip("/").rsplit("/", 1)[-1]
        title = core.clean(slug.replace("-", " ").replace("_", " "), 1000) or source.name
    published = core.parse_date(getattr(item, "published_at", ""))
    article = core.Article(
        id=core.digest(source.id, url, title),
        title=title,
        url=url,
        snippet="",
        published_at=core.iso(published) if published else "",
        fetched_at=core.iso(),
        publisher=source.name,
        publisher_url=source.home_url,
        feed_name=source.name,
        feed_url=source.feed_url,
        source_id=source.id,
        country=source.country,
        country_code=source.country_code,
        region=source.region,
        language=source.language,
        source_kind=source.kind,
    )
    article.discovery_method = getattr(item, "method", "site-discovery") or "site-discovery"
    source_page = getattr(item, "source_page", "")
    article.provenance_urls = [source_page] if source_page else []
    return article


def _serialize(obj: Any) -> dict[str, Any]:
    return dict(vars(obj))


def collect(state_dir: Path, max_sources: int, max_articles: int, per_source: int, since_hours: float,
            timeout: float, workers: int, refresh_sources: bool, regions: set[str] | None,
            countries: set[str] | None, languages: set[str] | None, query: str, new_only: bool,
            crawl_pages: bool = True, article_workers: int = 12, max_article_chars: int = 6000,
            respect_robots: bool = True, allow_google_fallback: bool = True,
            discover_sites: bool = True, discovery_sites: int = 150, discovery_urls_per_site: int = 6,
            discovery_workers: int = 12, story_clustering: bool = True) -> dict[str, Any]:
    feed_pool = min(50_000, max(max_articles, min(max_articles * 2, 5000)))
    base = core.collect(
        state_dir, max_sources, feed_pool, per_source, since_hours, timeout, workers,
        refresh_sources, regions, countries, languages, "", new_only,
        crawl_pages=crawl_pages, article_workers=article_workers, max_article_chars=max_article_chars,
        respect_robots=respect_robots, allow_google_fallback=allow_google_fallback,
    )

    sources, _stats = core.load_catalog(state_dir, False, timeout)
    selected = core.balanced(sources, max_sources, regions, countries, languages, allow_google_fallback)
    by_url: dict[str, SimpleNamespace] = {}
    for row in base.get("articles", []):
        obj = _obj(row)
        key = core.normalize_url(getattr(obj, "canonical_url", "") or obj.url) or obj.url
        by_url.setdefault(key, obj)

    discovery_health: dict[str, Any] = {
        "sites_attempted": 0, "sites_succeeded": 0, "sites_failed": 0,
        "urls_discovered": 0, "errors": [], "crawl": {"attempted": 0, "succeeded": 0, "limited": 0, "failed": 0, "errors": []},
    }
    discovered_articles: list[core.Article] = []
    old_ids = core.seen_ids(state_dir) if new_only else set()
    old_urls = _read_seen_urls(state_dir) if new_only else set()
    cutoff = core.now() - core.timedelta(hours=since_hours) if since_hours > 0 else None

    if discover_sites:
        discovered = discover_sources(
            selected, USER_AGENT, timeout,
            max_sites=max(1, min(discovery_sites, core.HARD_SOURCE_CAP)),
            max_urls_per_site=max(1, min(discovery_urls_per_site, 50)),
            workers=max(1, min(discovery_workers, 32)),
            respect_robots=respect_robots,
        )
        discovery_health.update({k: v for k, v in discovered.items() if k != "rows"})
        for row in discovered.get("rows", []):
            source = row.get("source")
            if not isinstance(source, core.FeedSource):
                continue
            for item in row.get("items", []):
                article = _from_discovery(source, item)
                if not article.url or article.id in old_ids or article.url in old_urls:
                    continue
                if cutoff and article.published_at and (core.parse_date(article.published_at) or cutoff) < cutoff:
                    continue
                key = core.normalize_url(article.url) or article.url
                if key in by_url:
                    existing = by_url[key]
                    method = getattr(article, "discovery_method", "site-discovery")
                    if getattr(existing, "discovery_method", "feed") == "feed":
                        existing.discovery_method = "feed+" + method
                    provenance = list(getattr(existing, "provenance_urls", []) or [])
                    for value in getattr(article, "provenance_urls", []) or []:
                        if value and value not in provenance:
                            provenance.append(value)
                    existing.provenance_urls = provenance[:20]
                    continue
                discovered_articles.append(article)
                if len(discovered_articles) >= feed_pool:
                    break
            if len(discovered_articles) >= feed_pool:
                break

    if crawl_pages and discovered_articles:
        d_crawl = core.enrich_articles(discovered_articles, timeout, article_workers, max_article_chars, respect_robots)
        discovery_health["crawl"] = d_crawl
    for article in discovered_articles:
        obj = _obj({**article.__dict__,
                    "discovery_method": getattr(article, "discovery_method", "site-discovery"),
                    "provenance_urls": list(getattr(article, "provenance_urls", []) or [])})
        key = core.normalize_url(getattr(obj, "canonical_url", "") or obj.url) or obj.url
        by_url.setdefault(key, obj)

    objects = deduplicate_articles(list(by_url.values()))
    if query:
        q = query.casefold()
        objects = [o for o in objects if q in f"{getattr(o, 'title', '')} {getattr(o, 'snippet', '')} {getattr(o, 'article_text', '')} {getattr(o, 'publisher', '')}".casefold()]
    objects.sort(key=lambda o: getattr(o, "published_at", "") or getattr(o, "fetched_at", ""), reverse=True)
    objects = objects[:max_articles]

    clusters = build_story_clusters(objects) if story_clustering else []
    articles = [_serialize(o) for o in objects]
    feed_crawl = base.get("health", {}).get("crawl", {})
    d_crawl = discovery_health.get("crawl", {})
    aggregate_crawl = {
        "attempted": int(feed_crawl.get("attempted", 0)) + int(d_crawl.get("attempted", 0)),
        "succeeded": int(feed_crawl.get("succeeded", 0)) + int(d_crawl.get("succeeded", 0)),
        "limited": int(feed_crawl.get("limited", 0)) + int(d_crawl.get("limited", 0)),
        "failed": int(feed_crawl.get("failed", 0)) + int(d_crawl.get("failed", 0)),
        "feed": feed_crawl,
        "discovery": d_crawl,
    }
    base["version"] = VERSION
    base["health"]["crawl"] = aggregate_crawl
    base["health"]["discovery"] = {k: v for k, v in discovery_health.items() if k != "crawl"}
    base["selected_sources"] = len(selected)
    base["direct_sources_selected"] = sum(s.kind == "direct" for s in selected)
    base["fallback_sources_selected"] = sum(s.kind != "direct" for s in selected)
    base["discovered_articles"] = len(by_url)
    base["new_articles"] = len(articles)
    base["story_clusters"] = [cluster.to_dict() for cluster in clusters]
    base["corroborated_story_clusters"] = sum(cluster.source_count >= 2 for cluster in clusters)
    base["articles"] = articles
    return base


def markdown(payload: dict[str, Any]) -> str:
    discovery = payload.get("health", {}).get("discovery", {})
    crawl = payload.get("health", {}).get("crawl", {})
    clusters = payload.get("story_clusters", [])
    lines = [
        "# UltimateNewsFeeder knowledge batch",
        "",
        f"Generated: {payload['generated_at']}",
        f"Sources attempted: {payload['health']['attempted']}",
        f"Sites explored beyond feeds: {discovery.get('sites_attempted', 0)}",
        f"URLs discovered from sitemaps/homepages: {discovery.get('urls_discovered', 0)}",
        f"Articles retained: {len(payload.get('articles', []))}",
        f"Article pages crawled successfully: {crawl.get('succeeded', 0)}",
        f"Story clusters: {len(clusters)}",
        f"Multi-publisher corroborated clusters: {payload.get('corroborated_story_clusters', 0)}",
        "",
        "Corroboration is a retrieval signal, not a truth probability. Preserve publisher provenance and verify important claims against the linked evidence.",
        "",
    ]
    multi = [c for c in clusters if c.get("source_count", 0) >= 2]
    if multi:
        lines += ["# Cross-source story intelligence", ""]
        for cluster in multi[:100]:
            lines += [
                f"## Story {cluster['story_id']}: {cluster['representative_title']}", "",
                f"- Independent publishers: {cluster['source_count']}",
                f"- Countries: {', '.join(cluster['countries'])}",
                f"- Publishers: {', '.join(cluster['publishers'][:12])}",
                f"- Evidence quality: {cluster['evidence_quality']}",
                f"- Corroboration signal: {cluster['corroboration_score']}", "",
            ]
    lines += ["# Article evidence", ""]
    for a in payload.get("articles", []):
        lines += [
            f"## {a.get('title', '')}", "",
            f"- Publisher: {a.get('publisher', '')}",
            f"- Country: {a.get('country', '')} ({a.get('country_code', '')})",
            f"- Region: {a.get('region', '')}",
            f"- Language: {a.get('language', '')}",
            f"- Published: {a.get('published_at') or 'unknown'}",
            f"- Article URL: {a.get('url', '')}",
            f"- Canonical URL: {a.get('canonical_url') or a.get('url', '')}",
            f"- Feed: {a.get('feed_name', '')} — {a.get('feed_url', '')}",
            f"- Discovery method: {a.get('discovery_method', 'feed')}",
            f"- Crawl status: {a.get('crawl_status', 'not_attempted')}",
            f"- Story ID: {a.get('story_id') or 'unclustered'}",
            f"- Story cluster size: {a.get('story_cluster_size', 1)}",
            f"- Corroborating publishers: {a.get('corroborating_publishers', 1)}",
            f"- Evidence quality: {a.get('evidence_quality', 0)}",
            f"- Corroboration signal: {a.get('corroboration_score', 0)}",
            f"- Provenance ID: {a.get('id', '')}", "",
            "### Feed/discovery summary", "", a.get("snippet") or "(No summary provided.)", "",
        ]
        if a.get("article_text"):
            lines += ["### Crawled article evidence", "", a["article_text"], ""]
        elif a.get("crawl_error"):
            lines += ["### Crawl note", "", a["crawl_error"], ""]
    return "\n".join(lines).strip() + "\n"


def write_outputs(payload: dict[str, Any], output_dir: Path) -> dict[str, str]:
    output_dir.mkdir(parents=True, exist_ok=True)
    stamp = core.now().strftime("%Y%m%dT%H%M%SZ")
    batch = core.digest(*(a.get("id", "") for a in payload.get("articles", [])))[:12]
    base = output_dir / f"ultimate-news-{stamp}-{batch}"
    jsonl, md = base.with_suffix(".jsonl"), base.with_suffix(".md")
    jsonl.write_text("".join(json.dumps(a, ensure_ascii=False) + "\n" for a in payload.get("articles", [])), encoding="utf-8")
    md.write_text(markdown(payload), encoding="utf-8")
    return {"jsonl": str(jsonl.resolve()), "markdown": str(md.resolve())}
