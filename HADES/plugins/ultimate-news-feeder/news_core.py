from __future__ import annotations

import concurrent.futures
import email.utils
import hashlib
import html
import json
import re
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
import xml.etree.ElementTree as ET
from collections import defaultdict, deque
from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Iterable

from article_crawler import crawl_article
from source_catalog import COUNTRY_NAMES, COUNTRY_REGIONS, GOOGLE_NEWS_LOCALES, PLENARY_BASE, PLENARY_COUNTRIES

PLUGIN_ID = "ultimate-news-feeder"
VERSION = "1.1.0"
HARD_SOURCE_CAP = 500
USER_AGENT = f"HADES-{PLUGIN_ID}/{VERSION}"


def now() -> datetime:
    return datetime.now(UTC)


def iso(value: datetime | None = None) -> str:
    value = value or now()
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def clean(value: str | None, limit: int = 3500) -> str:
    text = html.unescape(value or "")
    text = re.sub(r"<script\b[^>]*>.*?</script>|<style\b[^>]*>.*?</style>", " ", text, flags=re.I | re.S)
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return re.sub(r"\s+([,.;:!?])", r"\1", text)[:limit]


def digest(*parts: str) -> str:
    return hashlib.sha256("\x1f".join(parts).encode("utf-8", "ignore")).hexdigest()


def normalize_url(url: str) -> str:
    try:
        p = urllib.parse.urlsplit(html.unescape((url or "").strip()))
    except ValueError:
        return url or ""
    if p.scheme not in {"http", "https"}:
        return url or ""
    drop = {"utm_source", "utm_medium", "utm_campaign", "utm_term", "utm_content", "gclid", "fbclid"}
    query = [(k, v) for k, v in urllib.parse.parse_qsl(p.query, keep_blank_values=True) if k.lower() not in drop]
    return urllib.parse.urlunsplit((p.scheme.lower(), p.netloc.lower(), p.path or "/", urllib.parse.urlencode(query), ""))


def parse_date(value: str | None) -> datetime | None:
    value = (value or "").strip()
    if not value:
        return None
    try:
        dt = email.utils.parsedate_to_datetime(value)
        if dt:
            return (dt if dt.tzinfo else dt.replace(tzinfo=UTC)).astimezone(UTC)
    except (TypeError, ValueError, OverflowError):
        pass
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return (dt if dt.tzinfo else dt.replace(tzinfo=UTC)).astimezone(UTC)
    except ValueError:
        return None


def fetch(url: str, timeout: float, max_bytes: int = 8 * 1024 * 1024) -> bytes:
    from ssrf import open_public_url

    with open_public_url(
        url,
        headers={
            "User-Agent": USER_AGENT,
            "Accept": "application/rss+xml, application/atom+xml, application/xml, text/xml, */*;q=0.5",
        },
        timeout=timeout,
    ) as response:
        data = response.read(max_bytes + 1)
    if len(data) > max_bytes:
        raise ValueError("feed response too large")
    return data


def lname(tag: str) -> str:
    return tag.rsplit("}", 1)[-1].lower()


def field(node: ET.Element, names: set[str]) -> str:
    for child in list(node):
        if lname(child.tag) in names:
            if lname(child.tag) == "link" and child.attrib.get("href"):
                return child.attrib["href"].strip()
            return "".join(child.itertext()).strip()
    return ""


@dataclass(frozen=True)
class FeedSource:
    id: str
    name: str
    feed_url: str
    home_url: str
    country: str
    country_code: str
    region: str
    language: str
    kind: str
    catalog: str


@dataclass
class Article:
    id: str
    title: str
    url: str
    snippet: str
    published_at: str
    fetched_at: str
    publisher: str
    publisher_url: str
    feed_name: str
    feed_url: str
    source_id: str
    country: str
    country_code: str
    region: str
    language: str
    source_kind: str
    article_text: str = ""
    crawl_status: str = "not_attempted"
    crawl_method: str = ""
    crawl_url: str = ""
    canonical_url: str = ""
    crawl_error: str = ""
    crawl_bytes: int = 0
    paywall_hint: bool = False


