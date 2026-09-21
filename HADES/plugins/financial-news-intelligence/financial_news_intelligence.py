#!/usr/bin/env python3
from __future__ import annotations

import argparse
import concurrent.futures
import email.utils
import hashlib
import html
from html.parser import HTMLParser
import json
import os
from pathlib import Path
import re
import sqlite3
import time
from datetime import UTC, datetime, timedelta
import urllib.error
import urllib.parse
import urllib.request
import urllib.robotparser
import uuid
import xml.etree.ElementTree as ET
from collections import Counter, defaultdict, deque
from dataclasses import asdict, dataclass
from typing import Any, Iterable

from source_catalog import CATALOG, SourceSeed

PLUGIN_ID = "financial-news-intelligence"
VERSION = "1.0.0"
MIN_SOURCES = 300
MAX_SOURCES = 500
USER_AGENT = f"HADES-{PLUGIN_ID}/{VERSION} (+direct-source financial-news collector)"


def _is_blocked_host(host: str) -> bool:
    import ipaddress

    host = (host or "").lower().strip("[]")
    if not host:
        return True
    if host in {"localhost", "metadata.google.internal"}:
        return True
    if host.endswith(".localhost") or host.endswith(".local") or host.endswith(".internal"):
        return True
    try:
        ip = ipaddress.ip_address(host)
        return bool(
            ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_multicast or ip.is_reserved or ip.is_unspecified
        )
    except ValueError:
        return False


def assert_public_http_url(url: str) -> str:
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme not in {"http", "https"}:
        raise ValueError("Only http/https URLs are allowed")
    host = (parsed.hostname or "").lower()
    if _is_blocked_host(host):
        raise ValueError(f"Private/local host blocked: {host}")
    if parsed.username or parsed.password:
        raise ValueError("URL credentials are not allowed")
    return url


def yes(value: Any) -> bool:
    return value is True or str(value).strip().lower() in {"1", "true", "yes", "on"}


def now() -> datetime:
    return datetime.now(UTC)


def iso(dt: datetime | None = None) -> str:
    dt = dt or now()
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC).isoformat().replace("+00:00", "Z")


def clean(value: str | None, limit: int = 5000) -> str:
    text = html.unescape(value or "")
    text = re.sub(r"<script\b[^>]*>.*?</script>|<style\b[^>]*>.*?</style>", " ", text, flags=re.I | re.S)
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text[:limit]


def normalize_url(url: str, base: str = "") -> str:
    if base:
        url = urllib.parse.urljoin(base, url)
    try:
        p = urllib.parse.urlsplit(html.unescape((url or "").strip()))
    except ValueError:
        return ""
    if p.scheme not in {"http", "https"}:
        return ""
    drop = {
        "utm_source", "utm_medium", "utm_campaign", "utm_term", "utm_content", "utm_id",
        "gclid", "fbclid", "mc_cid", "mc_eid", "ref", "referrer",
    }
    query = [(k, v) for k, v in urllib.parse.parse_qsl(p.query, keep_blank_values=True) if k.lower() not in drop]
    path = re.sub(r"/{2,}", "/", p.path or "/")
    return urllib.parse.urlunsplit((p.scheme.lower(), p.netloc.lower(), path, urllib.parse.urlencode(query), ""))


def digest(*parts: str) -> str:
    return hashlib.sha256("\x1f".join(parts).encode("utf-8", "ignore")).hexdigest()


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
    for candidate in (value, value.replace("Z", "+00:00")):
        try:
            dt = datetime.fromisoformat(candidate)
            return (dt if dt.tzinfo else dt.replace(tzinfo=UTC)).astimezone(UTC)
        except ValueError:
            pass
    return None


class HTMLDiscoveryParser(HTMLParser):
    def __init__(self, base_url: str):
        super().__init__(convert_charrefs=True)
        self.base_url = base_url
        self.feed_links: list[str] = []
        self.article_links: list[tuple[str, str]] = []
        self._anchor_href = ""
        self._anchor_text: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attr = {k.lower(): (v or "") for k, v in attrs}
        if tag.lower() == "link":
            rel = attr.get("rel", "").lower()
            typ = attr.get("type", "").lower()
            href = normalize_url(attr.get("href", ""), self.base_url)
            if href and "alternate" in rel and ("rss" in typ or "atom" in typ or "xml" in typ):
                self.feed_links.append(href)
        elif tag.lower() == "a":
            self._anchor_href = normalize_url(attr.get("href", ""), self.base_url)
            self._anchor_text = []

    def handle_data(self, data: str) -> None:
        if self._anchor_href:
            self._anchor_text.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() == "a" and self._anchor_href:
            text = clean(" ".join(self._anchor_text), 500)
            if text:
                self.article_links.append((self._anchor_href, text))
            self._anchor_href = ""
            self._anchor_text = []


