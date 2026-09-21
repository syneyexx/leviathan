from __future__ import annotations

import json
import sys
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from article_crawler import extract_article_html  # noqa: E402
from news_core import FeedSource, balanced, markdown, normalize_url, parse_feed, parse_opml  # noqa: E402
from site_discovery import parse_sitemap  # noqa: E402
from story_intelligence import build_story_clusters, deduplicate_articles  # noqa: E402


def sample_source(cc: str = "NL", name: str = "Example", kind: str = "direct") -> FeedSource:
    return FeedSource(
        id=f"source-{cc}-{name}",
        name=name,
        feed_url=f"https://{name.lower()}.example/rss",
        home_url=f"https://{name.lower()}.example/",
        country="Netherlands" if cc == "NL" else cc,
        country_code=cc,
        region="Europe",
        language="en",
        kind=kind,
        catalog="test",
    )


def test_parse_rss_and_provenance() -> None:
    rss = b"""<?xml version='1.0'?><rss version='2.0'><channel><title>x</title>
    <item><title>Hello &amp; World</title><link>https://example.com/a?utm_source=x</link>
    <description><![CDATA[<p>Short <b>summary</b>.</p>]]></description>
    <pubDate>Mon, 07 Sep 2026 12:00:00 GMT</pubDate><source url='https://publisher.example'>Publisher</source></item>
    </channel></rss>"""
    items = parse_feed(rss, sample_source(), fetched_at=datetime(2026, 9, 8, tzinfo=UTC))
    assert len(items) == 1
    assert items[0].title == "Hello & World"
    assert items[0].url == "https://example.com/a"
    assert items[0].snippet == "Short summary."
    assert items[0].publisher == "Publisher"
    assert items[0].published_at == "2026-09-07T12:00:00Z"
    assert items[0].crawl_status == "not_attempted"


def test_parse_atom() -> None:
    atom = b"""<feed xmlns='http://www.w3.org/2005/Atom'><entry><title>Atom item</title>
    <link href='https://example.com/atom'/><updated>2026-09-08T00:00:00Z</updated><summary>Body</summary></entry></feed>"""
    items = parse_feed(atom, sample_source())
    assert len(items) == 1
    assert items[0].url == "https://example.com/atom"
    assert items[0].snippet == "Body"


def test_parse_opml() -> None:
    opml = b"""<opml version='2.0'><body><outline text='A' title='A' type='rss'
    xmlUrl='https://a.example/rss' htmlUrl='https://a.example/'/></body></opml>"""
    items = parse_opml(opml, "NL", "https://catalog.example/NL.opml")
    assert len(items) == 1
    assert items[0].name == "A"
    assert items[0].country_code == "NL"
    assert items[0].kind == "direct"


def test_balanced_sources_hard_cap_and_country_spread() -> None:
    sources = [sample_source("US", f"US{i}") for i in range(20)] + [sample_source("NL", f"NL{i}") for i in range(2)]
    selected = balanced(sources, 4)
    assert len(selected) == 4
    assert {item.country_code for item in selected} == {"US", "NL"}


def test_balanced_can_disable_google_fallback() -> None:
    direct = sample_source("NL", "Direct", "direct")
    google = sample_source("US", "Google", "google-country")
    assert balanced([google, direct], 10, allow_google_fallback=False) == [direct]


def test_normalize_url_drops_tracking() -> None:
    assert normalize_url("https://Example.com/a?utm_source=x&x=1#frag") == "https://example.com/a?x=1"


def test_extract_html_article_and_metadata() -> None:
    raw = """<html lang='nl'><head><meta property='og:title' content='Titel'>
    <meta property='article:published_time' content='2026-09-08T10:00:00Z'>
    <link rel='canonical' href='/story'></head><body><nav>menu</nav><article>
    <p>Dit is de eerste relevante alinea met genoeg woorden om als artikeltekst te gelden.</p>
    <p>Dit is de tweede relevante alinea met aanvullende feiten en context voor HADES.</p>
    </article></body></html>"""
    result = extract_article_html(raw, "https://example.com/a")
    assert result.ok
    assert result.canonical_url == "https://example.com/story"
    assert result.language == "nl"
    assert result.extraction_method == "article"
    assert "eerste relevante" in result.text
    assert "menu" not in result.text


