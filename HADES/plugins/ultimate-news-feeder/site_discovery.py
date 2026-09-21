from __future__ import annotations

import concurrent.futures
import re
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from dataclasses import dataclass, asdict
from html import unescape
from html.parser import HTMLParser
from typing import Iterable

from article_crawler import allowed_by_robots

MAX_SITEMAP_BYTES = 8 * 1024 * 1024
MAX_HOMEPAGE_BYTES = 4 * 1024 * 1024


def _norm(value: str) -> str:
    return re.sub(r"\s+", " ", unescape(value or "")).strip()


def _origin(url: str) -> str:
    p = urllib.parse.urlsplit(url)
    return urllib.parse.urlunsplit((p.scheme.lower(), p.netloc.lower(), "", "", ""))


def _same_site(a: str, b: str) -> bool:
    return urllib.parse.urlsplit(a).netloc.lower().removeprefix("www.") == urllib.parse.urlsplit(b).netloc.lower().removeprefix("www.")


def _fetch(url: str, user_agent: str, timeout: float, max_bytes: int, accept: str) -> tuple[bytes, str, str]:
    from ssrf import open_public_url

    with open_public_url(
        url,
        headers={"User-Agent": user_agent, "Accept": accept},
        timeout=timeout,
    ) as response:
        data = response.read(max_bytes + 1)
        final_url = response.geturl()
        ctype = (response.headers.get_content_type() or "").lower()
    if len(data) > max_bytes:
        raise ValueError("response too large")
    return data, final_url, ctype


@dataclass(frozen=True)
class DiscoveredURL:
    url: str
    title: str = ""
    published_at: str = ""
    method: str = ""
    source_page: str = ""

    def to_dict(self) -> dict[str, str]:
        return asdict(self)


class _HomeParser(HTMLParser):
    def __init__(self, base_url: str) -> None:
        super().__init__(convert_charrefs=True)
        self.base_url = base_url
        self.links: list[tuple[str, str]] = []
        self._href = ""
        self._text: list[str] = []
        self._jsonld = False
        self._jsonld_buf: list[str] = []
        self.jsonld_chunks: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        data = {str(k).lower(): (v or "") for k, v in attrs}
        if tag.lower() == "a" and data.get("href"):
            self._href = urllib.parse.urljoin(self.base_url, data["href"])
            self._text = []
        if tag.lower() == "script" and "ld+json" in data.get("type", "").lower():
            self._jsonld = True
            self._jsonld_buf = []

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() == "a" and self._href:
            self.links.append((self._href, _norm(" ".join(self._text))))
            self._href = ""
            self._text = []
        if tag.lower() == "script" and self._jsonld:
            self.jsonld_chunks.append("".join(self._jsonld_buf))
            self._jsonld = False
            self._jsonld_buf = []

    def handle_data(self, data: str) -> None:
        if self._href:
            self._text.append(data)
        if self._jsonld:
            self._jsonld_buf.append(data)


_SKIP_PATH = re.compile(r"/(?:login|signin|signup|account|privacy|terms|cookies?|contact|about|authors?|tags?|topics?|categories?|search|subscribe|newsletter)(?:/|$)", re.I)
_MEDIA_EXT = re.compile(r"\.(?:jpg|jpeg|png|gif|webp|svg|pdf|mp3|mp4|mov|avi|zip)(?:$|\?)", re.I)
_DATEISH = re.compile(r"/(?:20\d{2})(?:/|-)(?:0?[1-9]|1[0-2])(?:/|-)")
_NEWSISH = re.compile(r"/(?:news|world|politics|business|economy|tech|technology|science|health|sport|sports|culture|article|story|stories|breaking)/", re.I)


