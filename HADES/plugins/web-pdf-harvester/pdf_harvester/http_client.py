"""Async HTTP client with redirect tracking and lightweight PDF probes."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import httpx

from .pdf_detect import DetectionResult, detect_from_headers, detect_from_magic
from .rate_limit import HostRateLimiter
from .urls import hostname_of, normalize_url, safe_normalize

USER_AGENT = "HADES-WebPDFHarvester/1.0 (+research; respectful crawler)"


@dataclass
class HttpFetchResult:
    url: str
    final_url: str
    status_code: int
    headers: dict[str, str]
    body: bytes | None = None
    text: str | None = None
    redirect_chain: list[str] = field(default_factory=list)
    error: str | None = None
    error_class: str | None = None
    detection: DetectionResult | None = None


class HttpClient:
    def __init__(
        self,
        *,
        timeout: float = 30.0,
        max_retries: int = 3,
        max_redirects: int = 10,
        rate_limiter: HostRateLimiter | None = None,
        allow_private: bool = False,
        max_html_bytes: int = 4 * 1024 * 1024,
    ) -> None:
        self.timeout = timeout
        self.max_retries = max_retries
        self.max_redirects = max_redirects
        self.rate_limiter = rate_limiter or HostRateLimiter()
        self.allow_private = allow_private
        self.max_html_bytes = max_html_bytes
        self._client: httpx.AsyncClient | None = None

    async def __aenter__(self) -> HttpClient:
        self._client = httpx.AsyncClient(
            headers={
                "User-Agent": USER_AGENT,
                "Accept": "text/html,application/xhtml+xml,application/pdf,*/*;q=0.8",
                "Accept-Encoding": "identity",
            },
            timeout=httpx.Timeout(self.timeout),
            follow_redirects=False,
            limits=httpx.Limits(max_connections=32, max_keepalive_connections=16),
        )
        return self

    async def __aexit__(self, *exc: Any) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    @property
    def client(self) -> httpx.AsyncClient:
        if self._client is None:
            raise RuntimeError("HttpClient must be used as async context manager")
        return self._client

    async def _request_once(
        self,
        method: str,
        url: str,
        *,
        referer: str | None = None,
        range_header: str | None = None,
    ) -> httpx.Response:
        headers: dict[str, str] = {}
        if referer:
            headers["Referer"] = referer
        if range_header:
            headers["Range"] = range_header
        host = hostname_of(url)
        await self.rate_limiter.wait(host)
        return await self.client.request(method, url, headers=headers)

    async def fetch(
        self,
        url: str,
        *,
        referer: str | None = None,
        method: str = "GET",
        read_body: bool = True,
        probe_pdf: bool = True,
    ) -> HttpFetchResult:
        current = normalize_url(url, allow_private=self.allow_private)
        chain = [current]
        last_error: str | None = None
        last_class: str | None = None

        for _attempt in range(self.max_retries + 1):
            try:
                redirects = 0
                while True:
                    response = await self._request_once(method if redirects == 0 else "GET", current, referer=referer)
                    if response.status_code in {301, 302, 303, 307, 308}:
                        location = response.headers.get("location")
                        await response.aclose()
                        if not location:
                            return HttpFetchResult(
                                url=url, final_url=current, status_code=response.status_code,
                                headers=dict(response.headers), redirect_chain=chain,
                                error="Redirect without Location", error_class="HTTP_ERROR",
                            )
                        nxt = safe_normalize(location, base=current, allow_private=self.allow_private)
                        if not nxt:
                            return HttpFetchResult(
                                url=url, final_url=current, status_code=response.status_code,
                                headers=dict(response.headers), redirect_chain=chain,
                                error="Redirect target blocked/invalid", error_class="SSRF_BLOCKED",
                            )
                        if nxt in chain:
                            return HttpFetchResult(
                                url=url, final_url=current, status_code=response.status_code,
                                headers=dict(response.headers), redirect_chain=chain,
                                error="Redirect loop", error_class="HTTP_ERROR",
                            )
                        chain.append(nxt)
                        current = nxt
                        redirects += 1
                        if redirects > self.max_redirects:
                            return HttpFetchResult(
                                url=url, final_url=current, status_code=response.status_code,
                                headers=dict(response.headers), redirect_chain=chain,
                                error="Too many redirects", error_class="HTTP_ERROR",
                            )
                        continue

                    if response.status_code in {429, 503}:
                        retry_after = response.headers.get("Retry-After")
                        delay = None
                        if retry_after:
                            try:
                                delay = float(retry_after)
                            except ValueError:
                                delay = None
                        self.rate_limiter.penalize(hostname_of(current), retry_after=delay, status=response.status_code)
                        await response.aclose()
                        last_error = f"HTTP {response.status_code}"
                        last_class = "HTTP_ERROR"
                        break

                    headers = {k.lower(): v for k, v in response.headers.items()}
                    detection = detect_from_headers(
                        current,
                        content_type=headers.get("content-type"),
                        content_disposition=headers.get("content-disposition"),
                        content_length=headers.get("content-length"),
                    )
                    body: bytes | None = None
                    text: str | None = None

                    async def _read_prefix(max_bytes: int = 1024) -> bytes:
                        chunks: list[bytes] = []
                        remaining = max_bytes
                        async for chunk in response.aiter_bytes():
                            if remaining <= 0:
                                break
                            pieces = chunk[:remaining]
                            chunks.append(pieces)
                            remaining -= len(pieces)
                            if remaining <= 0:
                                break
                        await response.aclose()
                        return b"".join(chunks)

                    if probe_pdf and (
                        detection.is_pdf
                        or detection.method == "url_pdf_but_html_mime"
                        or (not detection.is_pdf and "octet-stream" in (detection.mime_type or ""))
                    ):
                        # Read a small prefix from THIS response only — never open a nested
                        # request while the body is unread (HTTP/1.1 keepalive deadlock).
                        try:
                            prefix = await _read_prefix(1024)
                            magic = detect_from_magic(prefix, url=current, content_type=headers.get("content-type"))
                            if magic.method in {"magic_bytes", "html_body"}:
                                detection = magic
                            if detection.method == "html_body" and read_body:
                                # Prefix was HTML; keep it as body/text (may be truncated).
                                body = prefix
                                text = prefix.decode("utf-8", errors="replace")
                        except Exception:
                            try:
                                await response.aclose()
                            except Exception:
                                pass
                        return HttpFetchResult(
                            url=url,
                            final_url=current,
                            status_code=response.status_code,
                            headers=headers,
                            body=body,
                            text=text,
                            redirect_chain=chain,
                            detection=detection,
                            error=None if response.status_code < 400 else f"HTTP {response.status_code}",
                            error_class=None if response.status_code < 400 else "HTTP_ERROR",
                        )
                    elif read_body and response.status_code < 400:
                        body = await response.aread()
                        if len(body) > self.max_html_bytes:
                            body = body[: self.max_html_bytes]
                        mime = (headers.get("content-type") or "").lower()
                        if "html" in mime or "xml" in mime or body.lstrip()[:1] in (b"<",):
                            text = body.decode(response.charset_encoding or "utf-8", errors="replace")
                        elif probe_pdf:
                            magic = detect_from_magic(body[:16], url=current, content_type=headers.get("content-type"))
                            if magic.is_pdf:
                                detection = magic
                    else:
                        await response.aclose()

                    return HttpFetchResult(
                        url=url,
                        final_url=current,
                        status_code=response.status_code,
                        headers=headers,
                        body=body,
                        text=text,
                        redirect_chain=chain,
                        detection=detection,
                        error=None if response.status_code < 400 else f"HTTP {response.status_code}",
                        error_class=None if response.status_code < 400 else "HTTP_ERROR",
                    )
            except httpx.TimeoutException as exc:
                last_error = str(exc)
                last_class = "TIMEOUT"
            except httpx.HTTPError as exc:
                last_error = str(exc)
                last_class = "NETWORK_ERROR"
            except Exception as exc:
                last_error = str(exc)
                last_class = "NETWORK_ERROR"

        return HttpFetchResult(
            url=url, final_url=current, status_code=0, headers={}, redirect_chain=chain,
            error=last_error or "request failed", error_class=last_class or "NETWORK_ERROR",
        )

    async def fetch_robots_text(self, robots_url: str) -> str | None:
        try:
            result = await self.fetch(robots_url, read_body=True, probe_pdf=False)
            if result.status_code >= 400 or result.body is None:
                return None
            return result.body.decode("utf-8", errors="replace")
        except Exception:
            return None