class ArticleTextParser(HTMLParser):
    BLOCKED = {"script", "style", "nav", "footer", "header", "form", "svg", "noscript", "aside"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.blocked_depth = 0
        self.in_text_tag = 0
        self.parts: list[str] = []
        self.meta: dict[str, str] = {}
        self.canonical = ""
        self.time_values: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        tag = tag.lower()
        attr = {k.lower(): (v or "") for k, v in attrs}
        if tag in self.BLOCKED:
            self.blocked_depth += 1
        if self.blocked_depth == 0 and tag in {"p", "h1", "h2", "h3", "li", "blockquote"}:
            self.in_text_tag += 1
        if tag == "meta":
            key = (attr.get("property") or attr.get("name") or "").lower()
            content = attr.get("content", "")
            if key and content:
                self.meta[key] = content
        if tag == "link" and "canonical" in attr.get("rel", "").lower():
            self.canonical = attr.get("href", "")
        if tag == "time" and attr.get("datetime"):
            self.time_values.append(attr["datetime"])

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        if self.blocked_depth == 0 and tag in {"p", "h1", "h2", "h3", "li", "blockquote"} and self.in_text_tag:
            self.in_text_tag -= 1
            self.parts.append("\n")
        if tag in self.BLOCKED and self.blocked_depth:
            self.blocked_depth -= 1

    def handle_data(self, data: str) -> None:
        if self.blocked_depth == 0 and self.in_text_tag and data.strip():
            self.parts.append(data.strip() + " ")


@dataclass(slots=True)
class SourceResult:
    domain: str
    category: str
    seed_url: str
    method: str
    feed_url: str
    items: list[dict[str, Any]]
    elapsed_ms: int
    error: str = ""


class RobotsCache:
    def __init__(self, timeout: float):
        self.timeout = timeout
        self._cache: dict[str, urllib.robotparser.RobotFileParser | None] = {}

    def allowed(self, url: str) -> bool:
        p = urllib.parse.urlsplit(url)
        root = f"{p.scheme}://{p.netloc}"
        if root not in self._cache:
            rp = urllib.robotparser.RobotFileParser()
            robots_url = root + "/robots.txt"
            rp.set_url(robots_url)
            try:
                req = urllib.request.Request(robots_url, headers={"User-Agent": USER_AGENT})
                with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                    status = int(getattr(resp, "status", 200) or 200)
                    raw = resp.read(512_000).decode("utf-8", "replace")
                if status in {404, 410}:
                    # Missing robots.txt → allow (standard crawler behavior).
                    rp.parse([])
                else:
                    rp.parse(raw.splitlines())
                self._cache[root] = rp
            except urllib.error.HTTPError as exc:
                if int(getattr(exc, "code", 0) or 0) in {404, 410}:
                    rp.parse([])
                    self._cache[root] = rp
                else:
                    # Fail closed when robots.txt cannot be evaluated.
                    rp.parse(["User-agent: *", "Disallow: /"])
                    self._cache[root] = rp
            except Exception:
                rp.parse(["User-agent: *", "Disallow: /"])
                self._cache[root] = rp
        rp = self._cache[root]
        return rp.can_fetch(USER_AGENT, url)


def fetch_bytes(url: str, timeout: float, max_bytes: int = 5 * 1024 * 1024, accept: str = "*/*") -> tuple[bytes, str, str]:
    assert_public_http_url(url)
    opener = urllib.request.build_opener(urllib.request.HTTPHandler(), urllib.request.HTTPSHandler())
    current = url
    response = None
    for _ in range(8):
        req = urllib.request.Request(current, headers={
            "User-Agent": USER_AGENT,
            "Accept": accept,
            "Accept-Language": "en-US,en;q=0.8,*;q=0.3",
        })
        try:
            response = opener.open(req, timeout=timeout)
            break
        except urllib.error.HTTPError as exc:
            if int(getattr(exc, "code", 0) or 0) not in {301, 302, 303, 307, 308}:
                raise
            location = exc.headers.get("Location") if exc.headers else None
            if not location:
                raise
            current = assert_public_http_url(urllib.parse.urljoin(current, location))
    if response is None:
        raise RuntimeError(f"Too many redirects for {url}")
    with response:
        data = response.read(max_bytes + 1)
        final_url = assert_public_http_url(response.geturl())
        ctype = response.headers.get("Content-Type", "")
    if len(data) > max_bytes:
        raise ValueError("response exceeded size limit")
    return data, final_url, ctype


def is_feed(data: bytes, ctype: str = "") -> bool:
    head = data[:500].lstrip().lower()
    c = ctype.lower()
    return (b"<rss" in head or b"<feed" in head or b"<rdf:rdf" in head or "rss" in c or "atom" in c)


def lname(tag: str) -> str:
    return tag.rsplit("}", 1)[-1].lower()


def field(node: ET.Element, names: set[str]) -> str:
    for child in list(node):
        if lname(child.tag) in names:
            if lname(child.tag) == "link" and child.attrib.get("href"):
                return child.attrib["href"].strip()
            return "".join(child.itertext()).strip()
    return ""


def parse_feed(data: bytes, source: SourceSeed, feed_url: str, fetched_at: datetime) -> list[dict[str, Any]]:
    root = ET.fromstring(data)
    rows: list[dict[str, Any]] = []
    for item in (n for n in root.iter() if lname(n.tag) in {"item", "entry"}):
        title = clean(field(item, {"title"}), 1000)
        link = normalize_url(field(item, {"link"}), feed_url)
        if not link:
            guid = field(item, {"guid", "id"})
            link = normalize_url(guid) if guid.startswith(("http://", "https://")) else ""
        if not title or not link:
            continue
        bodies = ["".join(c.itertext()).strip() for c in list(item) if lname(c.tag) in {"description", "summary", "content", "encoded"}]
        published = parse_date(field(item, {"pubdate", "published", "updated", "date", "dc:date"}))
        rows.append({
            "title": title,
            "url": link,
            "summary": clean(max(bodies, key=len, default=""), 3500),
            "published_at": iso(published) if published else "",
            "collected_at": iso(fetched_at),
            "source_domain": source.domain,
            "source_url": source.url,
            "source_category": source.category,
            "discovery_method": "feed",
            "feed_url": feed_url,
        })
    return rows


ARTICLE_PATH_HINTS = re.compile(
    r"/(news|press|release|releases|story|stories|article|articles|markets?|business|economy|finance|invest|"
    r"earnings|results|deal|deals|merger|acquisition|crypto|blockchain|insights|research|media|company|corporate)/",
    re.I,
)
EXCLUDE_PATH_HINTS = re.compile(r"/(login|signin|signup|privacy|terms|cookie|contact|about|careers?|jobs|events?|videos?|podcasts?|tag|author)/", re.I)


def article_like(url: str, text: str, source: SourceSeed) -> bool:
    p = urllib.parse.urlsplit(url)
    if p.hostname and p.hostname.lower().removeprefix("www.") != source.domain:
        return False
    if EXCLUDE_PATH_HINTS.search(p.path + "/"):
        return False
    words = len(text.split())
    if words < 3 or len(text) < 18:
        return False
    if ARTICLE_PATH_HINTS.search(p.path + "/"):
        return True
    if re.search(r"/20\d{2}/(?:0?[1-9]|1[0-2])/(?:0?[1-9]|[12]\d|3[01])?", p.path):
        return True
    seed_path = urllib.parse.urlsplit(source.url).path.lower()
    return any(k in seed_path for k in ("news", "press", "media", "insight", "research", "market")) and words >= 5


def discover_from_html(data: bytes, final_url: str, source: SourceSeed, per_source: int) -> tuple[list[str], list[dict[str, Any]]]:
    parser = HTMLDiscoveryParser(final_url)
    parser.feed(data.decode("utf-8", "replace"))
    feeds = list(dict.fromkeys(parser.feed_links))[:8]
    rows: list[dict[str, Any]] = []
    seen: set[str] = set()
    for url, title in parser.article_links:
        url = normalize_url(url)
        if not url or url in seen or not article_like(url, title, source):
            continue
        seen.add(url)
        rows.append({
            "title": title,
            "url": url,
            "summary": "",
            "published_at": "",
            "collected_at": iso(),
            "source_domain": source.domain,
            "source_url": source.url,
            "source_category": source.category,
            "discovery_method": "homepage",
            "feed_url": "",
        })
        if len(rows) >= per_source:
            break
    return feeds, rows


def common_feed_urls(final_url: str) -> list[str]:
    p = urllib.parse.urlsplit(final_url)
    root = f"{p.scheme}://{p.netloc}"
    return [root + x for x in ("/feed", "/rss", "/rss.xml", "/feed.xml", "/atom.xml")]


def collect_source(source: SourceSeed, timeout: float, per_source: int, robots: RobotsCache | None) -> SourceResult:
    started = time.perf_counter()
    try:
        if robots and not robots.allowed(source.url):
            return SourceResult(source.domain, source.category, source.url, "blocked", "", [], 0, "robots.txt disallows seed URL")
        page, final_url, ctype = fetch_bytes(source.url, timeout, accept="application/rss+xml, application/atom+xml, application/xml, text/html;q=0.9, */*;q=0.3")
        fetched_at = now()
        if is_feed(page, ctype):
            items = parse_feed(page, source, final_url, fetched_at)[:per_source]
            return SourceResult(source.domain, source.category, source.url, "feed", final_url, items,
                                round((time.perf_counter() - started) * 1000))
        feeds, homepage_rows = discover_from_html(page, final_url, source, per_source)
        candidates = feeds + [x for x in common_feed_urls(final_url) if x not in feeds]
        for feed_url in candidates[:8]:
            try:
                if robots and not robots.allowed(feed_url):
                    continue
                raw, feed_final, feed_type = fetch_bytes(feed_url, timeout, accept="application/rss+xml, application/atom+xml, application/xml, text/xml;q=0.9, */*;q=0.2")
                if not is_feed(raw, feed_type):
                    continue
                items = parse_feed(raw, source, feed_final, fetched_at)
                if items:
                    return SourceResult(source.domain, source.category, source.url, "feed", feed_final, items[:per_source],
                                        round((time.perf_counter() - started) * 1000))
            except Exception:
                continue
        return SourceResult(source.domain, source.category, source.url, "homepage", "", homepage_rows[:per_source],
                            round((time.perf_counter() - started) * 1000))
    except Exception as exc:
        return SourceResult(source.domain, source.category, source.url, "error", "", [],
                            round((time.perf_counter() - started) * 1000), f"{type(exc).__name__}: {exc}"[:500])


def extract_article(url: str, timeout: float, max_chars: int, robots: RobotsCache | None) -> dict[str, Any]:
    if robots and not robots.allowed(url):
        return {"crawl_status": "blocked", "crawl_error": "robots.txt disallows article URL", "article_text": "", "canonical_url": url}
    try:
        raw, final_url, ctype = fetch_bytes(url, timeout, max_bytes=4 * 1024 * 1024, accept="text/html,application/xhtml+xml;q=0.9,*/*;q=0.2")
        if "html" not in ctype.lower() and b"<html" not in raw[:1000].lower():
            return {"crawl_status": "unsupported", "crawl_error": f"non-HTML content: {ctype}", "article_text": "", "canonical_url": normalize_url(final_url)}
        parser = ArticleTextParser()
        text = raw.decode("utf-8", "replace")
        parser.feed(text)
        canonical = normalize_url(parser.canonical, final_url) or normalize_url(final_url)
        body = clean(" ".join(parser.parts), max_chars)
        published = ""
        for key in ("article:published_time", "date", "datepublished", "dc.date", "parsely-pub-date"):
            dt = parse_date(parser.meta.get(key))
            if dt:
                published = iso(dt)
                break
        if not published:
            for value in parser.time_values[:5]:
                dt = parse_date(value)
                if dt:
                    published = iso(dt)
                    break
        description = clean(parser.meta.get("description") or parser.meta.get("og:description"), 2000)
        title = clean(parser.meta.get("og:title") or parser.meta.get("twitter:title"), 1000)
        return {
            "crawl_status": "ok" if body else "empty",
            "crawl_error": "" if body else "no usable article text extracted",
            "article_text": body,
            "canonical_url": canonical,
            "page_title": title,
            "page_description": description,
            "page_published_at": published,
        }
    except Exception as exc:
        return {"crawl_status": "failed", "crawl_error": f"{type(exc).__name__}: {exc}"[:500], "article_text": "", "canonical_url": normalize_url(url)}


EVENT_RULES: dict[str, tuple[int, tuple[str, ...]]] = {
    "earnings": (22, ("earnings", "revenue", "profit", "loss", "eps", "guidance", "quarter results", "full-year results", "forecast")),
    "merger_acquisition_deal": (30, ("acquisition", "acquire", "merger", "takeover", "buyout", "deal", "strategic investment", "joint venture")),
    "capital_markets": (24, ("ipo", "initial public offering", "secondary offering", "bond issuance", "debt offering", "share sale", "capital raise", "funding round")),
    "bankruptcy_distress": (35, ("bankruptcy", "chapter 11", "insolvency", "default", "restructuring", "liquidity crisis", "going concern")),
    "regulatory_legal": (26, ("sec charges", "lawsuit", "antitrust", "regulator", "investigation", "fine", "settlement", "sanction", "approval", "blocked by")),
    "management_governance": (18, ("ceo", "cfo", "chairman", "resigns", "resignation", "appointed", "board of directors", "activist investor")),
    "product_operations": (14, ("launches", "launch", "recall", "factory", "production", "shipment", "supply chain", "contract", "order", "partnership")),
    "cyber_security": (28, ("cyberattack", "data breach", "ransomware", "security incident", "hack", "exploit", "vulnerability")),
    "macro_rates": (24, ("interest rate", "rate cut", "rate hike", "inflation", "cpi", "gdp", "unemployment", "payrolls", "central bank", "monetary policy")),
    "commodities_energy": (18, ("oil price", "crude", "natural gas", "gold", "copper", "opec", "production cut", "commodity")),
    "crypto_market": (22, ("bitcoin", "ethereum", "crypto", "stablecoin", "token", "blockchain", "defi", "etf approval", "exchange hack")),
    "analyst_rating": (16, ("upgrade", "downgrade", "price target", "rating", "outperform", "underperform", "buy rating", "sell rating")),
}

TICKER_PATTERNS = [
    re.compile(r"\$([A-Z][A-Z0-9.\-]{0,5})\b"),
    re.compile(r"\b(?:NASDAQ|NYSE|AMEX|LSE|TSX|ASX|HKEX|SGX|NSE|BSE)\s*[:\-]\s*([A-Z0-9.\-]{1,8})\b", re.I),
]
CRYPTO_SYMBOLS = {"BTC", "ETH", "SOL", "XRP", "BNB", "ADA", "DOGE", "AVAX", "LINK", "DOT", "LTC", "BCH", "TRX", "TON", "SUI", "USDT", "USDC"}


def analyze(item: dict[str, Any]) -> dict[str, Any]:
    text = f"{item.get('title','')} {item.get('summary','')} {item.get('article_text','')}".casefold()
    events: list[str] = []
    score = 8
    reasons: list[str] = []
    for event, (weight, terms) in EVENT_RULES.items():
        matched = [term for term in terms if term.casefold() in text]
        if matched:
            events.append(event)
            score += weight
            reasons.append(f"{event}: {', '.join(matched[:3])}")
    category = item.get("source_category", "")
    if category in {"official_macro_regulation", "exchanges_market_infra"}:
        score += 12
        reasons.append("primary official/market-infrastructure source")
    elif category == "corporate_newsrooms":
        score += 8
        reasons.append("primary corporate source")
    elif category == "global_finance":
        score += 4
    title = item.get("title", "")
    for high in ("bankruptcy", "acquisition", "merger", "earnings", "sec charges", "rate cut", "rate hike", "cyberattack", "data breach"):
        if high in title.casefold():
            score += 8
            reasons.append(f"headline trigger: {high}")
    tickers: set[str] = set()
    raw = f"{item.get('title','')} {item.get('summary','')}"
    for pattern in TICKER_PATTERNS:
        tickers.update(m.group(1).upper() for m in pattern.finditer(raw))
    upper_words = set(re.findall(r"\b[A-Z]{2,5}\b", raw))
    crypto = sorted(upper_words & CRYPTO_SYMBOLS)
    return {
        "event_types": sorted(set(events)),
        "impact_score": max(0, min(score, 100)),
        "impact_reasons": reasons[:8],
        "tickers": sorted(tickers)[:20],
        "crypto_symbols": crypto,
    }


def select_sources(limit: int, categories: set[str] | None = None) -> list[SourceSeed]:
    if not MIN_SOURCES <= limit <= MAX_SOURCES:
        raise ValueError(f"max_sources must be {MIN_SOURCES}..{MAX_SOURCES}")
    groups: dict[str, deque[SourceSeed]] = defaultdict(deque)
    for source in CATALOG:
        if categories and source.category not in categories:
            continue
        groups[source.category].append(source)
    if sum(len(v) for v in groups.values()) < MIN_SOURCES:
        raise ValueError("category filter leaves fewer than 300 source websites")
    order = deque(sorted(groups, key=lambda c: (-groups[c][0].priority, c)))
    selected: list[SourceSeed] = []
    while order and len(selected) < limit:
        category = order.popleft()
        if groups[category]:
            selected.append(groups[category].popleft())
        if groups[category]:
            order.append(category)
    return selected


class SeenStore:
    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(path)
        self.conn.execute("CREATE TABLE IF NOT EXISTS seen (id TEXT PRIMARY KEY, url TEXT NOT NULL, first_seen TEXT NOT NULL)")
        self.conn.commit()

    def has(self, item_id: str) -> bool:
        return self.conn.execute("SELECT 1 FROM seen WHERE id=?", (item_id,)).fetchone() is not None

    def add_many(self, items: Iterable[dict[str, Any]]) -> None:
        self.conn.executemany("INSERT OR IGNORE INTO seen(id,url,first_seen) VALUES(?,?,?)",
                              [(x["id"], x["url"], iso()) for x in items])
        self.conn.commit()

    def close(self) -> None:
        self.conn.close()


def state_dir(value: str = "") -> Path:
    if value:
        return Path(value).expanduser().resolve()
    root = os.getenv("HADES_PLUGIN_DATA_DIR") or os.getenv("HADES_DATA_DIR") or str(Path.cwd())
    return Path(root).expanduser().resolve() / ".financial-news-intelligence"


def dedupe(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_url: dict[str, dict[str, Any]] = {}
    by_title: dict[str, str] = {}
    for item in items:
        canonical = normalize_url(item.get("canonical_url") or item.get("url") or "")
        if not canonical:
            continue
        item["canonical_url"] = canonical
        key = re.sub(r"[^a-z0-9]+", " ", item.get("title", "").casefold()).strip()
        title_sig = " ".join(key.split()[:20])
        if canonical in by_url or (title_sig and title_sig in by_title):
            continue
        item["id"] = digest(item.get("source_domain", ""), canonical, title_sig)
        by_url[canonical] = item
        if title_sig:
            by_title[title_sig] = canonical
    return list(by_url.values())


def collect(args: argparse.Namespace) -> dict[str, Any]:
    categories = {x.strip() for x in args.categories.split(",") if x.strip()} or None
    selected = select_sources(args.max_sources, categories)
    robots = RobotsCache(args.timeout_seconds) if yes(args.respect_robots) else None
    started = time.perf_counter()

    with concurrent.futures.ThreadPoolExecutor(max_workers=max(1, min(args.workers, 32))) as pool:
        futures = [pool.submit(collect_source, s, args.timeout_seconds, args.per_source, robots) for s in selected]
        source_rows = [f.result() for f in concurrent.futures.as_completed(futures)]

    all_items = [item for row in source_rows for item in row.items]
    cutoff = now() - timedelta(hours=args.since_hours) if args.since_hours > 0 else None
    if cutoff:
        filtered = []
        for item in all_items:
            dt = parse_date(item.get("published_at"))
            if dt and dt < cutoff:
                continue
            filtered.append(item)
        all_items = filtered
    if args.query:
        q = args.query.casefold()
        all_items = [x for x in all_items if q in f"{x.get('title','')} {x.get('summary','')} {x.get('source_domain','')}".casefold()]
    all_items = dedupe(all_items)
    all_items.sort(key=lambda x: x.get("published_at") or x.get("collected_at") or "", reverse=True)
    all_items = all_items[:args.max_articles]

    if yes(args.crawl_pages) and all_items:
        with concurrent.futures.ThreadPoolExecutor(max_workers=max(1, min(args.article_workers, 32))) as pool:
            futures = {pool.submit(extract_article, x["url"], args.timeout_seconds, args.max_article_chars, robots): x for x in all_items}
            for future in concurrent.futures.as_completed(futures):
                item = futures[future]
                extra = future.result()
                item.update(extra)
                if not item.get("summary") and extra.get("page_description"):
                    item["summary"] = extra["page_description"]
                if not item.get("published_at") and extra.get("page_published_at"):
                    item["published_at"] = extra["page_published_at"]
                if extra.get("page_title") and len(item.get("title", "")) < 8:
                    item["title"] = extra["page_title"]

    for item in all_items:
        item.update(analyze(item))
    all_items = [x for x in all_items if x["impact_score"] >= args.min_impact]
    all_items.sort(key=lambda x: (x["impact_score"], x.get("published_at") or x.get("collected_at") or ""), reverse=True)

    store = SeenStore(state_dir(args.state_dir) / "seen.sqlite3")
    try:
        if yes(args.new_only):
            all_items = [x for x in all_items if not store.has(x["id"])]
        all_items = all_items[:args.max_articles]
        store.add_many(all_items)
    finally:
        store.close()

    errors = [asdict(x) for x in source_rows if x.error]
    succeeded = sum(bool(x.items) for x in source_rows)
    methods = Counter(x.method for x in source_rows)
    return {
        "plugin": PLUGIN_ID,
        "version": VERSION,
        "generated_at": iso(),
        "source_contract": {"minimum": MIN_SOURCES, "maximum": MAX_SOURCES, "catalog_websites": len(CATALOG), "google_news_used": False},
        "selected_sources": len(selected),
        "source_categories": dict(sorted(Counter(s.category for s in selected).items())),
        "coverage": {
            "target_websites_with_items": MIN_SOURCES,
            "websites_with_items": succeeded,
            "target_met": succeeded >= MIN_SOURCES,
            "note": "A source counts only when this run produced at least one candidate item; reachability changes over time."
        },
        "health": {
            "attempted": len(selected),
            "succeeded_with_items": succeeded,
            "failed_or_empty": len(selected) - succeeded,
            "methods": dict(methods),
            "errors": errors[:100],
            "elapsed_ms": round((time.perf_counter() - started) * 1000),
        },
        "article_count": len(all_items),
        "articles": all_items,
    }


def write_outputs(payload: dict[str, Any], output_dir: Path) -> dict[str, str]:
    output_dir.mkdir(parents=True, exist_ok=True)
    stamp = now().strftime("%Y%m%dT%H%M%SZ")
    batch = digest(*(x["id"] for x in payload["articles"]))[:12] if payload["articles"] else "empty"
    base = output_dir / f"financial-news-{stamp}-{batch}"
    jsonl = base.with_suffix(".jsonl")
    summary = base.with_suffix(".json")
    md = base.with_suffix(".md")
    jsonl.write_text("".join(json.dumps(x, ensure_ascii=False) + "\n" for x in payload["articles"]), encoding="utf-8")
    summary.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    lines = [
        "# HADES Financial News Intelligence",
        "",
        f"Generated: {payload['generated_at']}",
        f"Direct websites attempted: {payload['selected_sources']}",
        f"Articles: {payload['article_count']}",
        "",
        "Impact scores are heuristic prioritization signals, not trading advice or certainty about price direction.",
        "",
    ]
    for a in payload["articles"]:
        lines += [
            f"## [{a['impact_score']}] {a['title']}",
            "",
            f"- Source: {a['source_domain']} ({a['source_category']})",
            f"- Published: {a.get('published_at') or 'unknown'}",
            f"- URL: {a['url']}",
            f"- Events: {', '.join(a['event_types']) or 'general-financial'}",
            f"- Tickers: {', '.join(a['tickers']) or '-'}",
            f"- Crypto: {', '.join(a['crypto_symbols']) or '-'}",
            "",
            a.get("summary") or "",
            "",
        ]
        if a.get("article_text"):
            lines += ["### Extracted evidence", "", a["article_text"], ""]
    md.write_text("\n".join(lines).strip() + "\n", encoding="utf-8")
    return {"jsonl": str(jsonl.resolve()), "json": str(summary.resolve()), "markdown": str(md.resolve())}


def upload_hades(path: Path, api_url: str, approved: bool, timeout: float) -> dict[str, Any]:
    if not approved:
        raise PermissionError("approved_file_write=true is required")
    boundary = "----HADESFinancialNews" + uuid.uuid4().hex
    data = path.read_bytes()
    body = (f"--{boundary}\r\nContent-Disposition: form-data; name=\"approved\"\r\n\r\ntrue\r\n"
            f"--{boundary}\r\nContent-Disposition: form-data; name=\"file\"; filename=\"{path.name}\"\r\n"
            f"Content-Type: text/markdown; charset=utf-8\r\n\r\n").encode() + data + f"\r\n--{boundary}--\r\n".encode()
    req = urllib.request.Request(api_url.rstrip("/") + "/files/upload", data=body, method="POST", headers={
        "User-Agent": USER_AGENT,
        "Content-Type": f"multipart/form-data; boundary={boundary}",
        "Accept": "application/json",
    })
    with urllib.request.urlopen(req, timeout=max(30, timeout)) as response:
        return json.loads(response.read(4 * 1024 * 1024).decode("utf-8"))


def cmd_fetch(args: argparse.Namespace) -> int:
    payload = collect(args)
    payload["outputs"] = write_outputs(payload, Path(args.output_dir).expanduser().resolve())
    articles = int(payload.get("article_count") or 0)
    succeeded = int((payload.get("health") or {}).get("succeeded_with_items") or 0)
    if articles <= 0 or succeeded <= 0:
        payload = {
            **payload,
            "ok": False,
            "error": "no_articles_collected",
            "error_detail": "All sources failed or returned empty; refusing false success.",
        }
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 2
    payload = {**payload, "ok": True}
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


def cmd_feed(args: argparse.Namespace) -> int:
    payload = collect(args)
    articles = int(payload.get("article_count") or 0)
    succeeded = int((payload.get("health") or {}).get("succeeded_with_items") or 0)
    if articles <= 0 or succeeded <= 0:
        payload = {
            **payload,
            "ok": False,
            "error": "no_articles_collected",
            "error_detail": "All sources failed or returned empty; refusing false success.",
            "ingest": {"skipped": True, "reason": "no new articles"},
        }
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 2
    outputs = write_outputs(payload, Path(args.output_dir).expanduser().resolve())
    ingest = upload_hades(Path(outputs["markdown"]), args.hades_api_url, yes(args.approved_file_write), args.timeout_seconds)
    ingest_ok = bool(ingest) and not ingest.get("error") and (
        ingest.get("ok") is True
        or ingest.get("id")
        or ingest.get("document_id")
        or ingest.get("path")
        or ingest.get("file_id")
    )
    if not ingest_ok:
        print(json.dumps({**payload, "ok": False, "error": "ingest_failed", "outputs": outputs, "ingest": ingest}, ensure_ascii=False, indent=2))
        return 2
    print(json.dumps({**payload, "ok": True, "outputs": outputs, "ingest": ingest}, ensure_ascii=False, indent=2))
    return 0


def cmd_sources(args: argparse.Namespace) -> int:
    categories = {x.strip() for x in args.categories.split(",") if x.strip()} or None
    selected = select_sources(args.max_sources, categories)
    print(json.dumps({
        "plugin": PLUGIN_ID,
        "version": VERSION,
        "catalog_websites": len(CATALOG),
        "selected": len(selected),
        "minimum": MIN_SOURCES,
        "maximum": MAX_SOURCES,
        "google_news_used": False,
        "by_category": dict(sorted(Counter(s.category for s in selected).items())),
        "sources": [asdict(s) | {"domain": s.domain} for s in selected[:args.show]],
    }, ensure_ascii=False, indent=2))
    return 0


def cmd_audit(args: argparse.Namespace) -> int:
    categories = {x.strip() for x in args.categories.split(",") if x.strip()} or None
    selected = select_sources(args.max_sources, categories)
    robots = RobotsCache(args.timeout_seconds) if yes(args.respect_robots) else None
    with concurrent.futures.ThreadPoolExecutor(max_workers=max(1, min(args.workers, 32))) as pool:
        futures = [pool.submit(collect_source, s, args.timeout_seconds, 1, robots) for s in selected]
        rows = [f.result() for f in concurrent.futures.as_completed(futures)]
    rows.sort(key=lambda x: (x.error != "", x.domain))
    with_items = sum(bool(x.items) for x in rows)
    without_items = sum(not x.items for x in rows)
    ok = bool(rows) and with_items > 0
    print(json.dumps({
        "plugin": PLUGIN_ID,
        "ok": ok,
        "audited": len(rows),
        "with_items": with_items,
        "without_items": without_items,
        "methods": dict(Counter(x.method for x in rows)),
        "rows": [asdict(x) | {"items": len(x.items)} for x in rows[:args.show]],
        **({} if ok else {"error": "audit_found_no_items"}),
    }, ensure_ascii=False, indent=2))
    return 0 if ok else 2


def cmd_terminal(_args: argparse.Namespace) -> int:
    root = Path(__file__).resolve().parent
    if os.name == "nt":
        import subprocess
        subprocess.Popen(["cmd.exe", "/K", f'cd /d "{root}"'])
    else:
        import subprocess
        shell = os.environ.get("SHELL", "/bin/sh")
        subprocess.Popen([shell], cwd=root)
    print(json.dumps({"plugin": PLUGIN_ID, "terminal_opened": True, "cwd": str(root)}))
    return 0


def add_common(p: argparse.ArgumentParser) -> None:
    p.add_argument("--state-dir", default="")
    p.add_argument("--output-dir", default="financial-news-output")
    p.add_argument("--max-sources", type=int, default=480)
    p.add_argument("--max-articles", type=int, default=1500)
    p.add_argument("--per-source", type=int, default=6)
    p.add_argument("--since-hours", type=float, default=48)
    p.add_argument("--timeout-seconds", type=float, default=12)
    p.add_argument("--workers", type=int, default=20)
    p.add_argument("--article-workers", type=int, default=16)
    p.add_argument("--crawl-pages", default="true")
    p.add_argument("--max-article-chars", type=int, default=6000)
    p.add_argument("--respect-robots", default="true")
    p.add_argument("--new-only", default="true")
    p.add_argument("--min-impact", type=int, default=10)
    p.add_argument("--query", default="")
    p.add_argument("--categories", default="")


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Direct-source financial news intelligence collector for HADES")
    sub = p.add_subparsers(dest="command", required=True)
    a = sub.add_parser("fetch"); add_common(a); a.set_defaults(func=cmd_fetch)
    a = sub.add_parser("feed-hades"); add_common(a); a.add_argument("--hades-api-url", default=os.getenv("HADES_API_URL", "http://127.0.0.1:8000/api")); a.add_argument("--approved-file-write", default="false"); a.set_defaults(func=cmd_feed)
    a = sub.add_parser("sources"); a.add_argument("--max-sources", type=int, default=480); a.add_argument("--categories", default=""); a.add_argument("--show", type=int, default=30); a.set_defaults(func=cmd_sources)
    a = sub.add_parser("audit"); a.add_argument("--max-sources", type=int, default=480); a.add_argument("--categories", default=""); a.add_argument("--timeout-seconds", type=float, default=8); a.add_argument("--workers", type=int, default=24); a.add_argument("--respect-robots", default="true"); a.add_argument("--show", type=int, default=100); a.set_defaults(func=cmd_audit)
    a = sub.add_parser("terminal"); a.set_defaults(func=cmd_terminal)
    return p


def validate_args(args: argparse.Namespace) -> None:
    if hasattr(args, "max_sources") and not MIN_SOURCES <= args.max_sources <= MAX_SOURCES:
        raise ValueError(f"max_sources must be {MIN_SOURCES}..{MAX_SOURCES}")
    if hasattr(args, "max_articles") and not 1 <= args.max_articles <= 50_000:
        raise ValueError("max_articles must be 1..50000")
    if hasattr(args, "per_source") and not 1 <= args.per_source <= 100:
        raise ValueError("per_source must be 1..100")
    if hasattr(args, "max_article_chars") and not 500 <= args.max_article_chars <= 15_000:
        raise ValueError("max_article_chars must be 500..15000")
    if hasattr(args, "min_impact") and not 0 <= args.min_impact <= 100:
        raise ValueError("min_impact must be 0..100")


def main() -> int:
    args = parser().parse_args()
    try:
        validate_args(args)
        return int(args.func(args))
    except KeyboardInterrupt:
        print(json.dumps({"plugin": PLUGIN_ID, "status": "cancelled"}))
        return 130
    except Exception as exc:
        print(json.dumps({"plugin": PLUGIN_ID, "status": "error", "error": f"{type(exc).__name__}: {exc}"}, ensure_ascii=False))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