def _link_score(url: str, title: str) -> int:
    p = urllib.parse.urlsplit(url)
    path = p.path or "/"
    if p.scheme not in {"http", "https"} or _MEDIA_EXT.search(url) or _SKIP_PATH.search(path):
        return -100
    score = 0
    if len(title) >= 24:
        score += 2
    if len(title) >= 50:
        score += 1
    if _DATEISH.search(path):
        score += 3
    if _NEWSISH.search(path):
        score += 2
    slug = path.rstrip("/").split("/")[-1]
    if len(slug) >= 24 and ("-" in slug or "_" in slug):
        score += 2
    if path.count("/") >= 3:
        score += 1
    if p.query:
        score -= 1
    return score


def parse_sitemap(data: bytes, source_url: str = "") -> tuple[list[DiscoveredURL], list[str]]:
    root = ET.fromstring(data)
    tag = root.tag.rsplit("}", 1)[-1].lower()
    urls: list[DiscoveredURL] = []
    nested: list[str] = []
    for node in list(root):
        lname = node.tag.rsplit("}", 1)[-1].lower()
        if tag == "sitemapindex" and lname == "sitemap":
            loc = next(("".join(x.itertext()).strip() for x in list(node) if x.tag.rsplit("}", 1)[-1].lower() == "loc"), "")
            if loc:
                nested.append(urllib.parse.urljoin(source_url, loc))
            continue
        if lname != "url":
            continue
        loc = ""
        lastmod = ""
        title = ""
        publication = ""
        for child in node.iter():
            n = child.tag.rsplit("}", 1)[-1].lower()
            value = _norm("".join(child.itertext()))
            if n == "loc" and not loc:
                loc = value
            elif n == "lastmod" and not lastmod:
                lastmod = value
            elif n == "title" and not title:
                title = value
            elif n == "publication_date" and not publication:
                publication = value
        if loc:
            urls.append(DiscoveredURL(urllib.parse.urljoin(source_url, loc), title[:1000], (publication or lastmod)[:100], "sitemap", source_url))
    return urls, nested


def robots_sitemaps(home_url: str, user_agent: str, timeout: float) -> list[str]:
    origin = _origin(home_url)
    robots = origin.rstrip("/") + "/robots.txt"
    try:
        raw, _, _ = _fetch(robots, user_agent, min(timeout, 8), 512 * 1024, "text/plain,*/*;q=0.1")
    except Exception:
        return []
    out: list[str] = []
    for line in raw.decode("utf-8", "replace").splitlines():
        if line.lower().startswith("sitemap:"):
            value = line.split(":", 1)[1].strip()
            if value.startswith(("http://", "https://")):
                out.append(value)
    return out


def discover_homepage(home_url: str, user_agent: str, timeout: float, max_urls: int, respect_robots: bool) -> list[DiscoveredURL]:
    if respect_robots and not allowed_by_robots(home_url, user_agent, timeout):
        return []
    try:
        raw, final_url, ctype = _fetch(home_url, user_agent, timeout, MAX_HOMEPAGE_BYTES, "text/html,application/xhtml+xml;q=0.9,*/*;q=0.2")
    except Exception:
        return []
    if ctype not in {"text/html", "application/xhtml+xml", "text/plain"}:
        return []
    parser = _HomeParser(final_url)
    parser.feed(raw.decode("utf-8", "replace"))
    ranked: list[tuple[int, DiscoveredURL]] = []
    seen: set[str] = set()
    for url, title in parser.links:
        if not _same_site(final_url, url):
            continue
        p = urllib.parse.urlsplit(url)
        normalized = urllib.parse.urlunsplit((p.scheme.lower(), p.netloc.lower(), p.path or "/", p.query, ""))
        if normalized in seen:
            continue
        seen.add(normalized)
        score = _link_score(normalized, title)
        if score < 3:
            continue
        if respect_robots and not allowed_by_robots(normalized, user_agent, timeout):
            continue
        ranked.append((score, DiscoveredURL(normalized, title[:1000], "", "homepage", final_url)))
    ranked.sort(key=lambda item: (item[0], len(item[1].title)), reverse=True)
    return [item for _, item in ranked[:max_urls]]


