"""Thin capability facades for web.search / web.fetch over WebResearchProvider.

GI7: routes through existing research web providers — never invents results.
"""

from __future__ import annotations

from typing import Any

from .web import WebResearchProvider, web_unavailable_reason

_BOUND_PROVIDER: WebResearchProvider | None = None
_ALLOW_OUTBOUND: bool = False
_ALLOW_WEB: bool = True


def bind_web_provider(
    provider: WebResearchProvider | None,
    *,
    allow_outbound: bool = False,
    allow_web: bool = True,
) -> None:
    global _BOUND_PROVIDER, _ALLOW_OUTBOUND, _ALLOW_WEB
    _BOUND_PROVIDER = provider
    _ALLOW_OUTBOUND = bool(allow_outbound)
    _ALLOW_WEB = bool(allow_web)


def get_bound_web_provider() -> WebResearchProvider | None:
    return _BOUND_PROVIDER


def execute_web_search(query: str, *, limit: int = 5) -> dict[str, Any]:
    """Search via bound provider. Honest WEB_SEARCH_UNAVAILABLE when not configured."""
    q = (query or "").strip()
    if not q:
        return {
            "status": "REJECTED",
            "error_code": "VALIDATION_ERROR",
            "error": "query is required",
            "results": [],
            "truth": {"fabricated": False},
        }
    provider = _BOUND_PROVIDER
    if provider is None:
        return {
            "status": "UNAVAILABLE",
            "error_code": "WEB_SEARCH_UNAVAILABLE",
            "error": "Web research provider is not bound",
            "results": [],
            "truth": {"fabricated": False, "not_configured": True},
        }
    reason = web_unavailable_reason(
        allow_web=_ALLOW_WEB,
        allow_outbound=_ALLOW_OUTBOUND,
        provider=provider,
    )
    search_ready = getattr(provider, "search_configured", None)
    search_ok = bool(callable(search_ready) and search_ready())
    if not search_ok:
        detail = reason or "web_search_endpoint_unconfigured"
        code = (
            "NOT_CONFIGURED"
            if "unconfigured" in detail or "not configured" in detail.lower()
            else "WEB_SEARCH_UNAVAILABLE"
        )
        # Prefer explicit WEB_SEARCH_UNAVAILABLE for operator-facing honesty.
        if code == "NOT_CONFIGURED":
            code = "WEB_SEARCH_UNAVAILABLE"
        return {
            "status": "UNAVAILABLE",
            "error_code": code,
            "error": f"Web search unavailable: {detail}",
            "reason": detail,
            "results": [],
            "truth": {
                "fabricated": False,
                "not_configured": True,
                "direct_fetch_may_still_work": bool(
                    _ALLOW_OUTBOUND and provider.configured()
                ),
            },
        }
    try:
        results = provider.search(q, limit=max(1, min(int(limit), 20)))
    except Exception as exc:  # noqa: BLE001
        msg = str(exc)
        code = "WEB_SEARCH_UNAVAILABLE"
        lower = msg.lower()
        if "not configured" in lower or "unconfigured" in lower:
            code = "WEB_SEARCH_UNAVAILABLE"
        elif "outbound" in lower or "disabled" in lower:
            code = "WEB_SEARCH_UNAVAILABLE"
        return {
            "status": "UNAVAILABLE",
            "error_code": code,
            "error": msg,
            "results": [],
            "truth": {"fabricated": False},
        }
    return {
        "status": "OK",
        "query": q,
        "count": len(results),
        "results": [
            r.public_dict() if hasattr(r, "public_dict") else r for r in results
        ],
        "provider": getattr(provider, "name", "unknown"),
        "truth": {"fabricated": False, "from_web_research_provider": True},
    }


def execute_web_fetch(
    url: str,
    *,
    timeout_seconds: float = 20.0,
    max_bytes: int = 2_000_000,
) -> dict[str, Any]:
    """Fetch a URL via bound provider. May work when search is unconfigured."""
    cleaned = (url or "").strip()
    if not cleaned:
        return {
            "status": "REJECTED",
            "error_code": "VALIDATION_ERROR",
            "error": "url is required",
            "truth": {"fabricated": False},
        }
    provider = _BOUND_PROVIDER
    if provider is None:
        return {
            "status": "UNAVAILABLE",
            "error_code": "WEB_UNAVAILABLE",
            "error": "Web research provider is not bound",
            "truth": {"fabricated": False, "not_configured": True},
        }
    if not _ALLOW_OUTBOUND:
        return {
            "status": "UNAVAILABLE",
            "error_code": "WEB_UNAVAILABLE",
            "error": "Outbound network disabled (LEVIATHAN_NETWORK_ALLOW_OUTBOUND)",
            "reason": "outbound_network_disabled",
            "truth": {"fabricated": False},
        }
    if not provider.configured():
        return {
            "status": "UNAVAILABLE",
            "error_code": "NOT_CONFIGURED",
            "error": "Web provider is not configured for outbound fetch",
            "truth": {"fabricated": False, "not_configured": True},
        }
    try:
        page = provider.fetch_page(
            cleaned,
            timeout_seconds=float(timeout_seconds),
            max_bytes=int(max_bytes),
        )
    except Exception as exc:  # noqa: BLE001
        return {
            "status": "FAILED",
            "error_code": "SOURCE_FETCH_FAILED",
            "error": str(exc),
            "url": cleaned,
            "truth": {"fabricated": False},
        }
    payload = page.public_dict() if hasattr(page, "public_dict") else dict(page)
    return {
        "status": "OK",
        "page": payload,
        "provider": getattr(provider, "name", "unknown"),
        "truth": {
            "fabricated": False,
            "from_web_research_provider": True,
            "search_not_required": True,
        },
    }
