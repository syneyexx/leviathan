"""Central HTTP mutation authentication + Host-header allowlist for LEVIATHAN.

Default local posture remains loopback-only (no token required).
When LOOPBACK_ONLY is false, every state-changing HTTP request must present
a matching operator token. Approval is not a substitute for caller auth.

Host-header validation (TrustedHost) is fail-closed when non-loopback:
operators must set LEVIATHAN_TRUSTED_HOSTS. Wildcards are refused.
Loopback deployments keep localhost / 127.0.0.1 / ::1 (local launcher OK).
"""

from __future__ import annotations

import hmac
import os
from typing import Any, Iterable

from starlette.requests import Request

OPERATOR_TOKEN_ENV = "LEVIATHAN_OPERATOR_TOKEN"
OPERATOR_TOKEN_HEADER = "x-leviathan-operator-token"
TRUSTED_HOSTS_ENV = "LEVIATHAN_TRUSTED_HOSTS"
SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS", "TRACE"})

# Paths that remain reachable without operator auth even for non-safe methods
# when non-loopback (intentionally empty — default-deny mutations).
PUBLIC_MUTATION_PATH_PREFIXES: tuple[str, ...] = ()

# Local launcher / bind defaults. Never includes "*".
LOOPBACK_TRUSTED_HOSTS: tuple[str, ...] = ("127.0.0.1", "localhost", "::1")
# Starlette/FastAPI TestClient default Host — loopback-only only.
TESTCLIENT_HOST = "testserver"


class MutationAuthError(PermissionError):
    """Raised when a non-loopback mutation lacks a valid operator token."""

    def __init__(self, detail: str = "operator authentication required") -> None:
        super().__init__(detail)
        self.detail = detail
        self.status_code = 403


def read_expected_operator_token() -> str:
    return (os.environ.get(OPERATOR_TOKEN_ENV) or "").strip()


def operator_token_configured() -> bool:
    return bool(read_expected_operator_token())


def is_safe_method(method: str) -> bool:
    return method.upper() in SAFE_METHODS


def is_api_path(path: str) -> bool:
    return path.startswith("/api/")


def is_public_mutation_path(path: str) -> bool:
    return any(path == prefix or path.startswith(prefix) for prefix in PUBLIC_MUTATION_PATH_PREFIXES)


def mutation_requires_operator_auth(
    *,
    method: str,
    path: str,
    loopback_only: bool,
) -> bool:
    """Return True when this request must present a valid operator token."""
    if loopback_only:
        return False
    if not is_api_path(path):
        return False
    if is_safe_method(method):
        return False
    if is_public_mutation_path(path):
        return False
    return True


def tokens_match(provided: str, expected: str) -> bool:
    """Constant-time compare; empty expected never matches."""
    if not expected or not provided:
        return False
    return hmac.compare_digest(provided.encode("utf-8"), expected.encode("utf-8"))


def assert_operator_mutation_allowed(
    request: Request,
    *,
    loopback_only: bool,
) -> None:
    """Enforce operator token for non-loopback mutations. No-op on loopback."""
    path = request.url.path
    method = request.method
    if not mutation_requires_operator_auth(
        method=method, path=path, loopback_only=loopback_only
    ):
        return
    expected = read_expected_operator_token()
    provided = (request.headers.get(OPERATOR_TOKEN_HEADER) or "").strip()
    if not tokens_match(provided, expected):
        raise MutationAuthError(
            "Non-loopback host: state-changing API calls require matching "
            f"{OPERATOR_TOKEN_HEADER} (set {OPERATOR_TOKEN_ENV})"
        )


