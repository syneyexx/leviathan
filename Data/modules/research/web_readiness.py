"""Canonical web research readiness model — no secrets, operator-honest."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from .web import WebResearchProvider, web_unavailable_reason


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


# In-process last probe (not secrets; diagnostic only).
_LAST_PROBE: dict[str, Any] = {
    "last_probe_at": None,
    "last_probe_status": None,
    "last_error_code": None,
    "last_error_message": None,
}


def record_probe(
    *,
    status: str,
    error_code: str | None = None,
    error_message: str | None = None,
) -> None:
    _LAST_PROBE["last_probe_at"] = utc_now()
    _LAST_PROBE["last_probe_status"] = status
    _LAST_PROBE["last_error_code"] = error_code
    _LAST_PROBE["last_error_message"] = (error_message or "")[:500] or None


@dataclass
class WebResearchReadiness:
    outbound_network: bool
    search_available: bool
    direct_fetch_available: bool
    provider_name: str
    provider_type: str
    endpoint_configured: bool
    api_key_configured: bool
    fallback_enabled: bool
    fallback_status: str
    robots_policy: str
    worker_provider_ready: bool
    search_mode: str
    operator_summary: str
    last_probe_at: str | None = None
    last_probe_status: str | None = None
    last_error_code: str | None = None
    last_error_message: str | None = None
    reason_codes: list[str] = field(default_factory=list)

    def public_dict(self) -> dict[str, Any]:
        return {
            "outbound_network": self.outbound_network,
            "search_available": self.search_available,
            "direct_fetch_available": self.direct_fetch_available,
            "provider_name": self.provider_name,
            "provider_type": self.provider_type,
            "endpoint_configured": self.endpoint_configured,
            "api_key_configured": self.api_key_configured,
            "fallback_enabled": self.fallback_enabled,
            "fallback_status": self.fallback_status,
            "robots_policy": self.robots_policy,
            "worker_provider_ready": self.worker_provider_ready,
            "search_mode": self.search_mode,
            "operator_summary": self.operator_summary,
            "last_probe_at": self.last_probe_at,
            "last_probe_status": self.last_probe_status,
            "last_error_code": self.last_error_code,
            "last_error_message": self.last_error_message,
            "reason_codes": list(self.reason_codes),
            "truth": {
                "secrets_never_returned": True,
                "api_key_configured_is_boolean_only": True,
                "search_hit_is_not_evidence": True,
            },
        }


def build_web_readiness(
    *,
    allow_outbound: bool,
    provider: WebResearchProvider,
    search_endpoint: str | None = None,
    api_key_configured: bool = False,
    search_mode: str = "auto",
    robots_policy: str = "respect_when_requested",
    worker_provider_ready: bool | None = None,
) -> WebResearchReadiness:
    mode = (search_mode or "auto").strip().lower() or "auto"
    endpoint_configured = bool((search_endpoint or "").strip())
    search_ready = bool(getattr(provider, "search_configured", lambda: False)())
    fetch_ready = bool(allow_outbound and provider.configured())
    fallback_enabled = mode in {"auto", "fallback_only"} and allow_outbound
    provider_name = str(getattr(provider, "name", "unknown") or "unknown")
    provider_type = str(
        getattr(provider, "active_provider_type", None)
        or getattr(provider, "search_provider", None)
        or provider_name
    )

    reasons: list[str] = []
    if not allow_outbound:
        reasons.append("outbound_network_disabled")
    if mode == "off":
        reasons.append("web_search_mode_off")
        search_ready = False
        fallback_enabled = False
    if mode == "configured_only" and not endpoint_configured:
        reasons.append("web_search_endpoint_unconfigured")
        search_ready = False

    # Fallback status label (honest).
    if not allow_outbound:
        fallback_status = "disabled_outbound"
    elif mode == "off":
        fallback_status = "disabled_mode_off"
    elif mode == "configured_only":
        fallback_status = "disabled_configured_only"
    elif endpoint_configured and mode == "auto":
        fallback_status = "standby_after_configured"
    elif fallback_enabled:
        fallback_status = "BEST_EFFORT_PUBLIC_SEARCH"
    else:
        fallback_status = "unavailable"

    if search_ready:
        summary = "WEB SEARCH READY"
    elif fetch_ready:
        summary = "FETCH ONLY — search unavailable; direct URL fetch available"
        if "web_search_endpoint_unconfigured" not in reasons and not endpoint_configured:
            reasons.append("web_search_endpoint_unconfigured")
    else:
        summary = "WEB SEARCH UNAVAILABLE"
        detail = web_unavailable_reason(
            allow_web=True, allow_outbound=allow_outbound, provider=provider
        )
        if detail and detail not in reasons:
            reasons.append(detail)

    reason_suffix = f" — reason: {reasons[0]}" if reasons and not search_ready else ""
    if not search_ready and reasons:
        if fetch_ready:
            summary = f"FETCH ONLY — search unavailable; reason: {reasons[0]}"
        else:
            summary = f"WEB SEARCH UNAVAILABLE — reason: {reasons[0]}"

    return WebResearchReadiness(
        outbound_network=bool(allow_outbound),
        search_available=bool(search_ready),
        direct_fetch_available=bool(fetch_ready),
        provider_name=provider_name,
        provider_type=provider_type,
        endpoint_configured=endpoint_configured,
        api_key_configured=bool(api_key_configured),
        fallback_enabled=bool(fallback_enabled),
        fallback_status=fallback_status,
        robots_policy=robots_policy,
        worker_provider_ready=(
            bool(worker_provider_ready)
            if worker_provider_ready is not None
            else bool(allow_outbound and provider.configured())
        ),
        search_mode=mode,
        operator_summary=summary + (reason_suffix if reason_suffix not in summary else ""),
        last_probe_at=_LAST_PROBE.get("last_probe_at"),
        last_probe_status=_LAST_PROBE.get("last_probe_status"),
        last_error_code=_LAST_PROBE.get("last_error_code"),
        last_error_message=_LAST_PROBE.get("last_error_message"),
        reason_codes=reasons,
    )


def probe_web_research(
    provider: WebResearchProvider,
    *,
    allow_outbound: bool,
    query: str = "SQLite WAL mode",
    limit: int = 3,
) -> dict[str, Any]:
    """Search → pick one safe result → fetch. Does not persist research artifacts."""
    out: dict[str, Any] = {
        "status": "FAILED",
        "query": query,
        "search": None,
        "fetch": None,
        "provider": getattr(provider, "name", "unknown"),
        "truth": {"fabricated": False, "persists_artifacts": False},
    }
    if not allow_outbound:
        out["status"] = "UNAVAILABLE"
        out["error_code"] = "OUTBOUND_DISABLED"
        out["error"] = "Outbound network disabled"
        record_probe(status="UNAVAILABLE", error_code="OUTBOUND_DISABLED", error_message=out["error"])
        return out
    search_ready = getattr(provider, "search_configured", lambda: False)()
    if not search_ready:
        out["status"] = "UNAVAILABLE"
        out["error_code"] = "WEB_SEARCH_UNAVAILABLE"
        out["error"] = "No search provider available"
        record_probe(
            status="UNAVAILABLE",
            error_code="WEB_SEARCH_UNAVAILABLE",
            error_message=out["error"],
        )
        return out
    try:
        results = provider.search(query, limit=max(1, min(int(limit), 5)))
    except Exception as exc:  # noqa: BLE001 — surface to operator
        out["status"] = "FAILED"
        out["error_code"] = "SEARCH_FAILED"
        out["error"] = str(exc)[:500]
        record_probe(status="FAILED", error_code="SEARCH_FAILED", error_message=out["error"])
        return out
    out["search"] = {
        "count": len(results),
        "results": [r.public_dict() for r in results[:5]],
    }
    if not results:
        out["status"] = "DEGRADED"
        out["error_code"] = "NO_RESULTS"
        out["error"] = "Search returned zero results"
        record_probe(status="DEGRADED", error_code="NO_RESULTS", error_message=out["error"])
        return out
    target = results[0]
    try:
        page = provider.fetch_page(target.url, respect_robots_txt=True)
    except Exception as exc:  # noqa: BLE001
        out["status"] = "DEGRADED"
        out["error_code"] = "FETCH_FAILED"
        out["error"] = str(exc)[:500]
        out["fetch"] = {"url": target.url, "ok": False}
        record_probe(status="DEGRADED", error_code="FETCH_FAILED", error_message=out["error"])
        return out
    out["fetch"] = {
        "ok": True,
        "url": page.url,
        "canonical_url": page.canonical_url,
        "title": page.title,
        "status_code": page.status_code,
        "content_hash": page.content_hash,
        "text_chars": len(page.text or ""),
        "fetched_at": page.fetched_at,
    }
    if page.status_code >= 400 or not (page.text or "").strip():
        out["status"] = "DEGRADED"
        out["error_code"] = "FETCH_UNREADABLE"
        out["error"] = f"Fetched page unreadable (status={page.status_code})"
        record_probe(
            status="DEGRADED",
            error_code="FETCH_UNREADABLE",
            error_message=out["error"],
        )
        return out
    out["status"] = "OK"
    record_probe(status="OK")
    return out
