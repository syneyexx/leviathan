"""Centralized browser URL / SSRF policy.

Browser navigation can bypass normal HTTP-client SSRF controls, so this policy
is enforced inside the browser domain before navigate / download / crawl.
"""

from __future__ import annotations

import ipaddress
import socket
from typing import Any
from urllib.parse import urlparse

from .errors import BROWSER_TARGET_BLOCKED, BrowserDomainError

ALLOWED_SCHEMES_DEFAULT = frozenset({"https", "http"})
# data: only for readiness probes / explicit tests — never general automation.
INTERNAL_PROBE_SCHEMES = frozenset({"data"})
BLOCKED_SCHEMES = frozenset(
    {
        "file",
        "javascript",
        "vbscript",
        "chrome",
        "chrome-extension",
        "about",
        "blob",
        "ws",
        "wss",
        "ftp",
    }
)


def _host_is_private_or_local(host: str) -> bool:
    text = (host or "").strip().lower().rstrip(".")
    if not text:
        return True
    if text in {"localhost", "localhost.localdomain"}:
        return True
    if text.endswith(".localhost") or text.endswith(".local"):
        return True
    if text == "metadata.google.internal":
        return True
    try:
        ip = ipaddress.ip_address(text)
        return bool(
            ip.is_private
            or ip.is_loopback
            or ip.is_link_local
            or ip.is_reserved
            or ip.is_multicast
            or ip.is_unspecified
        )
    except ValueError:
        pass
    # DNS resolution — prefer fail-closed on resolution failure for general nav.
    try:
        infos = socket.getaddrinfo(text, None)
    except OSError:
        return True
    for info in infos:
        sockaddr = info[4]
        addr = sockaddr[0]
        try:
            ip = ipaddress.ip_address(addr)
        except ValueError:
            continue
        if (
            ip.is_private
            or ip.is_loopback
            or ip.is_link_local
            or ip.is_reserved
            or ip.is_multicast
            or ip.is_unspecified
            or str(ip) in {"169.254.169.254", "fd00:ec2::254"}
        ):
            return True
    return False


def validate_browser_url(
    url: str,
    *,
    allow_private: bool = False,
    allow_data_for_probe: bool = False,
    allowed_hosts: tuple[str, ...] | None = None,
    context: str = "navigate",
) -> dict[str, Any]:
    """Validate a browser navigation/download URL.

    Raises BrowserDomainError(BROWSER_TARGET_BLOCKED) on policy violation.
    """
    raw = str(url or "").strip()
    if not raw:
        raise BrowserDomainError(BROWSER_TARGET_BLOCKED, "empty URL", details={"context": context})
    parsed = urlparse(raw)
    scheme = (parsed.scheme or "").lower()
    if scheme in BLOCKED_SCHEMES:
        raise BrowserDomainError(
            BROWSER_TARGET_BLOCKED,
            f"scheme {scheme!r} is blocked for browser {context}",
            details={"scheme": scheme, "context": context},
        )
    if scheme in INTERNAL_PROBE_SCHEMES:
        if not allow_data_for_probe:
            raise BrowserDomainError(
                BROWSER_TARGET_BLOCKED,
                "data: URLs are only permitted for readiness/testing probes",
                details={"scheme": scheme, "context": context},
            )
        return {"url": raw, "scheme": scheme, "host": None, "private": False, "probe": True}
    if scheme not in ALLOWED_SCHEMES_DEFAULT:
        raise BrowserDomainError(
            BROWSER_TARGET_BLOCKED,
            f"scheme {scheme!r} is not permitted",
            details={"scheme": scheme, "context": context},
        )
    host = (parsed.hostname or "").lower()
    if allowed_hosts is not None:
        allow = {h.lower() for h in allowed_hosts}
        if host not in allow:
            raise BrowserDomainError(
                BROWSER_TARGET_BLOCKED,
                f"host {host!r} not in allowlist",
                details={"host": host, "allowed_hosts": sorted(allow), "context": context},
            )
        # QA localhost allowlist is an intentional private-network exception.
        return {
            "url": raw,
            "scheme": scheme,
            "host": host,
            "private": _host_is_private_or_local(host),
            "allowlist": True,
        }
    private = _host_is_private_or_local(host)
    if private and not allow_private:
        raise BrowserDomainError(
            BROWSER_TARGET_BLOCKED,
            f"private/loopback/metadata target blocked: {host!r}",
            details={"host": host, "context": context, "ssrf": True},
        )
    return {"url": raw, "scheme": scheme, "host": host, "private": private, "allowlist": False}


def sanitize_download_filename(name: str, *, max_len: int = 180) -> str:
    base = str(name or "download").replace("\\", "/").split("/")[-1]
    cleaned = "".join(ch if ch.isalnum() or ch in "._- " else "_" for ch in base).strip(" ._")
    if not cleaned:
        cleaned = "download"
    return cleaned[:max_len]
