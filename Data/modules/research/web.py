"""Web research provider abstraction — configured providers + bounded public fallback.

Search hits are discovery metadata only. Fetched page content is the source.
Never invents URLs, titles, snippets, or results.
"""

from __future__ import annotations

import html as html_lib
import re
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Protocol
from urllib.parse import parse_qs, unquote, urljoin, urlparse

from urllib.robotparser import RobotFileParser

import httpx

from .ssrf import assert_safe_url, validate_url_for_fetch

# Operator search modes (Settings: research.web_search_mode / LEVIATHAN_WEB_SEARCH_MODE).
WEB_SEARCH_MODES = frozenset({"auto", "configured_only", "fallback_only", "off"})
BEST_EFFORT_PUBLIC_PROVIDER = "best_effort_public_search"
DDG_HTML_ENDPOINT = "https://html.duckduckgo.com/html/"
# Bound keyless fallback traffic.
_FALLBACK_MAX_QUERIES_PER_MINUTE = 6
_FALLBACK_MAX_RESULTS = 8


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


@dataclass(frozen=True)
class WebSearchResult:
    title: str
    url: str
    snippet: str
    provider: str
    retrieved_at: str

    def public_dict(self) -> dict[str, Any]:
        return {
            "title": self.title,
            "url": self.url,
            "snippet": self.snippet,
            "provider": self.provider,
            "retrieved_at": self.retrieved_at,
        }


@dataclass(frozen=True)
class WebPageContent:
    url: str
    canonical_url: str
    title: str
    text: str
    content_type: str
    status_code: int
    content_hash: str
    fetched_at: str
    metadata: dict[str, Any] = field(default_factory=dict)

    def public_dict(self) -> dict[str, Any]:
        return {
            "url": self.url,
            "canonical_url": self.canonical_url,
            "title": self.title,
            "text": self.text,
            "content_type": self.content_type,
            "status_code": self.status_code,
            "content_hash": self.content_hash,
            "fetched_at": self.fetched_at,
            "metadata": dict(self.metadata),
        }


class WebResearchProvider(Protocol):
    name: str

    def configured(self) -> bool: ...

    def search(self, query: str, *, limit: int = 5) -> list[WebSearchResult]: ...

    def fetch_page(
        self,
        url: str,
        *,
        timeout_seconds: float = 20.0,
        max_bytes: int = 2_000_000,
        respect_robots_txt: bool = True,
    ) -> WebPageContent: ...


class UnconfiguredWebProvider:
    """Explicit unavailable state — never invents search results."""

    name = "unconfigured"

    def configured(self) -> bool:
        return False

    def search(self, query: str, *, limit: int = 5) -> list[WebSearchResult]:
        raise RuntimeError("Web research provider is not configured")

    def fetch_page(
        self,
        url: str,
        *,
        timeout_seconds: float = 20.0,
        max_bytes: int = 2_000_000,
        respect_robots_txt: bool = True,
    ) -> WebPageContent:
        raise RuntimeError("Web research provider is not configured")


class HostRateLimiter:
    """Per-host minimum interval + optional Retry-After honor (W10)."""

    def __init__(self, *, min_interval_seconds: float = 0.5) -> None:
        self.min_interval_seconds = max(0.0, float(min_interval_seconds))
        self._lock = threading.Lock()
        self._next_allowed: dict[str, float] = {}

    def wait(self, host: str, *, retry_after: float | None = None) -> float:
        key = (host or "").lower() or "unknown"
        now = time.monotonic()
        with self._lock:
            earliest = self._next_allowed.get(key, 0.0)
            delay = max(0.0, earliest - now)
            if retry_after is not None:
                delay = max(delay, float(retry_after))
            sleep_for = delay
            self._next_allowed[key] = max(now, earliest) + self.min_interval_seconds + (
                float(retry_after or 0.0)
            )
        if sleep_for > 0:
            time.sleep(min(sleep_for, 30.0))
        return sleep_for


_ROBOTS_CACHE: dict[str, tuple[float, RobotFileParser | None]] = {}
_ROBOTS_LOCK = threading.Lock()
_ROBOTS_TTL = 3600.0


