"""Public MCP transport clients with transport-boundary hardening.

The protocol implementation is retained in ``clients_legacy``. This module
re-exports that implementation and replaces only security-sensitive transport
boundaries:
- stdio children inherit non-secret host runtime variables plus only the
  per-server environment explicitly supplied by the MCP manager;
- HTTP clients bind URL/DNS validation to the actual socket connection.
"""

from __future__ import annotations

import os
import subprocess
import threading
from typing import Any
from urllib.parse import urlparse

from mcp_host import clients_legacy as _legacy
from secure_http_transport import create_safe_http_client
from url_security import UrlSecurityError, assert_public_http_url, safe_public_url

# Preserve the complete public/internal surface of the existing module. HADES
# has older tests and integrations that import helpers directly from clients.py;
# the hardening layer must not silently remove them.
for _name, _value in vars(_legacy).items():
    if _name not in {"__name__", "__package__", "__loader__", "__spec__"}:
        globals()[_name] = _value


# Ambient process credentials must never be exposed to an arbitrary stdio MCP
# server merely because HADES itself has them. The manager already constructs a
# per-server env map (including only that server's keyring-backed secret refs),
# so explicit env supplied to StdioMcpClient is the only secret re-entry path.
_AMBIENT_SECRET_ENV_EXACT = frozenset(
    {
        "ANTHROPIC_API_KEY",
        "AWS_ACCESS_KEY_ID",
        "AWS_SECRET_ACCESS_KEY",
        "AWS_SESSION_TOKEN",
        "AZURE_CLIENT_SECRET",
        "COMPOSIO_API_KEY",
        "FINCEPT_API_KEY",
        "FINCEPT_SESSION_TOKEN",
        "GH_TOKEN",
        "GITHUB_TOKEN",
        "HADES_LM_STUDIO_API_KEY",
        "NPM_TOKEN",
        "OPENAI_API_KEY",
        "SSH_AGENT_PID",
        "SSH_AUTH_SOCK",
    }
)
_AMBIENT_SECRET_ENV_SUFFIXES = (
    "_API_KEY",
    "_ACCESS_TOKEN",
    "_AUTH_TOKEN",
    "_BEARER_TOKEN",
    "_CLIENT_SECRET",
    "_PRIVATE_KEY",
    "_PASSWORD",
    "_SECRET",
    "_TOKEN",
)


def is_sensitive_stdio_env_key(key: str) -> bool:
    """Return whether an ambient env key is credential-shaped."""

    upper = str(key or "").strip().upper()
    return bool(
        upper
        and (
            upper in _AMBIENT_SECRET_ENV_EXACT
            or any(upper.endswith(suffix) for suffix in _AMBIENT_SECRET_ENV_SUFFIXES)
        )
    )


def build_stdio_child_environment(
    explicit: dict[str, str] | None = None,
    *,
    ambient: dict[str, str] | None = None,
) -> dict[str, str]:
    """Build an MCP stdio child env without leaking unrelated host secrets.

    Non-secret ambient variables such as PATH, SYSTEMROOT, TEMP, proxy settings,
    locale and user-home paths are preserved for normal CLI compatibility. Secret
    shaped ambient variables are stripped. ``explicit`` is trusted only as the
    manager-selected per-server environment and is applied last so that a server
    can still receive its own configured/keyring-backed credential.
    """

    source = dict(os.environ if ambient is None else ambient)
    child = {
        str(key): str(value)
        for key, value in source.items()
        if not is_sensitive_stdio_env_key(str(key))
    }
    child.update({str(key): str(value) for key, value in (explicit or {}).items()})
    return child


_LegacyStdioMcpClient = _legacy.StdioMcpClient


class StdioMcpClient(_LegacyStdioMcpClient):
    """Legacy stdio protocol implementation with per-server env isolation."""

    def _spawn_process(self) -> None:
        # ``_env`` is the manager-selected server env. Never use the legacy
        # ``_merged_env`` here: legacy builds it from ``os.environ.copy()`` and
        # would disclose unrelated HADES/host credentials to the MCP child.
        child_env = build_stdio_child_environment(getattr(self, "_env", {}))
        self._merged_env = child_env
        self.proc = subprocess.Popen(
            self.command,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            bufsize=1,
            shell=False,
            env=child_env,
            cwd=self._cwd or None,
            creationflags=self._creationflags,
            preexec_fn=self._preexec_fn,
        )
        self._stderr_chunks = []
        self._stderr_thread = threading.Thread(target=self._pump_stderr, daemon=True)
        self._stderr_thread.start()
        self._reader_thread = threading.Thread(target=self._pump_stdout, daemon=True)
        self._reader_thread.start()


_LegacyHttpMcpClient = _legacy.HttpMcpClient


class HttpMcpClient(_LegacyHttpMcpClient):
    """Existing MCP HTTP client with DNS validation bound to the TCP dial."""

    def __init__(
        self,
        endpoint_url: str,
        *,
        headers: dict[str, str] | None = None,
        bearer_token: str | None = None,
        timeout: float = 60.0,
        allow_private: bool = False,
    ) -> None:
        super().__init__(
            endpoint_url,
            headers=headers,
            bearer_token=bearer_token,
            timeout=timeout,
            allow_private=allow_private,
        )
        previous_client = self._client
        try:
            self._client = create_safe_http_client(
                timeout=self.timeout,
                follow_redirects=False,
                # Historical ``allow_private`` on MCP was already limited by
                # endpoint validation to explicit localhost/loopback hosts.
                # Keep that API contract while enforcing the narrower policy at
                # the actual socket connection boundary.
                allow_loopback=self.allow_private,
            )
        except Exception:
            try:
                previous_client.close()
            finally:
                raise
        previous_client.close()

    def _validate_url(self, url: str) -> str:
        raw = (url or "").strip()
        parsed = urlparse(raw)
        host = (parsed.hostname or "").lower().strip("[]")
        local = _legacy._is_explicit_loopback_host(host)
        if local and not self.allow_private:
            raise _legacy.McpClientError(
                "Loopback MCP endpoint requires explicit local permission",
                kind="validation",
            )
        try:
            assert_public_http_url(
                raw,
                allow_loopback=bool(local and self.allow_private),
                purpose="mcp_http",
            )
        except UrlSecurityError as exc:
            raise _legacy.McpClientError(str(exc), kind="validation") from exc
        return raw

    def _validated_redirect_target(self, current_url: str, location: str) -> str:
        """Revalidate every hop and never weaken public hosts to private ranges."""
        safe = safe_public_url(
            location,
            base=current_url,
            # safe_public_url only applies this exception when the final target
            # is explicitly loopback, so a public hostname cannot rebind into it.
            allow_loopback=self.allow_private,
        )
        if not safe:
            raise _legacy.McpClientError(
                f"Redirect blocked by network policy: {location}",
                kind="auth",
            )
        if _legacy._url_origin(safe) != self._endpoint_origin:
            raise _legacy.McpClientError(
                "Cross-origin MCP redirect blocked to protect credentials",
                kind="auth",
            )
        return safe