def parse_feed(data: bytes, source: FeedSource, fetched_at: datetime | None = None) -> list[Article]:
    root = ET.fromstring(data)
    language = source.language
    xml_lang = root.attrib.get("{http://www.w3.org/XML/1998/namespace}lang")
    if xml_lang:
        language = clean(xml_lang, 40)
    else:
        for n in root.iter():
            if lname(n.tag) == "language" and clean("".join(n.itertext()), 40):
                language = clean("".join(n.itertext()), 40)
                break
    result: list[Article] = []
    fetched_stamp = iso(fetched_at)
    for item in (n for n in root.iter() if lname(n.tag) in {"item", "entry"}):
        title = clean(field(item, {"title"}), 1000)
        link = normalize_url(field(item, {"link"}))
        if not link:
            guid = field(item, {"guid", "id"})
            link = normalize_url(guid) if guid.startswith(("http://", "https://")) else ""
        if not title or not link:
            continue
        bodies = ["".join(c.itertext()).strip() for c in list(item) if lname(c.tag) in {"description", "summary", "content", "encoded"}]
        published = parse_date(field(item, {"pubdate", "published", "updated", "date"}))
        publisher, publisher_url = source.name, source.home_url
        for c in list(item):
            if lname(c.tag) == "source":
                publisher = clean("".join(c.itertext()), 300) or publisher
                publisher_url = normalize_url(c.attrib.get("url", "")) or publisher_url
                break
        result.append(Article(
            id=digest(source.id, link, title), title=title, url=link,
            snippet=clean(max(bodies, key=len, default="")),
            published_at=iso(published) if published else "", fetched_at=fetched_stamp,
            publisher=publisher, publisher_url=publisher_url, feed_name=source.name, feed_url=source.feed_url,
            source_id=source.id, country=source.country, country_code=source.country_code,
            region=source.region, language=language, source_kind=source.kind,
        ))
    return result


def parse_opml(data: bytes, cc: str, catalog_url: str) -> list[FeedSource]:
    root = ET.fromstring(data)
    country, region = COUNTRY_NAMES.get(cc, cc), COUNTRY_REGIONS.get(cc, "Other")
    result: list[FeedSource] = []
    for node in root.iter():
        url = node.attrib.get("xmlUrl") or node.attrib.get("xmlurl") or ""
        if not url.startswith(("http://", "https://")):
            continue
        url = normalize_url(url)
        result.append(FeedSource(
            id=digest("direct", url), name=clean(node.attrib.get("title") or node.attrib.get("text") or url, 300),
            feed_url=url, home_url=normalize_url(node.attrib.get("htmlUrl") or node.attrib.get("htmlurl") or ""),
            country=country, country_code=cc, region=region, language="und", kind="direct", catalog=catalog_url,
        ))
    return result


def fallback_sources() -> list[FeedSource]:
    result = []
    for cc, country, hl, lang, region in GOOGLE_NEWS_LOCALES:
        params = urllib.parse.urlencode({"hl": hl, "gl": cc, "ceid": f"{cc}:{lang.split('-')[0]}"})
        url = f"https://news.google.com/rss?{params}"
        result.append(FeedSource(digest("google", cc, url), f"Google News — {country}", url,
                                 f"https://news.google.com/?{params}", country, cc, region, lang,
                                 "google-country", "built-in"))
    return result


def read_json(path: Path, default: Any) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return default


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    tmp.replace(path)


def balanced(sources: list[FeedSource], cap: int, regions: set[str] | None = None,
             countries: set[str] | None = None, languages: set[str] | None = None,
             allow_google_fallback: bool = True) -> list[FeedSource]:
    cap = max(1, min(int(cap), HARD_SOURCE_CAP))
    groups: dict[str, deque[FeedSource]] = defaultdict(deque)
    for s in sorted(sources, key=lambda x: (x.kind != "direct", x.country_code, x.name.casefold())):
        if not allow_google_fallback and s.kind != "direct":
            continue
        if regions and s.region.casefold() not in regions:
            continue
        if countries and s.country_code.casefold() not in countries and s.country.casefold() not in countries:
            continue
        if languages and s.language.casefold() not in languages:
            continue
        groups[s.country_code].append(s)
    order = deque(sorted(groups))
    result: list[FeedSource] = []
    while order and len(result) < cap:
        cc = order.popleft()
        if groups[cc]:
            result.append(groups[cc].popleft())
        if groups[cc]:
            order.append(cc)
    return result


