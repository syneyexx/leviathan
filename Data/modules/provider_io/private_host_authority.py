"""Private-host / SSRF authority — never caller-granted from job payloads.

Ordinary capability callers and model-generated job arguments must not be able
to set ``allow_private_hosts=true`` and reach RFC1918 / loopback / metadata.

Authority sources (trusted configuration only):

1. ``LEVIATHAN_PROVIDER_ALLOW_PRIVATE_HOSTS`` operator env override
2. Hostname allowlist from ``LEVIATHAN_PROVIDER_PRIVATE_HOST_ALLOWLIST``
3. Hostname of the configured local model ``base_url`` (and related endpoints)

Job / payload ``allow_private_hosts`` fields are ignored.
"""

from __future__ import annotations

import os
from typing import Any
from urllib.parse import urlparse


_PRIVATE_ENV_OVERRIDE = "LEVIATHAN_PROVIDER_ALLOW_PRIVATE_HOSTS"
_ALLOWLIST_ENV = "LEVIATHAN_PROVIDER_PRIVATE_HOST_ALLOWLIST"


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


def configured_private_host_allowlist(*, settings: Any | None = None) -> set[str]:
    """Trusted hostnames that may receive private-network provider traffic."""
    hosts: set[str] = set()
    raw = (os.environ.get(_ALLOWLIST_ENV) or "").strip()
    if raw:
        for part in raw.split(","):
            h = _normalize_host(part)
            if h:
                hosts.add(h)
    if settings is None:
        try:
            from Data.backend.config import load_settings

            settings = load_settings()
        except Exception:  # noqa: BLE001
            settings = None
    if settings is not None:
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
                parsed = urlparse(obj if "://" in obj else f"http://{obj}")
                h = _normalize_host(parsed.hostname)
                if h:
                    hosts.add(h)
    # Common local inference defaults commonly configured by operators.
    hosts.update({"127.0.0.1", "localhost", "::1"})
    return hosts


def resolve_allow_private_hosts_for_url(
    url: str,
    *,
    settings: Any | None = None,
    request_flag: bool | None = None,  # ignored — retained for call-site clarity
) -> bool:
    """Return True only when trusted policy permits private-host access for ``url``.

    ``request_flag`` from jobs/payloads is intentionally ignored.
    """
    _ = request_flag  # untrusted — do not use
    if _env_truthy(_PRIVATE_ENV_OVERRIDE):
        return True
    parsed = urlparse(url if "://" in (url or "") else f"http://{url or ''}")
    host = _normalize_host(parsed.hostname)
    if not host:
        return False
    allowlist = configured_private_host_allowlist(settings=settings)
    return host in allowlist


def strip_untrusted_private_host_flags(args: dict[str, Any], payload: dict[str, Any]) -> None:
    """Remove forgeable allow_private_hosts from job args/payload before request build."""
    args.pop("allow_private_hosts", None)
    payload.pop("allow_private_hosts", None)
