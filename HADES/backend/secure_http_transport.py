"""HTTPX transport that binds SSRF DNS validation to the actual TCP dial.

Pre-request URL validation alone cannot prevent DNS rebinding: a hostile DNS
server may answer with a public address during validation and a private address
when the HTTP client resolves the same hostname again. This module resolves at
the HTTPCore TCP boundary, validates the complete answer set, and delegates the
socket connection using only numeric IP addresses. The original request origin
remains unchanged, so HTTP Host headers, TLS SNI, and certificate hostname
verification continue to use the requested hostname.
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

import httpcore
import httpx

# HADES runs the backend both as the ``backend`` package in tests/tools and with
# ``backend/`` on sys.path in the desktop runtime. Support both import modes so
# security callers never need to fall back to a different transport.
if __package__:
    from .url_security import resolve_safe_host_addresses
else:  # pragma: no cover - exercised by the desktop/backend entrypoint layout
    from url_security import resolve_safe_host_addresses


class SafeSyncNetworkBackend(httpcore.NetworkBackend):
    """Validate DNS at connect time and dial only validated numeric addresses."""

    def __init__(
        self,
        backend: httpcore.NetworkBackend | None = None,
        *,
        allow_private: bool = False,
        allow_loopback: bool = False,
    ) -> None:
        if allow_private and allow_loopback:
            raise ValueError("Choose allow_private or allow_loopback, not both")
        self._backend = backend or httpcore.SyncBackend()
        self._allow_private = bool(allow_private)
        self._allow_loopback = bool(allow_loopback)

    def connect_tcp(
        self,
        host: str,
        port: int,
        timeout: float | None = None,
        local_address: str | None = None,
        socket_options: Iterable[Any] | None = None,
    ) -> httpcore.NetworkStream:
        addresses = resolve_safe_host_addresses(
            host,
            port,
            allow_private=self._allow_private,
            allow_loopback=self._allow_loopback,
            purpose="HTTP connect",
        )

        # resolve_safe_host_addresses validates the complete result set before
        # returning. Only after that do we attempt numeric addresses in resolver
        # order, preserving normal multi-address fallback without giving the
        # delegate another attacker-controlled hostname to resolve.
        last_error: Exception | None = None
        for address in addresses:
            try:
                return self._backend.connect_tcp(
                    host=address,
                    port=port,
                    timeout=timeout,
                    local_address=local_address,
                    socket_options=socket_options,
                )
            except Exception as exc:
                last_error = exc
        if last_error is not None:
            raise last_error
        raise RuntimeError("Safe DNS resolution returned no dialable address")

    def connect_unix_socket(
        self,
        path: str,
        timeout: float | None = None,
        socket_options: Iterable[Any] | None = None,
    ) -> httpcore.NetworkStream:
        raise RuntimeError("UNIX sockets are not allowed by the rebinding-safe HTTP transport")

    def sleep(self, seconds: float) -> None:
        self._backend.sleep(seconds)


class RebindingSafeHTTPTransport(httpx.HTTPTransport):
    """HTTPX transport with fail-closed connect-time destination enforcement.

    HTTPX 0.28.x does not expose HTTPCore's network_backend parameter on
    HTTPTransport. HADES therefore replaces the backend of the direct
    ConnectionPool after construction. The shape is checked strictly; if a
    future dependency changes it, construction fails instead of silently
    falling back to unsafe hostname re-resolution.
    """

    def __init__(
        self,
        *,
        allow_private: bool = False,
        allow_loopback: bool = False,
        **kwargs: Any,
    ) -> None:
        if allow_private and allow_loopback:
            raise ValueError("Choose allow_private or allow_loopback, not both")
        if kwargs.get("proxy") is not None:
            raise ValueError("Proxies are not supported by the rebinding-safe HTTP transport")
        if kwargs.get("uds") is not None:
            raise ValueError("UNIX sockets are not supported by the rebinding-safe HTTP transport")

        # Environment CA configuration remains handled by HTTPX's verify
        # argument. Environment proxy discovery is deliberately disabled: a
        # proxy would move the TCP boundary away from the validated origin.
        kwargs["trust_env"] = False
        super().__init__(**kwargs)

        pool = getattr(self, "_pool", None)
        network_backend = getattr(pool, "_network_backend", None)
        if not isinstance(pool, httpcore.ConnectionPool) or network_backend is None:
            self.close()
            raise RuntimeError("Unsupported HTTPX/HTTPCore transport internals")

        pool._network_backend = SafeSyncNetworkBackend(
            network_backend,
            allow_private=allow_private,
            allow_loopback=allow_loopback,
        )


def create_safe_http_client(
    *,
    allow_private: bool = False,
    allow_loopback: bool = False,
    **client_kwargs: Any,
) -> httpx.Client:
    """Create a direct HTTPX client with DNS-rebinding-safe TCP connects.

    ``allow_loopback`` is the preferred local-service escape hatch. It only
    weakens destination policy for an explicitly loopback host. ``allow_private``
    is reserved for trusted private-network integrations and must never be used
    for arbitrary public URLs.
    """
    if allow_private and allow_loopback:
        raise ValueError("Choose allow_private or allow_loopback, not both")
    if "transport" in client_kwargs:
        raise ValueError("Custom transports are not accepted by create_safe_http_client")
    if client_kwargs.get("trust_env") not in (None, False):
        raise ValueError("Environment proxy settings are not allowed for safe HTTP clients")

    client_kwargs["trust_env"] = False
    client_kwargs["transport"] = RebindingSafeHTTPTransport(
        allow_private=allow_private,
        allow_loopback=allow_loopback,
    )
    return httpx.Client(**client_kwargs)
