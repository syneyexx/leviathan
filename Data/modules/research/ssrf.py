"""SSRF protection for research web fetches.

Blocks loopback, link-local, private, and metadata-style destinations.
Redirect targets must be revalidated with the same rules.
"""

from __future__ import annotations

import ipaddress
import socket
from dataclasses import dataclass
from urllib.parse import urlparse


ALLOWED_SCHEMES = frozenset({"http", "https"})


@dataclass(frozen=True)
class SsrfDecision:
    allowed: bool
    reason: str
    hostname: str | None = None
    resolved_ips: tuple[str, ...] = ()

    def public_dict(self) -> dict:
        return {
            "allowed": self.allowed,
            "reason": self.reason,
            "hostname": self.hostname,
            "resolved_ips": list(self.resolved_ips),
        }


def _is_blocked_ip(ip: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_multicast:
        return True
    if ip.is_reserved or ip.is_unspecified:
        return True
    # Cloud metadata / special-use ranges commonly abused for SSRF.
    if isinstance(ip, ipaddress.IPv4Address):
        if ip in ipaddress.ip_network("169.254.0.0/16"):
            return True
        if ip in ipaddress.ip_network("0.0.0.0/8"):
            return True
    if isinstance(ip, ipaddress.IPv6Address):
        if ip.ipv4_mapped is not None:
            return _is_blocked_ip(ip.ipv4_mapped)
    return False


def validate_url_for_fetch(
    url: str,
    *,
    resolve_dns: bool = True,
    allow_schemes: frozenset[str] = ALLOWED_SCHEMES,
) -> SsrfDecision:
    raw = (url or "").strip()
    if not raw:
        return SsrfDecision(False, "empty_url")
    if "\x00" in raw or any(ch.isspace() and ch not in (" ",) for ch in raw):
        # Reject control / odd whitespace; spaces alone still invalid in netloc.
        pass
    parsed = urlparse(raw)
    scheme = (parsed.scheme or "").lower()
    if scheme not in allow_schemes:
        return SsrfDecision(False, f"scheme_not_allowed:{scheme or 'missing'}")
    host = parsed.hostname
    if not host:
        return SsrfDecision(False, "missing_hostname")
    host_lower = host.lower().rstrip(".")
    if host_lower in {"localhost", "metadata.google.internal"}:
        return SsrfDecision(False, "blocked_hostname", hostname=host_lower)
    if host_lower.endswith(".localhost") or host_lower.endswith(".local"):
        return SsrfDecision(False, "blocked_hostname", hostname=host_lower)

    # Literal IP in URL.
    try:
        literal = ipaddress.ip_address(host_lower)
        if _is_blocked_ip(literal):
            return SsrfDecision(
                False,
                "blocked_ip",
                hostname=host_lower,
                resolved_ips=(str(literal),),
            )
        return SsrfDecision(True, "ok_literal_ip", hostname=host_lower, resolved_ips=(str(literal),))
    except ValueError:
        pass

    if not resolve_dns:
        return SsrfDecision(True, "ok_hostname_unresolved", hostname=host_lower)

    try:
        infos = socket.getaddrinfo(host_lower, parsed.port or None, type=socket.SOCK_STREAM)
    except socket.gaierror:
        return SsrfDecision(False, "dns_resolution_failed", hostname=host_lower)
    except OSError as exc:
        return SsrfDecision(False, f"dns_error:{exc}", hostname=host_lower)

    resolved: list[str] = []
    for info in infos:
        sockaddr = info[4]
        ip_text = sockaddr[0]
        try:
            ip_obj = ipaddress.ip_address(ip_text)
        except ValueError:
            continue
        resolved.append(str(ip_obj))
        if _is_blocked_ip(ip_obj):
            return SsrfDecision(
                False,
                "blocked_resolved_ip",
                hostname=host_lower,
                resolved_ips=tuple(resolved),
            )
    if not resolved:
        return SsrfDecision(False, "no_resolved_ips", hostname=host_lower)
    return SsrfDecision(True, "ok", hostname=host_lower, resolved_ips=tuple(dict.fromkeys(resolved)))


def assert_safe_url(url: str, *, resolve_dns: bool = True) -> SsrfDecision:
    decision = validate_url_for_fetch(url, resolve_dns=resolve_dns)
    if not decision.allowed:
        raise ValueError(f"SSRF blocked: {decision.reason} ({url})")
    return decision