def refresh_catalog(state_dir: Path, timeout: float) -> tuple[list[FeedSource], dict[str, Any]]:
    direct: list[FeedSource] = []
    failures: list[dict[str, str]] = []

    def one(item: tuple[str, str]) -> tuple[str, str, list[FeedSource], str]:
        cc, filename = item
        url = PLENARY_BASE.format(filename=urllib.parse.quote(filename))
        try:
            return cc, url, parse_opml(fetch(url, timeout), cc, url), ""
        except Exception as exc:
            return cc, url, [], f"{type(exc).__name__}: {exc}"[:500]

    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
        futures = [pool.submit(one, x) for x in PLENARY_COUNTRIES.items()]
        for cc, url, items, error in (f.result() for f in concurrent.futures.as_completed(futures)):
            direct.extend(items)
            if error:
                failures.append({"country_code": cc, "url": url, "error": error})
    unique = {s.feed_url: s for s in direct + fallback_sources()}
    sources = balanced(list(unique.values()), HARD_SOURCE_CAP)
    stats = {
        "total": len(sources),
        "direct": sum(s.kind == "direct" for s in sources),
        "fallback": sum(s.kind != "direct" for s in sources),
        "countries": len({s.country_code for s in sources}),
        "regions": len({s.region for s in sources}),
        "catalog_failures": failures,
    }
    write_json(state_dir / "source-cache.json", {"refreshed_at": iso(), "sources": [asdict(s) for s in sources], "stats": stats})
    return sources, stats


def load_catalog(state_dir: Path, refresh: bool, timeout: float) -> tuple[list[FeedSource], dict[str, Any]]:
    cached = read_json(state_dir / "source-cache.json", {})
    if not isinstance(cached, dict):
        cached = {}
    stamp = parse_date(cached.get("refreshed_at"))
    stale = not stamp or now() - stamp > timedelta(days=7)
    if refresh or stale or not cached.get("sources"):
        return refresh_catalog(state_dir, timeout)
    sources = [FeedSource(**row) for row in cached.get("sources", [])]
    return sources, cached.get("stats", {"total": len(sources)})


def seen_ids(state_dir: Path) -> set[str]:
    payload = read_json(state_dir / "seen.json", {})
    if not isinstance(payload, dict):
        return set()
    ids = payload.get("ids", [])
    return set(ids) if isinstance(ids, list) else set()


def save_seen(state_dir: Path, ids: Iterable[str]) -> None:
    ids = list(dict.fromkeys(ids))[-100_000:]
    write_json(state_dir / "seen.json", {"updated_at": iso(), "ids": ids})


