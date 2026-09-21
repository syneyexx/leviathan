"""Shared URL scheme / host guards for outbound HTTP (SSRF hardening).

Used by web research, plugin git import, MCP, and other non-LM-Studio fetchers.
Loopback LM Studio traffic must continue to use its own client — do not route
model endpoints through these guards with allow_private=False.

Validation is fail-closed: unresolved hosts and every non-globally-routable IP
are rejected. Callers that follow redirects must still re-validate every hop
(follow_redirects=False + Location normalization).
"""

from __future__ import annotations

import ipaddress
import socket
import urllib.parse
from typing import Any

BLOCKED_SCHEMES = frozenset({"file", "javascript", "data", "ftp", "blob", "about", "chrome"})
ALLOWED_SCHEMES = frozenset({"http", "https"})

# Azure exposes host/agent services on this platform virtual IP. Python's
# ipaddress currently classifies it as globally routable, so is_global alone
# is not sufficient for SSRF policy. Other common metadata addresses (for
# example 169.254.169.254 and 100.100.100.200) are already non-global.
_BLOCKED_METADATA_IPS = frozenset({ipaddress.ip_address("168.63.129.16")})
_LOCAL_HOST_SUFFIXES = (".localhost", ".local", ".internal")


class UrlSecurityError(ValueError):
    """Raised when a URL is blocked for security reasons."""


