from __future__ import annotations

import json
import re
import threading
import urllib.parse
import urllib.request
import urllib.robotparser
from dataclasses import dataclass
from html import unescape
from html.parser import HTMLParser
from typing import Any

DEFAULT_MAX_HTML_BYTES = 4 * 1024 * 1024
DEFAULT_MAX_TEXT_CHARS = 6000


def _norm_space(value: str) -> str:
    return re.sub(r"\s+", " ", unescape(value or "")).strip()


def _walk_json(value: Any):
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from _walk_json(child)
    elif isinstance(value, list):
        for child in value:
            yield from _walk_json(child)


class _ArticleHTMLParser(HTMLParser):
    BLOCKED = {"script", "style", "noscript", "svg", "canvas", "form", "nav", "footer", "aside"}

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._blocked_depth = 0
        self._article_depth = 0
        self._main_depth = 0
        self._p_depth = 0
        self._script_type = ""
        self._script_buf: list[str] = []
        self.article_parts: list[str] = []
        self.main_parts: list[str] = []
        self.paragraphs: list[str] = []
        self._current_p: list[str] = []
        self.json_ld: list[str] = []
        self.title = ""
        self.description = ""
        self.published = ""
        self.canonical = ""
        self.site_name = ""
        self.language = ""
        self.paywall_hint = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        tag = tag.lower()
        data = {str(k).lower(): (v or "") for k, v in attrs}
        if tag == "html" and data.get("lang"):
            self.language = _norm_space(data["lang"])[:40]
        if tag in self.BLOCKED:
            self._blocked_depth += 1
        if tag == "script":
            self._script_type = data.get("type", "").lower()
            self._script_buf = []
        if tag == "article":
            self._article_depth += 1
        if tag == "main":
            self._main_depth += 1
        if tag == "p":
            self._p_depth += 1
            self._current_p = []
        if tag == "meta":
            key = (data.get("property") or data.get("name") or data.get("itemprop") or "").lower()
            value = _norm_space(data.get("content", ""))
            if key in {"og:title", "twitter:title", "headline"} and value and not self.title:
                self.title = value[:1000]
            elif key in {"description", "og:description", "twitter:description"} and value and not self.description:
                self.description = value[:2000]
            elif key in {"article:published_time", "datepublished", "date", "pubdate"} and value and not self.published:
                self.published = value[:100]
            elif key == "og:site_name" and value:
                self.site_name = value[:300]
            elif key in {"isaccessibleforfree", "meteredpaywall"} and value.lower() in {"false", "0", "no", "true"}:
                if key == "meteredpaywall" or value.lower() in {"false", "0", "no"}:
                    self.paywall_hint = True
        if tag == "link":
            rel = {x.strip().lower() for x in data.get("rel", "").split()}
            if "canonical" in rel and data.get("href"):
                self.canonical = data["href"]

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        if tag == "p":
            text = _norm_space(" ".join(self._current_p))
            if len(text) >= 20:
                self.paragraphs.append(text)
            self._current_p = []
            self._p_depth = max(0, self._p_depth - 1)
        if tag == "article":
            self._article_depth = max(0, self._article_depth - 1)
        if tag == "main":
            self._main_depth = max(0, self._main_depth - 1)
        if tag == "script":
            if "ld+json" in self._script_type and self._script_buf:
                self.json_ld.append("".join(self._script_buf))
            self._script_type = ""
            self._script_buf = []
        if tag in self.BLOCKED:
            self._blocked_depth = max(0, self._blocked_depth - 1)

    def handle_data(self, data: str) -> None:
        if self._script_type and "ld+json" in self._script_type:
            self._script_buf.append(data)
            return
        if self._blocked_depth:
            return
        text = _norm_space(data)
        if not text:
            return
        if self._p_depth:
            self._current_p.append(text)
        if self._article_depth:
            self.article_parts.append(text)
        if self._main_depth:
            self.main_parts.append(text)


@dataclass
class CrawlResult:
    ok: bool
    final_url: str
    canonical_url: str
    title: str
    text: str
    description: str
    published_at: str
    site_name: str
    language: str
    content_type: str
    status: int
    blocked_reason: str
    paywall_hint: bool
    extraction_method: str
    bytes_read: int


_ROBOTS_CACHE: dict[str, urllib.robotparser.RobotFileParser | bool] = {}
_ROBOTS_LOCK = threading.Lock()


def _origin(url: str) -> str:
    p = urllib.parse.urlsplit(url)
    return urllib.parse.urlunsplit((p.scheme, p.netloc, "", "", ""))


def allowed_by_robots(url: str, user_agent: str, timeout: float) -> bool:
    origin = _origin(url)
    with _ROBOTS_LOCK:
        cached = _ROBOTS_CACHE.get(origin)
    if cached is not None:
        return True if cached is True else bool(cached.can_fetch(user_agent, url))
    robots_url = origin.rstrip("/") + "/robots.txt"
    parser = urllib.robotparser.RobotFileParser(robots_url)
    try:
        req = urllib.request.Request(robots_url, headers={"User-Agent": user_agent, "Accept": "text/plain,*/*;q=0.1"})
        with urllib.request.urlopen(req, timeout=min(timeout, 8)) as response:
            raw = response.read(512 * 1024).decode("utf-8", "replace")
        parser.parse(raw.splitlines())
        cached_value: urllib.robotparser.RobotFileParser | bool = parser
    except Exception:
        cached_value = True
    with _ROBOTS_LOCK:
        _ROBOTS_CACHE[origin] = cached_value
    return True if cached_value is True else bool(cached_value.can_fetch(user_agent, url))