def discover_site(home_url: str, user_agent: str, timeout: float, max_urls: int = 8,
                  max_sitemaps: int = 12, respect_robots: bool = True) -> list[DiscoveredURL]:
    origin = _origin(home_url)
    if not origin:
        return []
    sitemap_queue: list[str] = []
    sitemap_queue.extend(robots_sitemaps(home_url, user_agent, timeout))
    sitemap_queue.extend([
        origin.rstrip("/") + "/sitemap.xml",
        origin.rstrip("/") + "/sitemap_index.xml",
        origin.rstrip("/") + "/news-sitemap.xml",
        origin.rstrip("/") + "/news_sitemap.xml",
    ])
    seen_maps: set[str] = set()
    candidates: dict[str, DiscoveredURL] = {}
    while sitemap_queue and len(seen_maps) < max_sitemaps and len(candidates) < max_urls * 6:
        sitemap = sitemap_queue.pop(0)
        if sitemap in seen_maps or not _same_site(origin, sitemap):
            continue
        seen_maps.add(sitemap)
        if respect_robots and not allowed_by_robots(sitemap, user_agent, timeout):
            continue
        try:
            raw, final_url, ctype = _fetch(sitemap, user_agent, timeout, MAX_SITEMAP_BYTES, "application/xml,text/xml,*/*;q=0.2")
            if "xml" not in ctype and not raw.lstrip().startswith(b"<"):
                continue
            urls, nested = parse_sitemap(raw, final_url)
        except Exception:
            continue
        for nested_url in nested:
            if _same_site(origin, nested_url) and nested_url not in seen_maps:
                sitemap_queue.append(nested_url)
        for item in urls:
            if not _same_site(origin, item.url) or _link_score(item.url, item.title) < 1:
                continue
            if respect_robots and not allowed_by_robots(item.url, user_agent, timeout):
                continue
            candidates.setdefault(item.url, item)
    ordered = sorted(candidates.values(), key=lambda x: (x.published_at, len(x.title)), reverse=True)
    result = ordered[:max_urls]
    if len(result) < max_urls:
        for item in discover_homepage(home_url, user_agent, timeout, max_urls * 2, respect_robots):
            if item.url not in candidates:
                result.append(item)
                candidates[item.url] = item
                if len(result) >= max_urls:
                    break
    return result[:max_urls]


def discover_sources(sources: Iterable[object], user_agent: str, timeout: float, max_sites: int = 150,
                     max_urls_per_site: int = 6, workers: int = 12, respect_robots: bool = True) -> dict[str, object]:
    picked: list[object] = []
    seen_home: set[str] = set()
    for source in sources:
        home_url = getattr(source, "home_url", "") or ""
        if not home_url or getattr(source, "kind", "") != "direct":
            continue
        key = _origin(home_url)
        if not key or key in seen_home:
            continue
        seen_home.add(key)
        picked.append(source)
        if len(picked) >= max_sites:
            break

    rows: list[dict[str, object]] = []

    def one(source: object) -> dict[str, object]:
        home = getattr(source, "home_url", "")
        try:
            items = discover_site(home, user_agent, timeout, max_urls_per_site, respect_robots=respect_robots)
            return {"source": source, "items": items, "error": ""}
        except Exception as exc:
            return {"source": source, "items": [], "error": f"{type(exc).__name__}: {exc}"[:500]}

    with concurrent.futures.ThreadPoolExecutor(max_workers=max(1, min(workers, 32))) as pool:
        rows = [f.result() for f in concurrent.futures.as_completed([pool.submit(one, source) for source in picked])]

    discovered = sum(len(row["items"]) for row in rows)
    return {
        "sites_attempted": len(picked),
        "sites_succeeded": sum(not row["error"] for row in rows),
        "sites_failed": sum(bool(row["error"]) for row in rows),
        "urls_discovered": discovered,
        "rows": rows,
        "errors": [
            {"source": getattr(row["source"], "name", ""), "home_url": getattr(row["source"], "home_url", ""), "error": row["error"]}
            for row in rows if row["error"]
        ][:100],
    }
