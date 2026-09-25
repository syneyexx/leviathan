"""Injectable HTTP transport for market providers.

Remote network I/O for historical/quote fetches belongs under provider_io workers.
This module provides a small transport protocol so domain providers stay free of
hard-coded urllib loops while remaining testable with fake transports.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any, Protocol
from urllib.parse import urlparse

from Data.modules.common.retry import RetryPolicy, compute_backoff_seconds
from Data.modules.market_sim.types import MarketSimError


@dataclass(frozen=True)
class HttpResponse:
    status_code: int
    body: bytes
    headers: dict[str, str]
    url: str = ""

    def header(self, name: str) -> str | None:
        target = name.lower()
        for key, value in self.headers.items():
            if key.lower() == target:
                return value
        return None


class HttpTransport(Protocol):
    def request(
        self,
        method: str,
        url: str,
        *,
        headers: dict[str, str] | None = None,
        timeout: float | None = None,
    ) -> HttpResponse: ...


class UrllibTransport:
    """Legacy/local transport — used only when explicitly allowed (tests / offline)."""

    def request(
        self,
        method: str,
        url: str,
        *,
        headers: dict[str, str] | None = None,
        timeout: float | None = None,
    ) -> HttpResponse:
        import urllib.error
        import urllib.request

        req_headers = {
            "User-Agent": "LeviathanMarketSim/1.0 (research; paper-only)",
            **(headers or {}),
        }
        req = urllib.request.Request(url, headers=req_headers, method=method.upper())
        try:
            with urllib.request.urlopen(req, timeout=timeout or 30.0) as resp:  # noqa: S310
                return HttpResponse(
                    status_code=int(getattr(resp, "status", 200) or 200),
                    body=resp.read(),
                    headers={k: v for k, v in dict(resp.headers).items()},
                    url=url,
                )
        except urllib.error.HTTPError as exc:
            body = b""
            try:
                body = exc.read() or b""
            except Exception:  # noqa: BLE001
                body = b""
            return HttpResponse(
                status_code=int(exc.code),
                body=body,
                headers={k: v for k, v in dict(exc.headers or {}).items()},
                url=url,
            )


class HttpxTransport:
    """Worker-side transport backed by ProviderClientPool httpx clients."""

    def __init__(self, client: Any, *, provider: str = "market") -> None:
        self._client = client
        self.provider = provider

    def request(
        self,
        method: str,
        url: str,
        *,
        headers: dict[str, str] | None = None,
        timeout: float | None = None,
    ) -> HttpResponse:
        req_headers = {
            "User-Agent": "LeviathanMarketSim/1.0 (research; paper-only)",
            **(headers or {}),
        }
        kwargs: dict[str, Any] = {"headers": req_headers}
        if timeout is not None:
            kwargs["timeout"] = timeout
        resp = self._client.request(method.upper(), url, **kwargs)
        return HttpResponse(
            status_code=int(resp.status_code),
            body=bytes(resp.content or b""),
            headers={k: v for k, v in dict(resp.headers).items()},
            url=str(resp.url) if getattr(resp, "url", None) else url,
        )


def _parse_retry_after(raw: str | None) -> float | None:
    if not raw:
        return None
    raw = raw.strip()
    try:
        return max(0.0, float(raw))
    except ValueError:
        return None


def request_with_retry(
    transport: HttpTransport,
    method: str,
    url: str,
    *,
    headers: dict[str, str] | None = None,
    timeout: float | None = None,
    retry: RetryPolicy | None = None,
    cancel_check: Any | None = None,
    sleep: Any | None = None,
    host_allowlist: frozenset[str] | None = None,
) -> HttpResponse:
    """GET/HEAD with exponential backoff, Retry-After, and cancellation."""
    policy = retry or RetryPolicy(max_attempts=4, base_seconds=0.5, max_seconds=30.0)
    sleeper = sleep or time.sleep
    allow = host_allowlist or frozenset(
        {
            "data-api.binance.vision",
            "api.binance.com",
            "stream.binance.com",
            "stooq.com",
        }
    )
    host = (urlparse(url).hostname or "").lower()
    if host and host not in allow and not any(host.endswith("." + h) for h in allow):
        raise MarketSimError(
            "NETWORK_BLOCKED",
            f"host not allowlisted for market provider I/O: {host}",
            http_status=403,
        )

    last: HttpResponse | None = None
    last_exc: Exception | None = None
    for attempt in range(max(1, policy.max_attempts)):
        if cancel_check and cancel_check():
            raise MarketSimError("EXECUTION_CANCELLED", "Cancelled during market HTTP", http_status=499)
        try:
            last = transport.request(method, url, headers=headers, timeout=timeout)
        except MarketSimError:
            raise
        except Exception as exc:  # noqa: BLE001
            last_exc = exc
            if attempt + 1 >= policy.max_attempts:
                raise MarketSimError("PROVIDER_ERROR", str(exc), http_status=502) from exc
            sleeper(compute_backoff_seconds(attempt, policy=policy))
            continue

        if last.status_code == 429 or last.status_code >= 500:
            retry_after = _parse_retry_after(last.header("Retry-After"))
            if attempt + 1 >= policy.max_attempts:
                code = "PROVIDER_RATE_LIMITED" if last.status_code == 429 else "PROVIDER_HTTP"
                raise MarketSimError(
                    code,
                    f"HTTP {last.status_code} after retries for {url}",
                    http_status=last.status_code,
                )
            sleeper(compute_backoff_seconds(attempt, policy=policy, retry_after=retry_after))
            continue
        if last.status_code >= 400:
            raise MarketSimError(
                "PROVIDER_HTTP",
                f"HTTP {last.status_code} for {url}",
                http_status=last.status_code,
            )
        return last

    if last_exc is not None:
        raise MarketSimError("PROVIDER_ERROR", str(last_exc), http_status=502) from last_exc
    raise MarketSimError("PROVIDER_ERROR", "request exhausted without response", http_status=502)
