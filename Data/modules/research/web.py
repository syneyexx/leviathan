"""Web research provider abstraction — real provider only when configured."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Protocol
from urllib.parse import urlparse

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
    ) -> None:
        self.allow_outbound = bool(allow_outbound)
        self.search_endpoint = (search_endpoint or "").strip() or None
        self.api_key = (api_key or "").strip() or None
        self.user_agent = user_agent
        self.search_provider = _detect_search_provider(
            self.search_endpoint, search_provider
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
        if respect_robots_txt:
            # Soft check: record intent; full robots parser can be layered later.
            # We refuse crawling when robots cannot be checked for private hosts (already SSRF-blocked).
            pass
        headers = {"User-Agent": self.user_agent, "Accept": "text/html,text/plain,*/*"}
        current = url
        with httpx.Client(timeout=timeout_seconds, follow_redirects=False) as client:
            for _ in range(5):
                assert_safe_url(current)
                response = client.get(current, headers=headers)
                if response.status_code in {301, 302, 303, 307, 308}:
                    location = response.headers.get("location")
                    if not location:
                        raise RuntimeError("Redirect without Location header")
                    # Absolute or relative redirect.
                    from urllib.parse import urljoin

                    current = urljoin(current, location)
                    continue
                break
            else:
                raise RuntimeError("Too many redirects")

            content_type = response.headers.get("content-type", "application/octet-stream")
            raw = response.content[: max(1, max_bytes)]
            text = raw.decode("utf-8", errors="replace")
            title = _extract_title(text) or current
            from Data.modules.common.hashing import sha256_bytes

            return WebPageContent(
                url=url,
                canonical_url=str(response.url) if hasattr(response, "url") else current,
                title=title,
                text=_html_to_text(text) if "html" in content_type.lower() else text,
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
                },
            )


def _extract_title(html: str) -> str | None:
    import re

    match = re.search(r"<title[^>]*>(.*?)</title>", html, flags=re.I | re.S)
    if not match:
        return None
    return re.sub(r"\s+", " ", match.group(1)).strip()[:300] or None


def _html_to_text(html: str) -> str:
    import re

    text = re.sub(r"(?is)<script[^>]*>.*?</script>", " ", html)
    text = re.sub(r"(?is)<style[^>]*>.*?</style>", " ", text)
    text = re.sub(r"(?s)<[^>]+>", " ", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


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