def _is_private_ip(ip: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    """Reject anything that is not globally routable or is a metadata endpoint."""
    return not bool(ip.is_global) or ip in _BLOCKED_METADATA_IPS


def _normalized_host(host: str) -> str:
    return (host or "").lower().strip("[]").rstrip(".")


def _coerce_domain_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        parts = [part.strip() for part in value.replace(";", ",").split(",")]
        return [part.lower().rstrip(".") for part in parts if part.strip()]
    if isinstance(value, (list, tuple, set)):
        out: list[str] = []
        for item in value:
            text = str(item or "").strip().lower().rstrip(".")
            if text:
                out.append(text)
        return out
    return []


def host_matches_domain_rule(host: str, rule: str) -> bool:
    """Match host against an allow/deny rule (exact or ``*.suffix`` / bare suffix)."""
    normalized_host = _normalized_host(host)
    normalized_rule = (rule or "").lower().strip().rstrip(".")
    if not normalized_host or not normalized_rule:
        return False
    if normalized_rule.startswith("*."):
        suffix = normalized_rule[2:]
        return normalized_host == suffix or normalized_host.endswith("." + suffix)
    return normalized_host == normalized_rule or normalized_host.endswith("." + normalized_rule)


def assert_domain_policy(
    host: str,
    *,
    allowlist: Any = None,
    denylist: Any = None,
    purpose: str = "fetch",
) -> None:
    """Enforce optional domain allow/deny lists. Empty allowlist means unrestricted."""
    normalized = _normalized_host(host)
    deny_rules = _coerce_domain_list(denylist)
    for rule in deny_rules:
        if host_matches_domain_rule(normalized, rule):
            raise UrlSecurityError(f"Domain denylist blocked host for {purpose}: {normalized}")
    allow_rules = _coerce_domain_list(allowlist)
    if allow_rules and not any(host_matches_domain_rule(normalized, rule) for rule in allow_rules):
        raise UrlSecurityError(f"Domain allowlist blocked host for {purpose}: {normalized}")


def load_network_domain_policy() -> tuple[list[str], list[str], int]:
    """Read allowlist/denylist/redirect_limit from ControlService when available."""
    allowlist: list[str] = []
    denylist: list[str] = []
    redirect_limit = 10
    try:
        from control.service import resolve_setting

        allowlist = _coerce_domain_list(resolve_setting("network.domain_allowlist", default=[]))
        denylist = _coerce_domain_list(resolve_setting("network.domain_denylist", default=[]))
        raw_limit = resolve_setting("network.redirect_limit", default=10)
        if raw_limit is None:
            redirect_limit = 10
        else:
            redirect_limit = max(0, int(raw_limit))
    except Exception:
        pass
    return allowlist, denylist, redirect_limit


def _is_explicit_loopback_host(host: str) -> bool:
    normalized = _normalized_host(host)
    literal_host = normalized.split("%", 1)[0]
    try:
        return bool(ipaddress.ip_address(literal_host).is_loopback)
    except ValueError:
        return normalized == "localhost" or normalized.endswith(".localhost")


def resolve_safe_host_addresses(
    host: str,
    port: int | None = None,
    *,
    allow_private: bool = False,
    allow_loopback: bool = False,
    purpose: str = "connect",
) -> tuple[str, ...]:
    """Resolve once, validate every result, and return numeric dial targets.

    Public destinations must resolve exclusively to globally routable addresses.
    ``allow_loopback`` is deliberately narrower than ``allow_private``: it only
    permits an explicitly loopback-named/literal host and still requires every
    DNS answer to be loopback. This is the safe mode for local MCP/OAuth-style
    services because a public hostname cannot rebind into localhost.

    ``allow_private`` remains available for explicitly trusted private-network
    integrations. It must not be used for attacker-controlled/public URLs.
    """
    normalized = _normalized_host(host)
    if not normalized:
        raise UrlSecurityError(f"URL missing hostname for {purpose}")

    explicit_loopback = _is_explicit_loopback_host(normalized)
    if not allow_private and normalized == "metadata.google.internal":
        raise UrlSecurityError(f"Metadata host blocked for {purpose}: {normalized}")
    if not allow_private and not allow_loopback and (
        normalized == "localhost" or normalized.endswith(_LOCAL_HOST_SUFFIXES)
    ):
        raise UrlSecurityError(f"Private/non-public host blocked for {purpose}: {normalized}")
    if allow_loopback and not allow_private and not explicit_loopback:
        # Loopback mode does not weaken policy for ordinary hostnames.
        allow_loopback = False

    literal_host = normalized.split("%", 1)[0]
    try:
        literal = ipaddress.ip_address(literal_host)
    except ValueError:
        try:
            infos = socket.getaddrinfo(normalized, port, type=socket.SOCK_STREAM)
        except (socket.gaierror, OSError) as exc:
            raise UrlSecurityError(f"Unresolved host blocked for {purpose}: {normalized}") from exc

        addresses: list[str] = []
        seen: set[str] = set()
        for info in infos:
            raw = str(info[4][0]).split("%", 1)[0]
            try:
                address = ipaddress.ip_address(raw)
            except ValueError:
                continue
            canonical = str(address)
            if canonical not in seen:
                seen.add(canonical)
                addresses.append(canonical)
    else:
        addresses = [str(literal)]

    if not addresses:
        raise UrlSecurityError(f"Unresolved host blocked for {purpose}: {normalized}")

    parsed_addresses = tuple(ipaddress.ip_address(raw) for raw in addresses)
    if allow_private:
        return tuple(str(address) for address in parsed_addresses)
    if allow_loopback:
        if not all(address.is_loopback for address in parsed_addresses):
            raise UrlSecurityError(
                f"Non-loopback address blocked for local {purpose}: {normalized}"
            )
        return tuple(str(address) for address in parsed_addresses)

    for address in parsed_addresses:
        if _is_private_ip(address):
            raise UrlSecurityError(
                f"Private/non-public host blocked for {purpose}: {normalized}"
            )
    return tuple(str(address) for address in parsed_addresses)


def is_private_or_local_host(
    host: str,
    *,
    allow_private: bool = False,
    allow_loopback: bool = False,
) -> bool:
    """True when host is not allowed by the selected outbound-host policy."""
    if allow_private:
        return False
    try:
        resolve_safe_host_addresses(
            host,
            allow_private=False,
            allow_loopback=allow_loopback,
            purpose="host validation",
        )
    except UrlSecurityError:
        return True
    return False


def assert_public_http_url(
    url: str,
    *,
    allow_private: bool = False,
    allow_loopback: bool = False,
    purpose: str = "fetch",
    domain_allowlist: Any = None,
    domain_denylist: Any = None,
    apply_settings_domain_policy: bool = True,
) -> urllib.parse.ParseResult:
    """Validate scheme + host for an outbound URL. Raises UrlSecurityError on reject."""
    raw = (url or "").strip()
    if not raw:
        raise UrlSecurityError(f"Empty URL blocked for {purpose}")
    parsed = urllib.parse.urlparse(raw)
    scheme = (parsed.scheme or "").lower()
    if scheme in BLOCKED_SCHEMES or not scheme:
        raise UrlSecurityError(f"Blocked or missing URL scheme for {purpose}: {scheme or '(none)'}")
    if scheme not in ALLOWED_SCHEMES:
        raise UrlSecurityError(f"Unsupported URL scheme for {purpose}: {scheme}")
    host = (parsed.hostname or "").lower()
    if not host:
        raise UrlSecurityError(f"URL missing hostname for {purpose}")
    if parsed.username or parsed.password:
        raise UrlSecurityError(f"URL credentials are not allowed for {purpose}")
    try:
        _ = parsed.port
    except ValueError as exc:
        raise UrlSecurityError(f"Invalid URL port for {purpose}") from exc
    if is_private_or_local_host(
        host,
        allow_private=allow_private,
        allow_loopback=allow_loopback,
    ):
        raise UrlSecurityError(f"Private/non-public or unresolved host blocked for {purpose}: {host}")
    effective_allow = domain_allowlist
    effective_deny = domain_denylist
    if apply_settings_domain_policy and effective_allow is None and effective_deny is None:
        settings_allow, settings_deny, _ = load_network_domain_policy()
        effective_allow = settings_allow
        effective_deny = settings_deny
    assert_domain_policy(
        host,
        allowlist=effective_allow,
        denylist=effective_deny,
        purpose=purpose,
    )
    return parsed


def safe_public_url(
    url: str,
    *,
    base: str | None = None,
    allow_private: bool = False,
    allow_loopback: bool = False,
    domain_allowlist: Any = None,
    domain_denylist: Any = None,
    apply_settings_domain_policy: bool = True,
) -> str | None:
    """Normalize to absolute http(s) URL or return None when blocked."""
    raw = (url or "").strip()
    if not raw:
        return None
    if base:
        raw = urllib.parse.urljoin(base, raw)
    if raw.startswith("//"):
        scheme = urllib.parse.urlsplit(base or "https://example.invalid").scheme or "https"
        raw = f"{scheme}:{raw}"
    try:
        parsed = assert_public_http_url(
            raw,
            allow_private=allow_private,
            allow_loopback=allow_loopback,
            domain_allowlist=domain_allowlist,
            domain_denylist=domain_denylist,
            apply_settings_domain_policy=apply_settings_domain_policy,
        )
    except UrlSecurityError:
        return None
    host = (parsed.hostname or "").lower()
    try:
        host_ip = ipaddress.ip_address(host.split("%", 1)[0])
    except ValueError:
        rendered_host = host
    else:
        rendered_host = f"[{host}]" if host_ip.version == 6 else host
    port = parsed.port
    netloc = rendered_host
    if port and not ((parsed.scheme == "http" and port == 80) or (parsed.scheme == "https" and port == 443)):
        netloc = f"{rendered_host}:{port}"
    path = parsed.path or "/"
    return urllib.parse.urlunparse((parsed.scheme.lower(), netloc, path, "", parsed.query, ""))


def redirect_location(response: Any, current_url: str) -> str | None:
    """Extract Location header for a redirect response, joined to current_url."""
    status = int(getattr(response, "status_code", 0) or 0)
    if status not in {301, 302, 303, 307, 308}:
        return None
    headers = getattr(response, "headers", None) or {}
    location = headers.get("location") or headers.get("Location")
    if not location:
        return None
    return urllib.parse.urljoin(current_url, str(location).strip())
