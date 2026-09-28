"""Canonical endpoint locality classification for model/provider HTTP.

Trusted LOCAL endpoints may be reached by the Model Control Plane / local
runtime under operator configuration. REMOTE SaaS/cloud endpoints must execute
via ``provider_io`` — never as ad-hoc Control Plane sockets.

Authority comes from configuration (loopback defaults, private-host allowlist,
configured model/managed-serving base URLs). Callers cannot forge trust via
``allow_private_hosts`` in job payloads.
"""

from __future__ import annotations

import ipaddress
import os
from enum import Enum
from typing import Any
from urllib.parse import urlparse

from Data.modules.provider_io.private_host_authority import (
    configured_model_private_endpoints,
    endpoint_identity,
    resolve_allow_private_hosts_for_url,
)


class EndpointLocality(str, Enum):
    LOCAL_TRUSTED = "LOCAL_TRUSTED"
    REMOTE = "REMOTE"
    INVALID = "INVALID"


_LOOPBACK_HOSTS = frozenset({"localhost", "127.0.0.1", "::1", "0.0.0.0"})


def _host_is_loopback(host: str) -> bool:
    h = (host or "").strip().lower().rstrip(".")
    if h in _LOOPBACK_HOSTS:
        return True
    try:
        return bool(ipaddress.ip_address(h).is_loopback)
    except ValueError:
        return False


def classify_endpoint_locality(
    url: str | None,
    *,
    settings: Any | None = None,
) -> EndpointLocality:
    """Classify ``url`` as trusted-local, remote, or invalid.

    LOCAL_TRUSTED when:
    - scheme is http/https AND host is loopback, OR
    - endpoint matches configured private-host / model-serving authority

    REMOTE otherwise (public Internet / non-trusted hosts).
    """
    raw = (url or "").strip()
    if not raw:
        return EndpointLocality.INVALID
    parsed = urlparse(raw if "://" in raw else f"http://{raw}")
    scheme = (parsed.scheme or "http").lower()
    if scheme not in {"http", "https"}:
        return EndpointLocality.INVALID
    identity = endpoint_identity(raw)
    if identity is None:
        return EndpointLocality.INVALID
    _scheme, host, _port = identity
    if _host_is_loopback(host):
        return EndpointLocality.LOCAL_TRUSTED
    # Explicit operator / model-serving trust (scheme+host+port).
    if resolve_allow_private_hosts_for_url(
        raw,
        settings=settings,
        trust_model_endpoints=True,
    ):
        return EndpointLocality.LOCAL_TRUSTED
    # Configured model endpoints that are non-loopback private (e.g. LAN LM Studio).
    if identity in configured_model_private_endpoints(settings=settings):
        return EndpointLocality.LOCAL_TRUSTED
    return EndpointLocality.REMOTE


def is_trusted_local_endpoint(url: str | None, *, settings: Any | None = None) -> bool:
    return classify_endpoint_locality(url, settings=settings) == EndpointLocality.LOCAL_TRUSTED


def remote_llm_may_use_inline_http() -> bool:
    """True only when Control Plane may open remote LLM sockets inline.

    Production externalization forbids this. Specialist ``provider_io`` workers
    own remote sockets via their adapters (not OpenAICompatibleLLM).
    """
    from Data.modules.execution.workload import externalize_api_enabled

    if not externalize_api_enabled():
        return True
    # Explicit test/dev escape hatch only.
    raw = (os.environ.get("LEVIATHAN_ALLOW_INLINE_REMOTE_LLM") or "").strip().lower()
    return raw in {"1", "true", "yes", "on"}


def assert_local_or_externalized_remote(
    url: str | None,
    *,
    settings: Any | None = None,
    context: str = "llm",
) -> EndpointLocality:
    """Fail closed when a remote endpoint would be dialed from Control Plane.

    Returns the classified locality. Raises ``PermissionError`` (callers map to
    typed provider/model errors) when REMOTE and inline remote HTTP is forbidden.
    """
    locality = classify_endpoint_locality(url, settings=settings)
    if locality == EndpointLocality.INVALID:
        raise ValueError(f"Invalid {context} endpoint URL")
    if locality == EndpointLocality.LOCAL_TRUSTED:
        return locality
    if remote_llm_may_use_inline_http():
        return locality
    raise PermissionError(
        f"REMOTE {context} endpoint requires provider_io execution; "
        f"Control Plane must not open remote provider sockets "
        f"(endpoint locality={locality.value})"
    )