def test_extract_jsonld_newsarticle() -> None:
    payload = json.dumps({
        "@type": "NewsArticle",
        "headline": "H",
        "articleBody": "feit context " * 30,
        "publisher": {"name": "Nieuws"},
    })
    result = extract_article_html(f"<html><head><script type='application/ld+json'>{payload}</script></head></html>", "https://example.com/x")
    assert result.ok
    assert result.extraction_method == "json-ld"
    assert result.site_name == "Nieuws"


def test_paywall_hint_detected() -> None:
    raw = "<html><head><meta itemprop='isAccessibleForFree' content='false'></head><body><article><p>" + ("teaser " * 30) + "</p></article></body></html>"
    assert extract_article_html(raw, "https://example.com/x").paywall_hint


def test_markdown_keeps_provenance_and_crawled_evidence() -> None:
    source = sample_source()
    rss = b"""<rss><channel><item><title>T</title><link>https://example.com/t</link><description>S</description></item></channel></rss>"""
    article = parse_feed(rss, source)[0]
    article.article_text = "Crawled evidence text"
    article.crawl_status = "ok"
    article.crawl_method = "article"
    article.canonical_url = article.url
    text = markdown({
        "generated_at": "2026-09-08T00:00:00Z",
        "health": {"attempted": 1, "succeeded": 1, "crawl": {"succeeded": 1}},
        "articles": [article.__dict__],
    })
    assert "Article URL: https://example.com/t" in text
    assert f"Provenance ID: {article.id}" in text
    assert "Crawled article evidence" in text
    assert "Crawled evidence text" in text


def test_parse_news_sitemap_and_nested_index() -> None:
    sitemap = b"""<urlset xmlns='http://www.sitemaps.org/schemas/sitemap/0.9' xmlns:news='http://www.google.com/schemas/sitemap-news/0.9'>
    <url><loc>https://example.com/world/story-one</loc><lastmod>2026-09-08T10:00:00Z</lastmod>
    <news:news><news:publication_date>2026-09-08T09:55:00Z</news:publication_date><news:title>Story One</news:title></news:news></url></urlset>"""
    urls, nested = parse_sitemap(sitemap, "https://example.com/news-sitemap.xml")
    assert not nested
    assert urls[0].url == "https://example.com/world/story-one"
    assert urls[0].title == "Story One"
    assert urls[0].published_at == "2026-09-08T09:55:00Z"

    index = b"""<sitemapindex xmlns='http://www.sitemaps.org/schemas/sitemap/0.9'><sitemap><loc>/sitemap-news-2.xml</loc></sitemap></sitemapindex>"""
    urls, nested = parse_sitemap(index, "https://example.com/sitemap.xml")
    assert not urls
    assert nested == ["https://example.com/sitemap-news-2.xml"]


def test_canonical_dedup_preserves_provenance() -> None:
    a = parse_feed(b"<rss><channel><item><title>A</title><link>https://example.com/story</link><description>one</description></item></channel></rss>", sample_source())[0]
    b = parse_feed(b"<rss><channel><item><title>A duplicate</title><link>https://example.com/story</link><description>two</description></item></channel></rss>", sample_source())[0]
    a.canonical_url = "https://example.com/story"
    b.canonical_url = "https://example.com/story"
    b.article_text = "long evidence " * 100
    b.crawl_status = "ok"
    rows = deduplicate_articles([a, b])
    assert len(rows) == 1
    assert rows[0].duplicate_count == 1
    assert rows[0].crawl_status == "ok"


def test_story_cluster_cross_source_signals() -> None:
    a = parse_feed(b"<rss><channel><item><title>Major earthquake strikes coastal city causing widespread damage</title><link>https://a.example/story</link></item></channel></rss>", sample_source("NL", "Alpha"))[0]
    b = parse_feed(b"<rss><channel><item><title>Major earthquake strikes coastal city as widespread damage reported</title><link>https://b.example/story</link></item></channel></rss>", sample_source("DE", "Beta"))[0]
    a.publisher = "Alpha News"
    b.publisher = "Beta News"
    a.article_text = "evidence " * 200
    b.article_text = "evidence " * 200
    a.crawl_status = b.crawl_status = "ok"
    clusters = build_story_clusters([a, b])
    assert len(clusters) == 1
    assert clusters[0].source_count == 2
    assert a.story_id == b.story_id
    assert a.corroborating_publishers == 2
    assert a.corroboration_score > 0.5
