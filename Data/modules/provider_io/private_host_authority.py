"""Private-host / SSRF authority — never caller-granted from job payloads.

Ordinary capability callers and model-generated job arguments must not be able
to set ``allow_private_hosts=true`` and reach RFC1918 / loopback / metadata.

Authority sources (trusted configuration only):

1. ``LEVIATHAN_PROVIDER_ALLOW_PRIVATE_HOSTS`` operator env override
2. Endpoint allowlist from ``LEVIATHAN_PROVIDER_PRIVATE_HOST_ALLOWLIST``
   (bare host = any port; ``host:port`` / full URL = exact scheme+host+port)
3. Configured local model ``base_url`` / managed-serving endpoints — matched by
   **scheme + host + port** (not hostname alone). Model-provider trust does
   **not** apply to generic HTTP.

Job / payload ``allow_private_hosts`` fields are ignored.
"""

from __future__ import annotations

import os
from typing import Any
from urllib.parse import urlparse


_PRIVATE_ENV_OVERRIDE = "LEVIATHAN_PROVIDER_ALLOW_PRIVATE_HOSTS"
_ALLOWLIST_ENV = "LEVIATHAN_PROVIDER_PRIVATE_HOST_ALLOWLIST"

# (scheme, host, port) — port always concrete (default 80/443 when omitted).
EndpointKey = tuple[str, str, int]


def _env_truthy(name: str) -> bool:
    return (os.environ.get(name) or "").strip().lower() in {"1", "true", "yes", "on"}


def _normalize_host(host: str | None) -> str:
    if not host:
        return ""
    h = host.strip().lower().rstrip(".")
    if h.startswith("[") and h.endswith("]"):
        h = h[1:-1]
    # Strip zone id for link-local IPv6 if present
    if "%" in h:
        h = h.split("%", 1)[0]
    return h


def _default_port(scheme: str) -> int:
    return 443 if scheme == "https" else 80


def endpoint_identity(url: str) -> EndpointKey | None:
    """Normalize ``url`` to ``(scheme, host, port)`` for private-host matching."""
    raw = (url or "").strip()
    if not raw:
        return None
    parsed = urlparse(raw if "://" in raw else f"http://{raw}")
    scheme = (parsed.scheme or "http").lower()
    if scheme not in {"http", "https"}:
        return None
    host = _normalize_host(parsed.hostname)
    if not host:
        return None
    port = parsed.port if parsed.port is not None else _default_port(scheme)
    return (scheme, host, int(port))


def _parse_allowlist_entry(part: str) -> tuple[str | None, EndpointKey | None]:
    """Return ``(bare_host, exact_endpoint)`` for one allowlist token."""
    token = (part or "").strip()
    if not token:
        return None, None
    # Full URL → exact endpoint identity.
    if "://" in token:
        ep = endpoint_identity(token)
        return None, ep
    # host:port (no scheme) → http + exact port.
    if ":" in token and not token.startswith("["):
        host_part, _, port_part = token.rpartition(":")
        if host_part and port_part.isdigit():
            host = _normalize_host(host_part)
            if host:
                return None, ("http", host, int(port_part))
    host = _normalize_host(token)
    if host:
        return host, None
    return None, None


def _env_allowlist_hosts_and_endpoints() -> tuple[set[str], set[EndpointKey]]:
    hosts: set[str] = set()
    endpoints: set[EndpointKey] = set()
    raw = (os.environ.get(_ALLOWLIST_ENV) or "").strip()
    if not raw:
        return hosts, endpoints
    for part in raw.split(","):
        bare, ep = _parse_allowlist_entry(part)
        if bare:
            hosts.add(bare)
        if ep:
            endpoints.add(ep)
    return hosts, endpoints


def configured_model_private_endpoints(*, settings: Any | None = None) -> set[EndpointKey]:
    """Trusted model / managed-serving endpoints as scheme+host+port identities."""
    endpoints: set[EndpointKey] = set()
    if settings is None:
        try:
            from Data.backend.config import load_settings

            settings = load_settings()
        except Exception:  # noqa: BLE001
            settings = None
    if settings is None:
        return endpoints
    candidates: list[str] = []
    for attr_path in (
        ("model", "base_url"),
        ("managed_serving", "base_url"),
    ):
        obj: Any = settings
        for attr in attr_path:
            obj = getattr(obj, attr, None)
            if obj is None:
                break
        if isinstance(obj, str) and obj.strip():
            candidates.append(obj.strip())
    llm = getattr(settings, "llm_base_url", None)
    if isinstance(llm, str) and llm.strip():
        candidates.append(llm.strip())
    for raw in candidates:
        ep = endpoint_identity(raw if "://" in raw else f"http://{raw}")
        if ep:
            endpoints.add(ep)
    return endpoints


def configured_private_host_allowlist(*, settings: Any | None = None) -> set[str]:
    """Hostnames from the operator env allowlist (not model endpoints).

    Model-provider trust is endpoint-identity based — see
    ``configured_model_private_endpoints``. Generic HTTP must not treat this
    as inheriting model base_url hosts.
    """
    hosts, _endpoints = _env_allowlist_hosts_and_endpoints()
    _ = settings  # retained for call-site compatibility
    return hosts


def resolve_allow_private_hosts_for_url(
    url: str,
    *,
    settings: Any | None = None,
    request_flag: bool | None = None,  # ignored — retained for call-site clarity
    trust_model_endpoints: bool = False,
) -> bool:
    """Return True only when trusted policy permits private-host access for ``url``.

    ``request_flag`` from jobs/payloads is intentionally ignored.

    ``trust_model_endpoints``: when True (model-provider adapters only), configured
    model/managed-serving base_url identities may authorize matching scheme+host+port.
    Generic HTTP must leave this False so it does not inherit model-provider trust.
    """
    _ = request_flag  # untrusted — do not use
    if _env_truthy(_PRIVATE_ENV_OVERRIDE):
        return True
    target = endpoint_identity(url if "://" in (url or "") else f"http://{url or ''}")
    if target is None:
        return False
    bare_hosts, exact_endpoints = _env_allowlist_hosts_and_endpoints()
    if target in exact_endpoints:
        return True
    if target[1] in bare_hosts:
        # Operator bare-host allowlist: any port on that host.
        return True
    if trust_model_endpoints:
        return target in configured_model_private_endpoints(settings=settings)
    return False


def redirect_target_private_hosts_allowed(
    location: str,
    *,
    settings: Any | None = None,
    trust_model_endpoints: bool = False,
) -> bool:
    """Re-validate a redirect ``Location`` with the same endpoint-identity rules."""
    return resolve_allow_private_hosts_for_url(
        location,
        settings=settings,
        trust_model_endpoints=trust_model_endpoints,
    )


def strip_untrusted_private_host_flags(args: dict[str, Any], payload: dict[str, Any]) -> None:
    """Remove forgeable allow_private_hosts from job args/payload before request build."""
    args.pop("allow_private_hosts", None)
    payload.pop("allow_private_hosts", None)
