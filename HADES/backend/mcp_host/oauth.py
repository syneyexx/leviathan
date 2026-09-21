"""MCP OAuth surface with rebinding-safe HTTP transport enforcement.

The protocol/PKCE/state implementation is retained byte-for-byte in
``oauth_legacy``. This module only replaces that module's private HTTPX client
factory, ensuring every metadata, probe, token-exchange and refresh connection
resolves and validates its destination at the actual TCP dial.
"""

from __future__ import annotations

from typing import Any

import httpx as _real_httpx

from mcp_host import oauth_legacy as _legacy
from secure_http_transport import create_safe_http_client


class _SafeHttpxFacade:
    """Delegate HTTPX APIs while hardening OAuth's Client constructor only."""

    def Client(self, *args: Any, **kwargs: Any) -> _real_httpx.Client:
        if args:
            # OAuth's implementation uses keyword construction. Refuse an
            # unexpected future call shape rather than silently bypass policy.
            raise TypeError("OAuth HTTP clients must use keyword arguments")
        if "transport" in kwargs:
            raise ValueError("Custom OAuth HTTP transports are not allowed")
        # URL validation in oauth_legacy still decides whether a loopback OAuth
        # endpoint is authorized. At connect time allow_loopback remains narrow:
        # it never weakens policy for an ordinary/public hostname.
        return create_safe_http_client(allow_loopback=True, **kwargs)

    def __getattr__(self, name: str) -> Any:
        return getattr(_real_httpx, name)


# Legacy function objects resolve their globals from oauth_legacy, so replacing
# only this module-local HTTPX reference secures all existing egress without a
# process-wide monkeypatch.
_legacy.httpx = _SafeHttpxFacade()

# Preserve the full existing API, including intentionally private helpers used
# by oauth_tokens.py and regression tests.
for _name, _value in vars(_legacy).items():
    if _name not in {"__name__", "__package__", "__loader__", "__spec__"}:
        globals()[_name] = _value
