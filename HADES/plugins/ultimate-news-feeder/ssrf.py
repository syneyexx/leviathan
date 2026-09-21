"""Minimal public-URL guards for ultimate-news-feeder (SSRF hop checks)."""

from __future__ import annotations

import ipaddress
import urllib.error
import urllib.parse
import urllib.request


def is_blocked_host(host: str) -> bool:
    host = (host or "").lower().strip("[]")
    if not host:
        return True
    if host in {"localhost", "metadata.google.internal"}:
        return True
    if host.endswith(".localhost") or host.endswith(".local") or host.endswith(".internal"):
        return True
    try:
        ip = ipaddress.ip_address(host)
        return bool(
            ip.is_private
            or ip.is_loopback
            or ip.is_link_local
            or ip.is_multicast
            or ip.is_reserved
            or ip.is_unspecified
        )
    except ValueError:
        return False


def assert_public_http_url(url: str) -> str:
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme not in {"http", "https"}:
        raise ValueError("Only http/https URLs are allowed")
    host = (parsed.hostname or "").lower()
    if is_blocked_host(host):
        raise ValueError(f"Private/local host blocked: {host}")
    if parsed.username or parsed.password:
        raise ValueError("URL credentials are not allowed")
    return url


def open_public_url(
    url: str,
    *,
    headers: dict[str, str],
    timeout: float,
    max_hops: int = 8,
):
    """Open URL without auto-follow; validate each redirect hop. Caller must close."""
    opener = urllib.request.build_opener(urllib.request.HTTPHandler(), urllib.request.HTTPSHandler())
    current = assert_public_http_url(url)
    for _ in range(max_hops):
        req = urllib.request.Request(current, headers=headers)
        try:
            response = opener.open(req, timeout=timeout)
            assert_public_http_url(response.geturl())
            return response
        except urllib.error.HTTPError as exc:
            if int(getattr(exc, "code", 0) or 0) not in {301, 302, 303, 307, 308}:
                raise
            location = exc.headers.get("Location") if exc.headers else None
            if not location:
                raise
            current = assert_public_http_url(urllib.parse.urljoin(current, location))
    raise RuntimeError(f"Too many redirects for {url}")