def check_robots_allowed(
    url: str,
    *,
    user_agent: str,
    timeout_seconds: float = 5.0,
) -> dict[str, Any]:
    """Fetch/cache robots.txt and decide allow/deny. SSRF-safe."""
    parsed = urlparse(url)
    host = parsed.hostname or ""
    scheme = parsed.scheme or "https"
    if not host:
        return {"allowed": False, "reason": "missing_host", "robots_checked": False}
    robots_url = f"{scheme}://{host}/robots.txt"
    decision = validate_url_for_fetch(robots_url)
    if not decision.allowed:
        return {
            "allowed": False,
            "reason": f"robots_unreachable:{decision.reason}",
            "robots_checked": False,
            "robots_url": robots_url,
        }
    now = time.time()
    with _ROBOTS_LOCK:
        cached = _ROBOTS_CACHE.get(host)
        if cached and (now - cached[0]) < _ROBOTS_TTL:
            parser = cached[1]
        else:
            parser = None
            try:
                with httpx.Client(timeout=timeout_seconds, follow_redirects=False) as client:
                    resp = client.get(robots_url, headers={"User-Agent": user_agent})
                    status = int(getattr(resp, "status_code", 0) or 0)
                    if status == 404:
                        parser = RobotFileParser()
                        parser.parse([])
                    elif status >= 400:
                        return {
                            "allowed": False,
                            "reason": f"robots_http_{status}",
                            "robots_checked": False,
                            "robots_url": robots_url,
                        }
                    else:
                        # Prefer .text; fall back to .content for thin test doubles.
                        text = getattr(resp, "text", None)
                        if text is None:
                            raw = getattr(resp, "content", b"") or b""
                            if isinstance(raw, bytes):
                                text = raw.decode("utf-8", errors="replace")
                            else:
                                text = str(raw)
                        parser = RobotFileParser()
                        parser.parse(str(text).splitlines())
            except Exception as exc:  # noqa: BLE001
                return {
                    "allowed": False,
                    "reason": f"robots_error:{type(exc).__name__}",
                    "robots_checked": False,
                    "robots_url": robots_url,
                }
            _ROBOTS_CACHE[host] = (now, parser)
    if parser is None:
        return {"allowed": False, "reason": "robots_unavailable", "robots_checked": False}
    try:
        allowed = bool(parser.can_fetch(user_agent, url))
    except Exception:  # noqa: BLE001
        allowed = False
    return {
        "allowed": allowed,
        "reason": "allowed" if allowed else "disallow",
        "robots_checked": True,
        "robots_url": robots_url,
    }


def _detect_search_provider(endpoint: str | None, explicit: str | None) -> str:
    """Resolve search adapter: generic | searxng | brave."""
    raw = (explicit or "").strip().lower()
    if raw in {"generic", "searxng", "brave", "json"}:
        return "generic" if raw == "json" else raw
    ep = (endpoint or "").lower()
    if "searx" in ep:
        return "searxng"
    if "brave.com" in ep or "api.search.brave" in ep:
        return "brave"
    return "generic"