def parse_trusted_hosts(raw: str | None) -> list[str]:
    """Parse comma-separated Host allowlist. Rejects empty entries and '*'."""
    if not raw or not str(raw).strip():
        return []
    hosts: list[str] = []
    for part in str(raw).split(","):
        host = part.strip().lower()
        if not host:
            continue
        # Strip optional port for storage; TrustedHostMiddleware also strips port.
        if host.startswith("[") and "]" in host:
            # IPv6 literal e.g. [::1]:8765
            host = host[1 : host.index("]")]
        elif host.count(":") == 1 and not host.startswith("["):
            host = host.split(":", 1)[0]
        if host == "*":
            raise RuntimeError(
                f"{TRUSTED_HOSTS_ENV} must not contain '*' — Host allowlist is fail-closed"
            )
        if "*" in host:
            raise RuntimeError(
                f"{TRUSTED_HOSTS_ENV} refuses wildcard patterns ({host!r}); "
                "list exact hostnames only"
            )
        if host not in hosts:
            hosts.append(host)
    return hosts


def read_configured_trusted_hosts() -> list[str]:
    return parse_trusted_hosts(os.environ.get(TRUSTED_HOSTS_ENV))


def resolve_trusted_hosts(
    *,
    loopback_only: bool,
    bind_host: str = "127.0.0.1",
) -> list[str]:
    """Return the Host-header allowlist for TrustedHostMiddleware.

    Loopback: local launcher hosts + bind host + TestClient host.
    Non-loopback: fail-closed — requires explicit LEVIATHAN_TRUSTED_HOSTS (no '*').
    """
    configured = read_configured_trusted_hosts()
    bind = (bind_host or "").strip().lower()
    if bind.startswith("[") and "]" in bind:
        bind = bind[1 : bind.index("]")]
    elif bind.count(":") == 1:
        bind = bind.split(":", 1)[0]

    if loopback_only:
        hosts: list[str] = list(LOOPBACK_TRUSTED_HOSTS)
        if bind and bind not in hosts:
            hosts.append(bind)
        if TESTCLIENT_HOST not in hosts:
            hosts.append(TESTCLIENT_HOST)
        for host in configured:
            if host not in hosts:
                hosts.append(host)
        return hosts

    if not configured:
        raise RuntimeError(
            f"LEVIATHAN_LOOPBACK_ONLY=false requires a non-empty {TRUSTED_HOSTS_ENV} "
            "Host-header allowlist (comma-separated exact hosts). Refusing unsafe startup."
        )
    hosts = list(configured)
    if bind and bind not in hosts:
        hosts.append(bind)
    return hosts


def host_header_allowed(host_header: str | None, *, allowed_hosts: Iterable[str]) -> bool:
    """Match Starlette TrustedHostMiddleware host extraction (port stripped)."""
    if not host_header:
        return False
    host = host_header.strip().lower().split(":", 1)[0]
    if host.startswith("[") and "]" in host:
        host = host[1 : host.index("]")]
    allowed = {h.strip().lower() for h in allowed_hosts}
    return host in allowed


def validate_non_loopback_security_posture(
    *,
    loopback_only: bool,
    bind_host: str = "127.0.0.1",
) -> None:
    """Hard-fail startup when non-loopback lacks operator token or Host allowlist."""
    if loopback_only:
        # Still resolve so misconfigured wildcards in env fail early on loopback too.
        resolve_trusted_hosts(loopback_only=True, bind_host=bind_host)
        return
    if not operator_token_configured():
        raise RuntimeError(
            f"LEVIATHAN_LOOPBACK_ONLY=false requires a non-empty {OPERATOR_TOKEN_ENV} "
            "so mutation routes can be authenticated. Refusing unsafe startup."
        )
    resolve_trusted_hosts(loopback_only=False, bind_host=bind_host)


def classify_http_methods(methods: Iterable[str] | None) -> dict[str, Any]:
    """Classify OpenAPI/route methods for architecture tests."""
    raw = {str(m).upper() for m in (methods or ())}
    mutating = sorted(m for m in raw if m not in SAFE_METHODS and m != "WEBSOCKET")
    return {
        "methods": sorted(raw),
        "mutating_methods": mutating,
        "requires_operator_auth_when_non_loopback": bool(mutating),
    }
