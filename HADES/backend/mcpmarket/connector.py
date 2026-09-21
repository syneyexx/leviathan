"""MCPMarketConnector: catalog discovery only. Never executes tools."""

from __future__ import annotations

import time
from typing import Any, Callable
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from .cache import DiscoveryCache
from .handoff import prepare_connection
from .normalize import listing_to_capabilities, unknown_metadata_record
from .official import (
    BASE_URL,
    DEFAULT_TIMEOUT_SECONDS,
    USER_AGENT,
    official_surface,
    server_url,
    skill_url,
)
from .parse import parse_listing_page, parse_skill_page, slugify
from .proposals import propose_missing
from .trust import inspect_listing

Fetcher = Callable[[str], tuple[int, str]]


def _default_fetch(url: str, *, timeout: float = DEFAULT_TIMEOUT_SECONDS) -> tuple[int, str]:
    request = Request(url, headers={"User-Agent": USER_AGENT, "Accept": "text/html,application/ld+json"})
    try:
        with urlopen(request, timeout=timeout) as response:  # noqa: S310 - operator-triggered discovery of a fixed HTTPS host
            status = int(getattr(response, "status", 200) or 200)
            body = response.read(400_000).decode("utf-8", errors="replace")
            return status, body
    except HTTPError as exc:
        body = ""
        try:
            body = exc.read(20_000).decode("utf-8", errors="replace")
        except Exception:
            body = ""
        return int(exc.code or 0), body
    except (URLError, TimeoutError, OSError):
        return 0, ""


def _status_from_http(code: int) -> str:
    if code == 200:
        return "available"
    if code in {401, 403}:
        return "auth_required"
    if code == 429:
        return "degraded"
    if code in {0, 500, 502, 503, 504}:
        return "unavailable"
    if code == 404:
        return "unknown"
    return "degraded"


class MCPMarketConnector:
    """Discover MCPMarket listings. Execution remains HADES MCP Host."""

    def __init__(self, *, fetch: Fetcher | None = None, cache: DiscoveryCache | None = None) -> None:
        self._fetch = fetch or _default_fetch
        self.cache = cache or DiscoveryCache()
        self._last_status = "unknown"

    def status(self) -> dict[str, Any]:
        return {
            "state": self._last_status,
            "base_url": BASE_URL,
            "required_for_startup": False,
            "executes_tools": False,
            "official": official_surface(),
        }

    def fetch_server(self, slug: str) -> dict[str, Any]:
        url = server_url(slugify(slug))
        code, body = self._fetch(url)
        self._last_status = _status_from_http(code)
        if code != 200 or not body:
            return {
                "status": self._last_status,
                "http_status": code,
                "slug": slugify(slug),
                "listing": None,
                "model_called": False,
            }
        listing = parse_listing_page(body, url=url, kind_hint="mcp_server")
        listing["slug"] = slugify(slug)
        listing["discovered_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        listing.update(unknown_metadata_record(listing))
        return {
            "status": "available",
            "http_status": code,
            "slug": listing["slug"],
            "listing": listing,
            "inspection": inspect_listing(listing),
            "normalized": listing_to_capabilities(listing),
            "model_called": False,
        }

    def fetch_skill(self, slug: str) -> dict[str, Any]:
        url = skill_url(slugify(slug))
        code, body = self._fetch(url)
        self._last_status = _status_from_http(code)
        if code != 200 or not body:
            return {"status": _status_from_http(code), "http_status": code, "listing": None, "model_called": False}
        listing = parse_skill_page(body, url=url)
        listing["slug"] = slugify(slug)
        listing["kind_hint"] = "skill"
        return {
            "status": "available",
            "http_status": code,
            "listing": listing,
            "inspection": inspect_listing(listing),
            "normalized": listing_to_capabilities(listing),
            "model_called": False,
        }

    def search(
        self,
        query: str,
        *,
        mission_id: str = "anon",
        kind: str = "mcp_server",
    ) -> dict[str, Any]:
        requirement = query.strip()
        cache_key = self.cache.key(mission_id=mission_id, requirement=f"{kind}:{requirement}")
        cached = self.cache.get(cache_key)
        if cached:
            cached["duplicate_query_prevented"] = True
            cached["model_called"] = False
            return cached
        slug = slugify(requirement)
        if kind == "skill":
            result = self.fetch_skill(slug)
        else:
            result = self.fetch_server(slug)
        candidates = []
        if result.get("listing"):
            listing = result["listing"]
            candidates.append(
                {
                    "name": listing.get("name"),
                    "slug": listing.get("slug"),
                    "description": listing.get("description"),
                    "why": "exact_slug_or_page_match",
                    "needs_setup": True,
                    "requires_auth": bool((result.get("inspection") or {}).get("credentials", {}).get("requires_auth")),
                    "side_effect_class": (result.get("inspection") or {}).get("side_effect_class"),
                }
            )
        payload = {
            "status": result.get("status") or self._last_status,
            "query": requirement,
            "kind": kind,
            "http_status": result.get("http_status"),
            "candidates": candidates,
            "result": result,
            "proposal": propose_missing(
                requirement=requirement,
                candidates=candidates,
                market_status=str(result.get("status") or self._last_status),
            ),
            "model_called": False,
            "cache": "miss",
            "official_search_api": False,
            "note": "No official MCPMarket search API is documented; lookup uses public /server/{slug} or /tools/skills/{slug} pages.",
        }
        return self.cache.put(cache_key, payload)

    def prepare(self, listing: dict[str, Any], *, operator_approved: bool = False) -> dict[str, Any]:
        return prepare_connection(listing, operator_approved=operator_approved)


_CONNECTOR: MCPMarketConnector | None = None


def get_connector() -> MCPMarketConnector:
    global _CONNECTOR
    if _CONNECTOR is None:
        _CONNECTOR = MCPMarketConnector()
    return _CONNECTOR


def reset_connector() -> None:
    global _CONNECTOR
    _CONNECTOR = None