def extract_article_html(raw_html: str, base_url: str = "", max_chars: int = DEFAULT_MAX_TEXT_CHARS) -> CrawlResult:
    parser = _ArticleHTMLParser()
    parser.feed(raw_html)

    json_body = ""
    json_title = ""
    json_desc = ""
    json_date = ""
    json_canonical = ""
    json_site = ""
    for chunk in parser.json_ld:
        try:
            payload = json.loads(chunk)
        except Exception:
            continue
        for obj in _walk_json(payload):
            typ = obj.get("@type")
            types = {str(x).lower() for x in typ} if isinstance(typ, list) else {str(typ).lower()}
            if not ({"article", "newsarticle", "reportagenewsarticle", "analysisnewsarticle"} & types):
                continue
            body = _norm_space(str(obj.get("articleBody") or ""))
            if len(body) > len(json_body):
                json_body = body
            json_title = json_title or _norm_space(str(obj.get("headline") or obj.get("name") or ""))
            json_desc = json_desc or _norm_space(str(obj.get("description") or ""))
            json_date = json_date or _norm_space(str(obj.get("datePublished") or ""))
            json_canonical = json_canonical or _norm_space(str(obj.get("url") or ""))
            publisher = obj.get("publisher")
            if isinstance(publisher, dict):
                json_site = json_site or _norm_space(str(publisher.get("name") or ""))

    candidates = [
        ("json-ld", json_body),
        ("article", _norm_space(" ".join(parser.article_parts))),
        ("main", _norm_space(" ".join(parser.main_parts))),
        ("paragraphs", _norm_space(" ".join(parser.paragraphs))),
    ]
    method, text = max(candidates, key=lambda item: len(item[1]))
    if len(text) < 120:
        text = ""
        method = "none"
    text = text[:max(500, max_chars)]

    canonical = parser.canonical or json_canonical or base_url
    canonical = urllib.parse.urljoin(base_url, canonical) if canonical else base_url
    return CrawlResult(
        ok=bool(text),
        final_url=base_url,
        canonical_url=canonical,
        title=(parser.title or json_title)[:1000],
        text=text,
        description=(parser.description or json_desc)[:2000],
        published_at=(parser.published or json_date)[:100],
        site_name=(parser.site_name or json_site)[:300],
        language=parser.language[:40],
        content_type="text/html",
        status=200,
        blocked_reason="",
        paywall_hint=parser.paywall_hint,
        extraction_method=method,
        bytes_read=len(raw_html.encode("utf-8", "ignore")),
    )


def crawl_article(url: str, user_agent: str, timeout: float, max_chars: int = DEFAULT_MAX_TEXT_CHARS,
                  max_bytes: int = DEFAULT_MAX_HTML_BYTES, respect_robots: bool = True) -> CrawlResult:
    from ssrf import assert_public_http_url, open_public_url

    try:
        assert_public_http_url(url)
    except ValueError as exc:
        return CrawlResult(False, url, url, "", "", "", "", "", "", "", 0, str(exc), False, "none", 0)

    if respect_robots and not allowed_by_robots(url, user_agent, timeout):
        return CrawlResult(False, url, url, "", "", "", "", "", "", "", 0, "robots.txt denied crawl", False, "none", 0)

    try:
        with open_public_url(
            url,
            headers={
                "User-Agent": user_agent,
                "Accept": "text/html,application/xhtml+xml;q=0.9,*/*;q=0.2",
                "Accept-Language": "*",
            },
            timeout=timeout,
        ) as response:
            final_url = response.geturl()
            status = int(getattr(response, "status", 200) or 200)
            content_type = (response.headers.get_content_type() or "").lower()
            robots_header = (response.headers.get("X-Robots-Tag") or "").lower()
            if respect_robots and _origin(final_url) != _origin(url) and not allowed_by_robots(final_url, user_agent, timeout):
                return CrawlResult(False, final_url, final_url, "", "", "", "", "", "", content_type, status,
                                   "redirect target robots.txt denied indexing", False, "none", 0)
            if "noindex" in robots_header or "noarchive" in robots_header:
                return CrawlResult(False, final_url, final_url, "", "", "", "", "", "", content_type, status,
                                   "X-Robots-Tag blocks indexing", False, "none", 0)
            if content_type not in {"text/html", "application/xhtml+xml", "text/plain"}:
                return CrawlResult(False, final_url, final_url, "", "", "", "", "", "", content_type, status,
                                   f"unsupported content type: {content_type}", False, "none", 0)
            data = response.read(max_bytes + 1)
            if len(data) > max_bytes:
                return CrawlResult(False, final_url, final_url, "", "", "", "", "", "", content_type, status,
                                   "article response too large", False, "none", len(data))
            charset = response.headers.get_content_charset() or "utf-8"
        text = data.decode(charset, "replace")
        result = extract_article_html(text, final_url, max_chars=max_chars)
        result.final_url = final_url
        result.status = status
        result.content_type = content_type
        result.bytes_read = len(data)
        if result.paywall_hint and not result.text:
            result.blocked_reason = "paywall/limited-access page"
        return result
    except Exception as exc:
        return CrawlResult(False, url, url, "", "", "", "", "", "", "", 0, f"{type(exc).__name__}: {exc}"[:500], False, "none", 0)
