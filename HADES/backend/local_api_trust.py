"""Trusted Host / Origin / peer protection for the local HADES API.

CORS alone is a response policy. Browser-triggerable requests still need an
execution-side check so a hostile page cannot cause local side effects merely
because it cannot read the response body.

Trust is based on the TCP peer address (``request.client.host``). Host/Origin
checks remain as defense-in-depth for mutating methods. Non-loopback binds
require an explicit opt-in env var (see ``assert_loopback_bind_or_warn``).
"""

from __future__ import annotations

import ipaddress
import logging
import os
from typing import Iterable

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.types import ASGIApp

_UNSAFE_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})
_DEFAULT_TRUSTED_HOSTS = frozenset(
    {
        "127.0.0.1",
        "localhost",
        "::1",
        "[::1]",
        # Starlette/FastAPI TestClient default Host; not a network-reachable rebinding target.
        "testserver",
    }
)
_TEST_PEERS = frozenset({"testclient", "testserver"})
_ALLOW_NON_LOOPBACK_BIND_ENV = "HADES_ALLOW_NON_LOOPBACK_BIND"
_ALLOW_NON_LOOPBACK_CLIENTS_ENV = "HADES_ALLOW_NON_LOOPBACK_CLIENTS"
_BIND_HOST_ENV = "HADES_BIND_HOST"

logger = logging.getLogger("hades.local_api_trust")


def _normalize_host(value: str | None) -> str:
    raw = (value or "").strip().lower()
    if not raw:
        return ""
    # Strip optional port while preserving IPv6 bracket forms.
    if raw.startswith("["):
        end = raw.find("]")
        if end != -1:
            return raw[: end + 1]
    if raw.count(":") == 1:
        return raw.split(":", 1)[0]
    return raw


def _host_is_loopback(host: str) -> bool:
    normalized = _normalize_host(host).strip("[]")
    if not normalized:
        return False
    if normalized in {"localhost"} or normalized.endswith(".localhost"):
        return True
    try:
        return bool(ipaddress.ip_address(normalized.split("%", 1)[0]).is_loopback)
    except ValueError:
        return False


def _origin_host(origin: str) -> str:
    text = (origin or "").strip()
    if not text or text == "null":
        return ""
    # Origin is scheme://host[:port]
    without_scheme = text.split("://", 1)[-1]
    return _normalize_host(without_scheme.split("/", 1)[0])


def is_trusted_host(host: str, *, extra_trusted: Iterable[str] | None = None) -> bool:
    normalized = _normalize_host(host)
    if not normalized:
        return False
    trusted = set(_DEFAULT_TRUSTED_HOSTS)
    if extra_trusted:
        trusted.update(_normalize_host(item) for item in extra_trusted if item)
    if normalized in trusted:
        return True
    return _host_is_loopback(normalized)


def is_trusted_origin(origin: str, *, allowed_origins: Iterable[str] | None = None) -> bool:
    text = (origin or "").strip()
    if not text:
        return True  # non-browser / same-origin tooling without Origin
    if allowed_origins:
        allowed = {item.strip() for item in allowed_origins if str(item).strip()}
        if "*" in allowed or text in allowed:
            return True
    return _host_is_loopback(_origin_host(text))


def is_trusted_peer(peer_host: str | None, *, allow_non_loopback: bool | None = None) -> bool:
    """Return True when the TCP peer is loopback (or an explicit opt-in allows LAN)."""
    if allow_non_loopback is None:
        allow_non_loopback = _env_flag(_ALLOW_NON_LOOPBACK_CLIENTS_ENV)
    if allow_non_loopback:
        return True
    host = (peer_host or "").strip().lower()
    if not host:
        # ASGI servers without a client (some unit harnesses) — fail closed for
        # production-shaped requests; TestClient always supplies a peer.
        return False
    if host in _TEST_PEERS:
        return True
    return _host_is_loopback(host)


def _env_flag(name: str) -> bool:
    return os.environ.get(name, "").strip().lower() in {"1", "true", "yes", "on"}


def assert_loopback_bind_or_warn(*, bind_host: str | None = None) -> dict[str, object]:
    """Refuse or warn on non-loopback bind unless explicitly opted in.

    Returns a small status dict for health/diagnostics. Does not stop the
    process when opt-in is set — peer middleware still gates clients unless
    ``HADES_ALLOW_NON_LOOPBACK_CLIENTS`` is also set.
    """
    host = (bind_host if bind_host is not None else os.environ.get(_BIND_HOST_ENV, "127.0.0.1")) or "127.0.0.1"
    host = str(host).strip() or "127.0.0.1"
    allow_bind = _env_flag(_ALLOW_NON_LOOPBACK_BIND_ENV)
    loopback = _host_is_loopback(host) or host in {"localhost"}
    # 0.0.0.0 / :: are unspecified (all interfaces) — treat as non-loopback bind.
    if host in {"0.0.0.0", "::", "[::]"}:
        loopback = False
    if loopback:
        return {"bind_host": host, "loopback": True, "allowed": True, "warned": False}
    if not allow_bind:
        raise RuntimeError(
            f"Refusing non-loopback API bind host={host!r}. "
            f"Set {_ALLOW_NON_LOOPBACK_BIND_ENV}=1 to opt in (peer IP trust still applies)."
        )
    logger.warning(
        "Non-loopback API bind host=%s enabled via %s=1; "
        "LocalApiTrustMiddleware enforces loopback peer unless %s=1",
        host,
        _ALLOW_NON_LOOPBACK_BIND_ENV,
        _ALLOW_NON_LOOPBACK_CLIENTS_ENV,
    )
    return {"bind_host": host, "loopback": False, "allowed": True, "warned": True}


class LocalApiTrustMiddleware(BaseHTTPMiddleware):
    """Reject requests from non-loopback peers; Host/Origin defense for mutations."""

    def __init__(self, app: ASGIApp, *, allowed_origins: Iterable[str] | None = None) -> None:
        super().__init__(app)
        self.allowed_origins = list(allowed_origins or [])

    async def dispatch(self, request: Request, call_next) -> Response:
        peer = request.client.host if request.client else None
        if not is_trusted_peer(peer):
            return JSONResponse(
                status_code=403,
                content={"detail": "Untrusted peer rejected for local API access."},
            )
        if request.method.upper() in _UNSAFE_METHODS:
            host = request.headers.get("host") or ""
            if not is_trusted_host(host):
                return JSONResponse(
                    status_code=403,
                    content={"detail": "Untrusted Host rejected for local API mutation."},
                )
            origin = request.headers.get("origin") or ""
            if origin and not is_trusted_origin(origin, allowed_origins=self.allowed_origins):
                return JSONResponse(
                    status_code=403,
                    content={"detail": "Untrusted Origin rejected for local API mutation."},
                )
        return await call_next(request)
