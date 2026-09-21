"""URL normalization, SSRF protection and host helpers."""

from __future__ import annotations

import ipaddress
import re
import socket
import urllib.parse
from typing import Iterable

TRACKING_PARAMS = {
    "utm_source", "utm_medium", "utm_campaign", "utm_term", "utm_content",
    "utm_id", "utm_reader", "gclid", "fbclid", "mc_cid", "mc_eid",
    "msclkid", "_ga", "yclid", "igshid",
}

BLOCKED_SCHEMES = {"file", "javascript", "data", "ftp", "blob", "about", "chrome"}


class UrlSecurityError(ValueError):
    """Raised when a URL is blocked for security reasons."""


def hostname_of(url: str) -> str:
    return (urllib.parse.urlsplit(url).hostname or "").lower()


def same_registrable_host(host_a: str, host_b: str) -> bool:
    a = (host_a or "").lower().split(":", 1)[0].strip(".")
    b = (host_b or "").lower().split(":", 1)[0].strip(".")
    if not a or not b:
        return False
    return a == b or a.endswith("." + b) or b.endswith("." + a)


def _is_private_ip(ip: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    return bool(
        ip.is_private
        or ip.is_loopback
        or ip.is_link_local
        or ip.is_multicast
        or ip.is_reserved
        or ip.is_unspecified
    )


def is_private_or_local_host(host: str, *, allow_private: bool = False) -> bool:
    if allow_private:
        return False
    host = (host or "").lower().strip("[]")
    if not host:
        return True
    if host in {"localhost", "metadata.google.internal"}:
        return True
    if host.endswith(".localhost") or host.endswith(".local") or host.endswith(".internal"):
        return True
    try:
        ip = ipaddress.ip_address(host)
        return _is_private_ip(ip)
    except ValueError:
        pass
    # DNS resolution check (best-effort; also covers DNS rebinding at resolve time)
    try:
        infos = socket.getaddrinfo(host, None)
    except socket.gaierror:
        return False
    for info in infos:
        addr = info[4][0]
        try:
            if _is_private_ip(ipaddress.ip_address(addr)):
                return True
        except ValueError:
            continue
    return False


def strip_tracking_params(query: str) -> str:
    if not query:
        return ""
    pairs = urllib.parse.parse_qsl(query, keep_blank_values=True)
    kept = [(k, v) for k, v in pairs if k.lower() not in TRACKING_PARAMS]
    return urllib.parse.urlencode(kept, doseq=True)


def normalize_url(url: str, *, base: str | None = None, allow_private: bool = False) -> str:
    raw = (url or "").strip()
    if not raw:
        raise UrlSecurityError("Empty URL")
    if base:
        raw = urllib.parse.urljoin(base, raw)
    if raw.startswith("//"):
        scheme = urllib.parse.urlsplit(base or "https://example.invalid").scheme or "https"
        raw = f"{scheme}:{raw}"
    parsed = urllib.parse.urlsplit(raw)
    scheme = parsed.scheme.lower()
    if scheme in BLOCKED_SCHEMES or not scheme:
        raise UrlSecurityError(f"Blocked or missing URL scheme: {scheme or '(none)'}")
    if scheme not in {"http", "https"}:
        raise UrlSecurityError(f"Unsupported URL scheme: {scheme}")
    host = (parsed.hostname or "").lower()
    if not host:
        raise UrlSecurityError("URL missing hostname")
    if is_private_or_local_host(host, allow_private=allow_private):
        raise UrlSecurityError(f"Private/local host blocked: {host}")
    # Drop credentials from netloc
    port = parsed.port
    netloc = host
    if port and not ((scheme == "http" and port == 80) or (scheme == "https" and port == 443)):
        netloc = f"{host}:{port}"
    path = parsed.path or "/"
    path = re.sub(r"/{2,}", "/", path)
    query = strip_tracking_params(parsed.query)
    # Fragment is never meaningful for crawl identity
    return urllib.parse.urlunsplit((scheme, netloc, path, query, ""))


def safe_normalize(url: str, *, base: str | None = None, allow_private: bool = False) -> str | None:
    try:
        return normalize_url(url, base=base, allow_private=allow_private)
    except Exception:
        return None


def join_click_path(parent_path: Iterable[str] | None, url: str) -> list[str]:
    path = list(parent_path or [])
    if not path or path[-1] != url:
        path.append(url)
    return path
