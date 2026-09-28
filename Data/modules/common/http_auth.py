"""Central HTTP mutation authentication for LEVIATHAN control-plane routes.

Default local posture remains loopback-only (no token required).
When LOOPBACK_ONLY is false, every state-changing HTTP request must present
a matching operator token. Approval is not a substitute for caller auth.
"""

from __future__ import annotations

import hmac
import os
from typing import Any, Iterable

from starlette.requests import Request

OPERATOR_TOKEN_ENV = "LEVIATHAN_OPERATOR_TOKEN"
OPERATOR_TOKEN_HEADER = "x-leviathan-operator-token"
SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS", "TRACE"})

# Paths that remain reachable without operator auth even for non-safe methods
# when non-loopback (intentionally empty — default-deny mutations).
PUBLIC_MUTATION_PATH_PREFIXES: tuple[str, ...] = ()


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


def validate_non_loopback_security_posture(*, loopback_only: bool) -> None:
    """Hard-fail startup when non-loopback is enabled without operator credentials."""
    if loopback_only:
        return
    if not operator_token_configured():
        raise RuntimeError(
            f"LEVIATHAN_LOOPBACK_ONLY=false requires a non-empty {OPERATOR_TOKEN_ENV} "
            "so mutation routes can be authenticated. Refusing unsafe startup."
        )


def classify_http_methods(methods: Iterable[str] | None) -> dict[str, Any]:
    """Classify OpenAPI/route methods for architecture tests."""
    raw = {str(m).upper() for m in (methods or ())}
    mutating = sorted(m for m in raw if m not in SAFE_METHODS and m != "WEBSOCKET")
    return {
        "methods": sorted(raw),
        "mutating_methods": mutating,
        "requires_operator_auth_when_non_loopback": bool(mutating),
    }
