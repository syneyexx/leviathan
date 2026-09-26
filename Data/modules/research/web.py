"""Web research provider abstraction — real provider only when configured."""

from __future__ import annotations

import re
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Protocol
from urllib.parse import urljoin, urlparse
from urllib.robotparser import RobotFileParser

import httpx

from .ssrf import assert_safe_url, validate_url_for_fetch


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
                    if resp.status_code == 404:
                        parser = RobotFileParser()
                        parser.parse([])
                    elif resp.status_code >= 400:
                        return {
                            "allowed": False,
                            "reason": f"robots_http_{resp.status_code}",
                            "robots_checked": False,
                            "robots_url": robots_url,
                        }
                    else:
                        parser = RobotFileParser()
                        parser.parse(resp.text.splitlines())
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
            if response.status_code == 429:
                retry = float(response.headers.get("retry-after") or 1.0)
                self.rate_limiter.wait(host, retry_after=retry)
                response = client.get(self.search_endpoint, params=params, headers=headers)
            response.raise_for_status()
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
                if response.status_code == 429:
                    retry = float(response.headers.get("retry-after") or 1.0)
                    self.rate_limiter.wait(urlparse(current).hostname or host, retry_after=retry)
                    response = client.get(current, headers=headers)
                if response.status_code in {301, 302, 303, 307, 308}:
                    location = response.headers.get("location")
                    if not location:
                        raise RuntimeError("Redirect without Location header")
                    current = urljoin(current, location)
                    continue
                break
            else:
                raise RuntimeError("Too many redirects")

            content_type = response.headers.get("content-type", "application/octet-stream")
            raw = response.content[: max(1, max_bytes)]
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
                status_code=int(response.status_code),
                content_hash=sha256_bytes(raw),
                fetched_at=utc_now(),
                metadata={
                    "final_url": current,
                    "bytes": len(raw),
                    "truncated": len(response.content) > max_bytes,
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


def build_web_provider(
    *,
    allow_outbound: bool,
    search_endpoint: str | None = None,
    api_key: str | None = None,
    search_provider: str | None = None,
) -> WebResearchProvider:
    if not allow_outbound and not search_endpoint:
        return UnconfiguredWebProvider()
    return HttpWebProvider(
        allow_outbound=allow_outbound,
        search_endpoint=search_endpoint,
        api_key=api_key,
        search_provider=search_provider,
    )


def web_unavailable_reason(
    *,
    allow_web: bool,
    allow_outbound: bool,
    provider: WebResearchProvider,
) -> str | None:
    if not allow_web:
        return None
    if not allow_outbound:
        return "outbound_network_disabled"
    if not provider.configured():
        return "web_provider_unconfigured"
    search_ready = getattr(provider, "search_configured", None)
    if callable(search_ready) and not search_ready() and provider.name == "http_fetch":
        return "web_search_endpoint_unconfigured"
    return None
