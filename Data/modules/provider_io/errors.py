"""Normalized provider execution errors — reuse MCP/model codes where they match."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from Data.modules.common.secrets import redact_secrets


class ProviderErrorCode(str, Enum):
    PROVIDER_AUTH_FAILED = "PROVIDER_AUTH_FAILED"
    PROVIDER_RATE_LIMITED = "PROVIDER_RATE_LIMITED"
    PROVIDER_TIMEOUT = "PROVIDER_TIMEOUT"
    PROVIDER_UNAVAILABLE = "PROVIDER_UNAVAILABLE"
    PROVIDER_INVALID_REQUEST = "PROVIDER_INVALID_REQUEST"
    PROVIDER_MODEL_UNAVAILABLE = "PROVIDER_MODEL_UNAVAILABLE"
    PROVIDER_STREAM_INTERRUPTED = "PROVIDER_STREAM_INTERRUPTED"
    PROVIDER_RESPONSE_INVALID = "PROVIDER_RESPONSE_INVALID"
    PROVIDER_CIRCUIT_OPEN = "PROVIDER_CIRCUIT_OPEN"
    PROVIDER_NOT_CONFIGURED = "PROVIDER_NOT_CONFIGURED"
    EXECUTION_CANCELLED = "EXECUTION_CANCELLED"
    EXECUTION_CAPACITY_EXHAUSTED = "EXECUTION_CAPACITY_EXHAUSTED"
    EXECUTION_DEADLINE_EXCEEDED = "EXECUTION_DEADLINE_EXCEEDED"
    PROVIDER_EXECUTION_UNAVAILABLE = "PROVIDER_EXECUTION_UNAVAILABLE"
    SSRF_BLOCKED = "SSRF_BLOCKED"
    PAYLOAD_TOO_LARGE = "PAYLOAD_TOO_LARGE"
    NETWORK_BLOCKED = "NETWORK_BLOCKED"
    UNKNOWN = "PROVIDER_UNKNOWN"


# Errors that are normally safe to retry before semantic output begins.
RETRYABLE_CODES: frozenset[ProviderErrorCode] = frozenset(
    {
        ProviderErrorCode.PROVIDER_RATE_LIMITED,
        ProviderErrorCode.PROVIDER_TIMEOUT,
        ProviderErrorCode.PROVIDER_UNAVAILABLE,
        ProviderErrorCode.PROVIDER_STREAM_INTERRUPTED,
        ProviderErrorCode.EXECUTION_DEADLINE_EXCEEDED,  # only when budget remains
    }
)


@dataclass
class ProviderError(Exception):
    code: ProviderErrorCode
    message: str
    provider: str | None = None
    model: str | None = None
    retryable: bool = False
    http_status: int | None = None
    retry_after_seconds: float | None = None
    attempt: int = 0
    details: dict[str, Any] = field(default_factory=dict)

    def __str__(self) -> str:
        return f"{self.code.value}: {redact_secrets(self.message)}"

    def public_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "code": self.code.value,
            "message": redact_secrets(self.message),
            "retryable": self.retryable,
            "attempt": self.attempt,
        }
        if self.provider:
            payload["provider"] = self.provider
        if self.model:
            payload["model"] = self.model
        if self.http_status is not None:
            payload["http_status"] = self.http_status
        if self.retry_after_seconds is not None:
            payload["retry_after_seconds"] = self.retry_after_seconds
        if self.details:
            safe = {
                str(k): redact_secrets(str(v)) if isinstance(v, str) else v
                for k, v in self.details.items()
            }
            payload["details"] = safe
        return payload


def classify_http_status(
    status: int,
    *,
    body_snippet: str = "",
    retry_after: float | None = None,
) -> ProviderError:
    """Map HTTP status to a normalized provider error."""
    snippet = redact_secrets((body_snippet or "")[:500])
    if status in (401, 403):
        return ProviderError(
            ProviderErrorCode.PROVIDER_AUTH_FAILED,
            f"Provider authentication failed (HTTP {status})",
            retryable=False,
            http_status=status,
            details={"body": snippet},
        )
    if status == 404:
        return ProviderError(
            ProviderErrorCode.PROVIDER_MODEL_UNAVAILABLE,
            f"Provider resource not found (HTTP {status})",
            retryable=False,
            http_status=status,
            details={"body": snippet},
        )
    if status == 429:
        return ProviderError(
            ProviderErrorCode.PROVIDER_RATE_LIMITED,
            f"Provider rate limited (HTTP {status})",
            retryable=True,
            http_status=status,
            retry_after_seconds=retry_after,
            details={"body": snippet},
        )
    if status == 400 or status == 422:
        return ProviderError(
            ProviderErrorCode.PROVIDER_INVALID_REQUEST,
            f"Provider rejected request (HTTP {status})",
            retryable=False,
            http_status=status,
            details={"body": snippet},
        )
    if 500 <= status <= 599:
        return ProviderError(
            ProviderErrorCode.PROVIDER_UNAVAILABLE,
            f"Provider upstream error (HTTP {status})",
            retryable=True,
            http_status=status,
            retry_after_seconds=retry_after,
            details={"body": snippet},
        )
    return ProviderError(
        ProviderErrorCode.PROVIDER_RESPONSE_INVALID,
        f"Unexpected provider status (HTTP {status})",
        retryable=False,
        http_status=status,
        details={"body": snippet},
    )