def enrich_articles(articles: list[Article], timeout: float, article_workers: int, max_article_chars: int,
                    respect_robots: bool) -> dict[str, Any]:
    if not articles:
        return {"attempted": 0, "succeeded": 0, "limited": 0, "failed": 0, "errors": []}

    def one(article: Article) -> tuple[Article, str]:
        result = crawl_article(
            article.url,
            user_agent=USER_AGENT,
            timeout=timeout,
            max_chars=max_article_chars,
            respect_robots=respect_robots,
        )
        article.crawl_url = normalize_url(result.final_url) or result.final_url
        article.canonical_url = normalize_url(result.canonical_url) or article.crawl_url or article.url
        article.crawl_method = result.extraction_method
        article.crawl_bytes = result.bytes_read
        article.paywall_hint = result.paywall_hint
        if result.language and article.language in {"", "und"}:
            article.language = clean(result.language, 40)
        if result.published_at and not article.published_at:
            dt = parse_date(result.published_at)
            article.published_at = iso(dt) if dt else ""
        if result.description and not article.snippet:
            article.snippet = clean(result.description, 3500)
        if result.site_name and (not article.publisher or article.publisher.startswith("Google News")):
            article.publisher = clean(result.site_name, 300)
        if result.paywall_hint:
            article.crawl_status = "limited_access"
            article.crawl_error = "paywall/limited-access metadata detected; body not retained"
            article.article_text = ""
            return article, article.crawl_error
        if result.ok and result.text:
            article.crawl_status = "ok"
            article.article_text = clean(result.text, max_article_chars)
            return article, ""
        article.crawl_status = "blocked" if result.blocked_reason else "failed"
        article.crawl_error = result.blocked_reason or "article extraction produced no usable text"
        return article, article.crawl_error

    errors: list[dict[str, str]] = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=max(1, min(article_workers, 32))) as pool:
        futures = [pool.submit(one, article) for article in articles]
        rows = [f.result() for f in concurrent.futures.as_completed(futures)]
    for article, error in rows:
        if error:
            errors.append({"title": article.title, "url": article.url, "status": article.crawl_status, "error": error[:500]})
    return {
        "attempted": len(articles),
        "succeeded": sum(a.crawl_status == "ok" for a in articles),
        "limited": sum(a.crawl_status == "limited_access" for a in articles),
        "failed": sum(a.crawl_status not in {"ok", "limited_access"} for a in articles),
        "errors": errors[:100],
    }


def collect(state_dir: Path, max_sources: int, max_articles: int, per_source: int, since_hours: float,
            timeout: float, workers: int, refresh_sources: bool, regions: set[str] | None,
            countries: set[str] | None, languages: set[str] | None, query: str, new_only: bool,
            crawl_pages: bool = True, article_workers: int = 12, max_article_chars: int = 6000,
            respect_robots: bool = True, allow_google_fallback: bool = True) -> dict[str, Any]:
    sources, stats = load_catalog(state_dir, refresh_sources, timeout)
    selected = balanced(sources, max_sources, regions, countries, languages, allow_google_fallback)
    cutoff = now() - timedelta(hours=since_hours) if since_hours > 0 else None

    def one(source: FeedSource) -> tuple[FeedSource, list[Article], str, int]:
        started = time.perf_counter()
        try:
            items = parse_feed(fetch(source.feed_url, timeout), source)
            if cutoff:
                items = [a for a in items if not a.published_at or (parse_date(a.published_at) or cutoff) >= cutoff]
            if query:
                q = query.casefold()
                items = [a for a in items if q in f"{a.title} {a.snippet} {a.publisher}".casefold()]
            items.sort(key=lambda a: a.published_at or a.fetched_at, reverse=True)
            return source, items[:per_source], "", round((time.perf_counter() - started) * 1000)
        except Exception as exc:
            return source, [], f"{type(exc).__name__}: {exc}"[:500], round((time.perf_counter() - started) * 1000)

    with concurrent.futures.ThreadPoolExecutor(max_workers=max(1, min(workers, 32))) as pool:
        rows = [f.result() for f in concurrent.futures.as_completed([pool.submit(one, s) for s in selected])]
    merged: dict[str, Article] = {}
    for _source, items, _error, _ms in rows:
        for article in items:
            merged.setdefault(article.id, article)
    ordered = sorted(merged.values(), key=lambda a: a.published_at or a.fetched_at, reverse=True)
    old = seen_ids(state_dir) if new_only else set()
    fresh = [a for a in ordered if a.id not in old][:max_articles]
    feed_errors = [{"name": s.name, "feed_url": s.feed_url, "error": e} for s, _items, e, _ms in rows if e]
    crawl_health = enrich_articles(fresh, timeout, article_workers, max_article_chars, respect_robots) if crawl_pages else {
        "attempted": 0, "succeeded": 0, "limited": 0, "failed": 0, "errors": []
    }
    return {
        "plugin": PLUGIN_ID,
        "version": VERSION,
        "generated_at": iso(),
        "catalog": stats,
        "health": {
            "attempted": len(selected),
            "succeeded": len(selected) - len(feed_errors),
            "failed": len(feed_errors),
            "errors": feed_errors[:100],
            "crawl": crawl_health,
        },
        "selected_sources": len(selected),
        "direct_sources_selected": sum(s.kind == "direct" for s in selected),
        "fallback_sources_selected": sum(s.kind != "direct" for s in selected),
        "discovered_articles": len(ordered),
        "new_articles": len(fresh),
        "articles": [asdict(a) for a in fresh],
    }