class HttpWebProvider:
    """Minimal HTTP fetch provider with SSRF checks.

    Search is intentionally not faked: without a dedicated search API key/endpoint
    this provider only supports direct URL fetch of seed/discovered URLs.

    Optional search adapters (generic JSON, SearxNG, Brave) are selected via
    ``search_provider`` or auto-detected from the endpoint URL. Generic JSON
    (``results`` / ``items``) remains the default path.
    """

    name = "http_fetch"

    def __init__(
        self,
        *,
        allow_outbound: bool,
        search_endpoint: str | None = None,
        api_key: str | None = None,
        user_agent: str = "LEVIATHAN-Research/1.0",
        search_provider: str | None = None,
        min_request_interval_seconds: float = 0.5,
        rate_limiter: HostRateLimiter | None = None,
    ) -> None:
        self.allow_outbound = bool(allow_outbound)
        self.search_endpoint = (search_endpoint or "").strip() or None
        self.api_key = (api_key or "").strip() or None
        self.user_agent = user_agent
        self.search_provider = _detect_search_provider(
            self.search_endpoint, search_provider
        )
        self.rate_limiter = rate_limiter or HostRateLimiter(
            min_interval_seconds=min_request_interval_seconds
        )

    def configured(self) -> bool:
        # Direct URL fetch needs outbound only; search needs an endpoint too.
        return self.allow_outbound

    def search_configured(self) -> bool:
        return bool(self.allow_outbound and self.search_endpoint)

    def search(self, query: str, *, limit: int = 5) -> list[WebSearchResult]:
        if not self.allow_outbound:
            raise RuntimeError("Outbound network disabled (LEVIATHAN_NETWORK_ALLOW_OUTBOUND)")
        if not self.search_endpoint:
            raise RuntimeError(
                "Web search endpoint is not configured; set a real search provider endpoint"
            )
        assert_safe_url(self.search_endpoint)
        host = urlparse(self.search_endpoint).hostname or ""
        self.rate_limiter.wait(host)
        limit = max(1, min(int(limit), 20))
        headers = {"User-Agent": self.user_agent, "Accept": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        kind = self.search_provider
        params: dict[str, Any]
        if kind == "searxng":
            params = {"q": query, "format": "json", "limit": limit}
        elif kind == "brave":
            # Brave Search API uses X-Subscription-Token when keyed.
            if self.api_key:
                headers["X-Subscription-Token"] = self.api_key
                headers.pop("Authorization", None)
            params = {"q": query, "count": limit}
        else:
            params = {"q": query, "limit": limit}
        with httpx.Client(timeout=20.0, follow_redirects=False) as client:
            response = client.get(self.search_endpoint, params=params, headers=headers)
            status = int(getattr(response, "status_code", 0) or 0)
            if status == 429:
                headers_map = getattr(response, "headers", {}) or {}
                retry = float(headers_map.get("retry-after") or 1.0)
                self.rate_limiter.wait(host, retry_after=retry)
                response = client.get(self.search_endpoint, params=params, headers=headers)
            raise_for_status = getattr(response, "raise_for_status", None)
            if callable(raise_for_status):
                raise_for_status()
            elif status and status >= 400:
                raise RuntimeError(f"search_http_{status}")
            payload = response.json()
        items = _extract_search_items(payload, kind=kind)
        now = utc_now()
        out: list[WebSearchResult] = []
        for item in items[:limit]:
            if not isinstance(item, dict):
                continue
            url = str(item.get("url") or item.get("link") or item.get("href") or "").strip()
            if not url:
                continue
            decision = validate_url_for_fetch(url)
            if not decision.allowed:
                continue
            out.append(
                WebSearchResult(
                    title=str(item.get("title") or item.get("name") or url),
                    url=url,
                    snippet=str(
                        item.get("snippet")
                        or item.get("description")
                        or item.get("content")
                        or ""
                    ),
                    provider=f"{self.name}:{kind}",
                    retrieved_at=now,
                )
            )
        return out

    def fetch_page(
        self,
        url: str,
        *,
        timeout_seconds: float = 20.0,
        max_bytes: int = 2_000_000,
        respect_robots_txt: bool = True,
    ) -> WebPageContent:
        if not self.allow_outbound:
            raise RuntimeError("Outbound network disabled (LEVIATHAN_NETWORK_ALLOW_OUTBOUND)")
        assert_safe_url(url)
        robots_meta: dict[str, Any] = {"respect_robots_txt": respect_robots_txt}
        if respect_robots_txt:
            robots_meta = check_robots_allowed(
                url, user_agent=self.user_agent, timeout_seconds=min(5.0, timeout_seconds)
            )
            robots_meta["respect_robots_txt"] = True
            if not robots_meta.get("allowed"):
                raise RuntimeError(
                    f"robots_txt_disallow:{robots_meta.get('reason') or 'disallow'}"
                )
        host = urlparse(url).hostname or ""
        wait_s = self.rate_limiter.wait(host)
        headers = {"User-Agent": self.user_agent, "Accept": "text/html,text/plain,*/*"}
        current = url
        with httpx.Client(timeout=timeout_seconds, follow_redirects=False) as client:
            for _ in range(5):
                assert_safe_url(current)
                response = client.get(current, headers=headers)
                status = int(getattr(response, "status_code", 0) or 0)
                headers_map = getattr(response, "headers", {}) or {}
                if status == 429:
                    retry = float(headers_map.get("retry-after") or 1.0)
                    self.rate_limiter.wait(urlparse(current).hostname or host, retry_after=retry)
                    response = client.get(current, headers=headers)
                    status = int(getattr(response, "status_code", 0) or 0)
                    headers_map = getattr(response, "headers", {}) or {}
                if status in {301, 302, 303, 307, 308}:
                    location = headers_map.get("location")
                    if not location:
                        raise RuntimeError("Redirect without Location header")
                    current = urljoin(current, location)
                    continue
                break
            else:
                raise RuntimeError("Too many redirects")

            headers_map = getattr(response, "headers", {}) or {}
            content_type = headers_map.get("content-type", "application/octet-stream")
            raw_full = getattr(response, "content", b"") or b""
            raw = raw_full[: max(1, max_bytes)]
            text = raw.decode("utf-8", errors="replace")
            title = _extract_title(text) or current
            published_at = _extract_published_at(text) if "html" in content_type.lower() else None
            if "html" in content_type.lower():
                body, extractor = _html_to_readable_text(text)
            else:
                body, extractor = text, "plain"
            from Data.modules.common.hashing import sha256_bytes

            return WebPageContent(
                url=url,
                canonical_url=str(response.url) if hasattr(response, "url") else current,
                title=title,
                text=body,
                content_type=content_type.split(";")[0].strip(),
                status_code=int(getattr(response, "status_code", 0) or 0),
                content_hash=sha256_bytes(raw),
                fetched_at=utc_now(),
                metadata={
                    "final_url": current,
                    "bytes": len(raw),
                    "truncated": len(raw_full) > max_bytes,
                    "respect_robots_txt": respect_robots_txt,
                    "domain": urlparse(current).hostname,
                    "robots": robots_meta,
                    "rate_limit_wait_seconds": wait_s,
                    "extractor": extractor,
                    "published_at": published_at,
                },
            )


def _extract_title(html: str) -> str | None:
    match = re.search(r"<title[^>]*>(.*?)</title>", html, flags=re.I | re.S)
    if not match:
        return None
    return re.sub(r"\s+", " ", match.group(1)).strip()[:300] or None


def _extract_published_at(html: str) -> str | None:
    patterns = [
        r'<meta[^>]+property=["\']article:published_time["\'][^>]+content=["\']([^"\']+)["\']',
        r'<meta[^>]+content=["\']([^"\']+)["\'][^>]+property=["\']article:published_time["\']',
        r'<meta[^>]+name=["\'](?:pubdate|publish(?:ed)?(?:-?date)?|date)["\'][^>]+content=["\']([^"\']+)["\']',
        r'<time[^>]+datetime=["\']([^"\']+)["\']',
    ]
    for pat in patterns:
        match = re.search(pat, html, flags=re.I | re.S)
        if match:
            return match.group(1).strip()[:64]
    return None


def _html_to_text(html: str) -> str:
    text = re.sub(r"(?is)<script[^>]*>.*?</script>", " ", html)
    text = re.sub(r"(?is)<style[^>]*>.*?</style>", " ", text)
    text = re.sub(r"(?is)<noscript[^>]*>.*?</noscript>", " ", text)
    text = re.sub(r"(?s)<[^>]+>", " ", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def _html_to_readable_text(html: str) -> tuple[str, str]:
    """Prefer main/article content; fall back to full tag-strip (W10)."""
    for tag, name in (("article", "article"), ("main", "main")):
        match = re.search(rf"(?is)<{tag}[^>]*>(.*?)</{tag}>", html)
        if match:
            body = _html_to_text(match.group(1))
            if len(body) >= 120:
                return body, f"readability:{name}"
    paras = re.findall(r"(?is)<p[^>]*>(.*?)</p>", html)
    if paras:
        joined = _html_to_text(" ".join(paras[:80]))
        if len(joined) >= 120:
            return joined, "readability:paragraphs"
    return _html_to_text(html), "html_strip"


def _extract_search_items(payload: Any, *, kind: str) -> list[Any]:
    """Normalize provider JSON into a list of result dicts. Never invents hits."""
    if not isinstance(payload, dict):
        return []
    if kind == "brave":
        web = payload.get("web") if isinstance(payload.get("web"), dict) else {}
        items = web.get("results") if isinstance(web, dict) else None
        if isinstance(items, list):
            return items
    # SearxNG + generic: results / items
    items = payload.get("results") or payload.get("items") or []
    return items if isinstance(items, list) else []


def _unwrap_ddg_url(raw: str) -> str:
    """Unwrap DuckDuckGo redirect URLs to the destination when present."""
    url = (raw or "").strip()
    if not url:
        return ""
    if url.startswith("//"):
        url = "https:" + url
    parsed = urlparse(url)
    host = (parsed.hostname or "").lower()
    if "duckduckgo.com" in host and ("/l/" in parsed.path or "uddg=" in (parsed.query or "")):
        qs = parse_qs(parsed.query)
        uddg = (qs.get("uddg") or [None])[0]
        if uddg:
            return unquote(uddg)
    return url


def _parse_ddg_html_results(body: str, *, limit: int) -> list[dict[str, str]]:
    """Parse DuckDuckGo HTML/Lite result blocks. Never invents hits."""
    out: list[dict[str, str]] = []
    # Primary: result__a anchors (html.duckduckgo.com).
    for match in re.finditer(
        r'class="result__a"[^>]*href="([^"]+)"[^>]*>(.*?)</a>',
        body,
        flags=re.I | re.S,
    ):
        href = html_lib.unescape(match.group(1).strip())
        title = re.sub(r"<[^>]+>", " ", html_lib.unescape(match.group(2)))
        title = re.sub(r"\s+", " ", title).strip()
        url = _unwrap_ddg_url(href)
        if not url.startswith(("http://", "https://")):
            continue
        # Skip DDG internal chrome.
        host = (urlparse(url).hostname or "").lower()
        if "duckduckgo.com" in host:
            continue
        # Snippet: nearest result__snippet after this match.
        snippet = ""
        tail = body[match.end() : match.end() + 1200]
        sn = re.search(
            r'class="result__snippet"[^>]*>(.*?)</(?:a|td|div|span)>',
            tail,
            flags=re.I | re.S,
        )
        if sn:
            snippet = re.sub(r"<[^>]+>", " ", html_lib.unescape(sn.group(1)))
            snippet = re.sub(r"\s+", " ", snippet).strip()[:500]
        out.append({"title": title or url, "url": url, "snippet": snippet})
        if len(out) >= limit:
            break
    if out:
        return out
    # Lite fallback: result-link
    for match in re.finditer(
        r'class="result-link"[^>]*href="([^"]+)"[^>]*>(.*?)</a>',
        body,
        flags=re.I | re.S,
    ):
        href = html_lib.unescape(match.group(1).strip())
        title = re.sub(r"<[^>]+>", " ", html_lib.unescape(match.group(2)))
        title = re.sub(r"\s+", " ", title).strip()
        url = _unwrap_ddg_url(href)
        if not url.startswith(("http://", "https://")):
            continue
        host = (urlparse(url).hostname or "").lower()
        if "duckduckgo.com" in host:
            continue
        out.append({"title": title or url, "url": url, "snippet": ""})
        if len(out) >= limit:
            break
    return out


class DuckDuckGoHtmlSearchProvider:
    """Bounded zero-key public discovery via DuckDuckGo HTML (BEST_EFFORT_PUBLIC_SEARCH).

    Not an enterprise search product. Rate-limited, SSRF-validated, no invented hits.
    Fetch reuses HttpWebProvider page-fetch semantics.
    """

    name = BEST_EFFORT_PUBLIC_PROVIDER
    search_provider = BEST_EFFORT_PUBLIC_PROVIDER
    active_provider_type = BEST_EFFORT_PUBLIC_PROVIDER

    def __init__(
        self,
        *,
        allow_outbound: bool,
        user_agent: str = "LEVIATHAN-Research/1.0",
        rate_limiter: HostRateLimiter | None = None,
        fetch_delegate: HttpWebProvider | None = None,
    ) -> None:
        self.allow_outbound = bool(allow_outbound)
        self.user_agent = user_agent
        self.rate_limiter = rate_limiter or HostRateLimiter(min_interval_seconds=1.0)
        self._fetch = fetch_delegate or HttpWebProvider(
            allow_outbound=allow_outbound,
            user_agent=user_agent,
            rate_limiter=self.rate_limiter,
        )
        self._query_times: list[float] = []
        self._query_lock = threading.Lock()

    def configured(self) -> bool:
        return self.allow_outbound

    def search_configured(self) -> bool:
        return self.allow_outbound

    def _enforce_query_budget(self) -> None:
        now = time.monotonic()
        with self._query_lock:
            self._query_times = [t for t in self._query_times if now - t < 60.0]
            if len(self._query_times) >= _FALLBACK_MAX_QUERIES_PER_MINUTE:
                raise RuntimeError(
                    "best_effort_public_search_rate_limited:"
                    f"max_{_FALLBACK_MAX_QUERIES_PER_MINUTE}_queries_per_minute"
                )
            self._query_times.append(now)

    def search(self, query: str, *, limit: int = 5) -> list[WebSearchResult]:
        if not self.allow_outbound:
            raise RuntimeError("Outbound network disabled (LEVIATHAN_NETWORK_ALLOW_OUTBOUND)")
        q = (query or "").strip()
        if not q:
            return []
        self._enforce_query_budget()
        limit = max(1, min(int(limit), _FALLBACK_MAX_RESULTS))
        headers = {
            "User-Agent": self.user_agent,
            "Accept": "text/html,application/xhtml+xml;q=0.9,*/*;q=0.8",
        }
        # Prefer GET on html.duckduckgo.com — POST often returns anomaly/challenge pages.
        endpoints = (
            (DDG_HTML_ENDPOINT, "get"),
            ("https://lite.duckduckgo.com/lite/", "get"),
        )
        body = ""
        last_status = 0
        last_error = ""
        with httpx.Client(timeout=20.0, follow_redirects=True) as client:
            for endpoint, method in endpoints:
                assert_safe_url(endpoint)
                host = urlparse(endpoint).hostname or "duckduckgo.com"
                self.rate_limiter.wait(host)
                try:
                    if method == "get":
                        response = client.get(endpoint, params={"q": q}, headers=headers)
                    else:
                        response = client.post(
                            endpoint,
                            data={"q": q},
                            headers={
                                **headers,
                                "Content-Type": "application/x-www-form-urlencoded",
                            },
                        )
                except Exception as exc:  # noqa: BLE001
                    last_error = str(exc)
                    continue
                last_status = int(getattr(response, "status_code", 0) or 0)
                if last_status == 429:
                    headers_map = getattr(response, "headers", {}) or {}
                    retry = float(headers_map.get("retry-after") or 2.0)
                    self.rate_limiter.wait(host, retry_after=retry)
                    response = client.get(endpoint, params={"q": q}, headers=headers)
                    last_status = int(getattr(response, "status_code", 0) or 0)
                if last_status >= 400:
                    last_error = f"best_effort_public_search_http_{last_status}"
                    continue
                text = getattr(response, "text", None)
                if text is None:
                    raw = getattr(response, "content", b"") or b""
                    text = raw.decode("utf-8", errors="replace")
                lower = text.lower()
                if "anomaly" in lower and "result__a" not in lower and "result-link" not in lower:
                    last_error = "best_effort_public_search_challenge"
                    continue
                body = text
                final_url = str(getattr(response, "url", endpoint) or endpoint)
                host_final = (urlparse(final_url).hostname or "").lower()
                if "duckduckgo.com" not in host_final:
                    decision = validate_url_for_fetch(final_url)
                    if not decision.allowed:
                        last_error = "best_effort_public_search_redirect_blocked"
                        body = ""
                        continue
                break
        if not body:
            raise RuntimeError(
                last_error or f"best_effort_public_search_http_{last_status or 'unknown'}"
            )
        items = _parse_ddg_html_results(body, limit=limit)
        now = utc_now()
        out: list[WebSearchResult] = []
        for item in items:
            url = item["url"]
            decision = validate_url_for_fetch(url)
            if not decision.allowed:
                continue
            out.append(
                WebSearchResult(
                    title=item["title"],
                    url=url,
                    snippet=item.get("snippet") or "",
                    provider=BEST_EFFORT_PUBLIC_PROVIDER,
                    retrieved_at=now,
                )
            )
        return out

    def fetch_page(
        self,
        url: str,
        *,
        timeout_seconds: float = 20.0,
        max_bytes: int = 2_000_000,
        respect_robots_txt: bool = True,
    ) -> WebPageContent:
        return self._fetch.fetch_page(
            url,
            timeout_seconds=timeout_seconds,
            max_bytes=max_bytes,
            respect_robots_txt=respect_robots_txt,
        )


def _is_search_availability_error(exc: BaseException) -> bool:
    msg = str(exc).lower()
    needles = (
        "not configured",
        "unavailable",
        "unconfigured",
        "timeout",
        "timed out",
        "429",
        "401",
        "403",
        "502",
        "503",
        "504",
        "rate_limit",
        "rate limited",
        "connection",
        "http_",
        "search_http_",
        "best_effort_public_search_http_",
        "outbound network disabled",
    )
    return any(n in msg for n in needles)


class ChainedWebProvider:
    """Provider selection/failover: configured → Searx/Brave/generic → keyless public.

    Failover only on provider/search availability errors.
    ``configured_only`` never silently falls back.
    """

    name = "web_search_chain"

    def __init__(
        self,
        *,
        allow_outbound: bool,
        search_endpoint: str | None = None,
        api_key: str | None = None,
        search_provider: str | None = None,
        search_mode: str = "auto",
        user_agent: str = "LEVIATHAN-Research/1.0",
    ) -> None:
        self.allow_outbound = bool(allow_outbound)
        self.search_endpoint = (search_endpoint or "").strip() or None
        self.api_key = (api_key or "").strip() or None
        self.search_mode = (search_mode or "auto").strip().lower() or "auto"
        if self.search_mode not in WEB_SEARCH_MODES:
            self.search_mode = "auto"
        self.user_agent = user_agent
        self.rate_limiter = HostRateLimiter(min_interval_seconds=0.5)
        self._configured = (
            HttpWebProvider(
                allow_outbound=allow_outbound,
                search_endpoint=self.search_endpoint,
                api_key=self.api_key,
                search_provider=search_provider,
                rate_limiter=self.rate_limiter,
                user_agent=user_agent,
            )
            if allow_outbound or self.search_endpoint
            else None
        )
        self._fallback = DuckDuckGoHtmlSearchProvider(
            allow_outbound=allow_outbound,
            user_agent=user_agent,
            rate_limiter=self.rate_limiter,
            fetch_delegate=self._configured
            or HttpWebProvider(
                allow_outbound=allow_outbound,
                user_agent=user_agent,
                rate_limiter=self.rate_limiter,
            ),
        )
        self._last_search_provider: str | None = None
        self.active_provider_type = self._describe_active_type()

    def _describe_active_type(self) -> str:
        if self.search_mode == "off":
            return "off"
        if self.search_mode == "fallback_only":
            return BEST_EFFORT_PUBLIC_PROVIDER
        if self.search_endpoint and self._configured is not None:
            return f"configured:{self._configured.search_provider}"
        if self.search_mode in {"auto", "fallback_only"}:
            return BEST_EFFORT_PUBLIC_PROVIDER
        return "none"

    def configured(self) -> bool:
        return bool(self.allow_outbound)

    def search_configured(self) -> bool:
        if not self.allow_outbound or self.search_mode == "off":
            return False
        if self.search_mode == "configured_only":
            return bool(self._configured and self._configured.search_configured())
        if self.search_mode == "fallback_only":
            return self._fallback.search_configured()
        # auto: configured endpoint OR public fallback
        if self._configured and self._configured.search_configured():
            return True
        return self._fallback.search_configured()

    def search(self, query: str, *, limit: int = 5) -> list[WebSearchResult]:
        if not self.allow_outbound:
            raise RuntimeError("Outbound network disabled (LEVIATHAN_NETWORK_ALLOW_OUTBOUND)")
        if self.search_mode == "off":
            raise RuntimeError("Web search mode is off (research.web_search_mode=off)")

        errors: list[str] = []

        def _try(provider: Any, label: str) -> list[WebSearchResult] | None:
            nonlocal errors
            try:
                results = provider.search(query, limit=limit)
                self._last_search_provider = label
                self.active_provider_type = label
                return results
            except Exception as exc:  # noqa: BLE001 — failover decision
                if not _is_search_availability_error(exc):
                    raise
                errors.append(f"{label}:{exc}")
                return None

        if self.search_mode == "fallback_only":
            results = _try(self._fallback, BEST_EFFORT_PUBLIC_PROVIDER)
            if results is not None:
                return results
            raise RuntimeError(
                "WEB_SEARCH_UNAVAILABLE: " + ("; ".join(errors) or "fallback_failed")
            )

        if self.search_mode == "configured_only":
            if not self._configured or not self._configured.search_configured():
                raise RuntimeError(
                    "Web search endpoint is not configured; set a real search provider endpoint"
                )
            results = _try(
                self._configured,
                f"configured:{self._configured.search_provider}",
            )
            if results is not None:
                return results
            raise RuntimeError(
                "WEB_SEARCH_UNAVAILABLE: " + ("; ".join(errors) or "configured_provider_failed")
            )

        # auto
        if self._configured and self._configured.search_configured():
            results = _try(
                self._configured,
                f"configured:{self._configured.search_provider}",
            )
            if results is not None:
                return results
        results = _try(self._fallback, BEST_EFFORT_PUBLIC_PROVIDER)
        if results is not None:
            return results
        raise RuntimeError(
            "WEB_SEARCH_UNAVAILABLE: " + ("; ".join(errors) or "no_search_provider_available")
        )

    def fetch_page(
        self,
        url: str,
        *,
        timeout_seconds: float = 20.0,
        max_bytes: int = 2_000_000,
        respect_robots_txt: bool = True,
    ) -> WebPageContent:
        delegate = self._configured or self._fallback
        return delegate.fetch_page(
            url,
            timeout_seconds=timeout_seconds,
            max_bytes=max_bytes,
            respect_robots_txt=respect_robots_txt,
        )


def normalize_web_search_mode(raw: str | None) -> str:
    mode = (raw or "auto").strip().lower() or "auto"
    return mode if mode in WEB_SEARCH_MODES else "auto"


def build_web_provider(
    *,
    allow_outbound: bool,
    search_endpoint: str | None = None,
    api_key: str | None = None,
    search_provider: str | None = None,
    search_mode: str | None = None,
) -> WebResearchProvider:
    mode = normalize_web_search_mode(search_mode)
    if mode == "off":
        # Fetch-only when outbound; search always unavailable.
        if allow_outbound:
            return HttpWebProvider(
                allow_outbound=True,
                search_endpoint=None,
                api_key=None,
                search_provider=search_provider,
            )
        return UnconfiguredWebProvider()
    if not allow_outbound and not search_endpoint:
        return UnconfiguredWebProvider()
    # Prefer chain so auto mode gets keyless fallback when endpoint unset.
    return ChainedWebProvider(
        allow_outbound=allow_outbound,
        search_endpoint=search_endpoint,
        api_key=api_key,
        search_provider=search_provider,
        search_mode=mode,
    )


def web_unavailable_reason(
    *,
    allow_web: bool,
    allow_outbound: bool,
    provider: WebResearchProvider,
) -> str | None:
    """Return reason when *search discovery* is unavailable.

    Direct URL fetch may still work when this returns
    ``web_search_endpoint_unconfigured`` for legacy http_fetch-only providers.
    Chained providers with fallback enabled return None when search is ready.
    """
    if not allow_web:
        return None
    if not allow_outbound:
        return "outbound_network_disabled"
    if not provider.configured():
        return "web_provider_unconfigured"
    search_ready = getattr(provider, "search_configured", None)
    if callable(search_ready) and search_ready():
        return None
    mode = getattr(provider, "search_mode", None)
    if mode == "off":
        return "web_search_mode_off"
    if mode == "configured_only":
        return "web_search_endpoint_unconfigured"
    # Legacy HttpWebProvider without endpoint / chain without fallback path.
    if provider.name in {"http_fetch", "web_search_chain", "unconfigured"}:
        return "web_search_endpoint_unconfigured"
    return "web_search_unavailable"