def markdown(payload: dict[str, Any]) -> str:
    crawl = payload.get("health", {}).get("crawl", {})
    lines = [
        "# UltimateNewsFeeder knowledge batch",
        "",
        f"Generated: {payload['generated_at']}",
        f"Sources attempted: {payload['health']['attempted']}",
        f"Sources succeeded: {payload['health']['succeeded']}",
        f"Articles: {len(payload['articles'])}",
        f"Article pages crawled successfully: {crawl.get('succeeded', 0)}",
        "",
        "News evidence with provenance. Important claims should be verified against the linked publisher; crawled text is bounded and paywall/login bypass is not attempted.",
        "",
    ]
    for a in payload["articles"]:
        lines += [
            f"## {a['title']}",
            "",
            f"- Publisher: {a['publisher']}",
            f"- Country: {a['country']} ({a['country_code']})",
            f"- Region: {a['region']}",
            f"- Language: {a['language']}",
            f"- Published: {a['published_at'] or 'unknown'}",
            f"- Article URL: {a['url']}",
            f"- Canonical URL: {a.get('canonical_url') or a['url']}",
            f"- Feed: {a['feed_name']} — {a['feed_url']}",
            f"- Source kind: {a['source_kind']}",
            f"- Crawl status: {a.get('crawl_status', 'not_attempted')}",
            f"- Extraction: {a.get('crawl_method') or 'feed-only'}",
            f"- Provenance ID: {a['id']}",
            "",
            "### Feed summary",
            "",
            a['snippet'] or "(No feed summary provided.)",
            "",
        ]
        if a.get("article_text"):
            lines += ["### Crawled article evidence", "", a["article_text"], ""]
        elif a.get("crawl_error"):
            lines += ["### Crawl note", "", a["crawl_error"], ""]
    return "\n".join(lines).strip() + "\n"


def write_outputs(payload: dict[str, Any], output_dir: Path) -> dict[str, str]:
    output_dir.mkdir(parents=True, exist_ok=True)
    stamp, batch = now().strftime("%Y%m%dT%H%M%SZ"), digest(*(a["id"] for a in payload["articles"]))[:12]
    base = output_dir / f"ultimate-news-{stamp}-{batch}"
    jsonl, md = base.with_suffix(".jsonl"), base.with_suffix(".md")
    jsonl.write_text("".join(json.dumps(a, ensure_ascii=False) + "\n" for a in payload["articles"]), encoding="utf-8")
    md.write_text(markdown(payload), encoding="utf-8")
    return {"jsonl": str(jsonl.resolve()), "markdown": str(md.resolve())}


def upload_hades(path: Path, api_url: str, approved: bool, timeout: float) -> dict[str, Any]:
    if not approved:
        raise PermissionError("approved_file_write=true is required")
    boundary = "----HADESNews" + uuid.uuid4().hex
    data = path.read_bytes()
    body = (f"--{boundary}\r\nContent-Disposition: form-data; name=\"approved\"\r\n\r\ntrue\r\n"
            f"--{boundary}\r\nContent-Disposition: form-data; name=\"file\"; filename=\"{path.name}\"\r\n"
            f"Content-Type: text/markdown; charset=utf-8\r\n\r\n").encode() + data + f"\r\n--{boundary}--\r\n".encode()
    req = urllib.request.Request(api_url.rstrip("/") + "/files/upload", data=body, method="POST",
                                 headers={"User-Agent": USER_AGENT, "Content-Type": f"multipart/form-data; boundary={boundary}", "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=max(30, timeout)) as response:
        return json.loads(response.read(4 * 1024 * 1024).decode("utf-8"))
