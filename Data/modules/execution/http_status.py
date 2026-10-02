"""Shared HTTP status mapping for ExecutionGateway results.

Used by capability execute, skill execute, and any other surface that must not
treat REJECTED / FAILED / TIMEOUT / CANCELLED / APPROVAL_REQUIRED as HTTP 200.
"""

from __future__ import annotations

from .types import CapabilityStatus

# Terminal / non-success statuses → HTTP code. COMPLETED maps to None (caller uses 200).
_STATUS_HTTP: dict[str, int] = {
    CapabilityStatus.APPROVAL_REQUIRED.value: 403,
    CapabilityStatus.REJECTED.value: 422,
    CapabilityStatus.QUEUED.value: 202,
    CapabilityStatus.TIMEOUT.value: 504,
    CapabilityStatus.CANCELLED.value: 409,
    CapabilityStatus.FAILED.value: 500,
}


def gateway_status_http_code(
    status: CapabilityStatus | str,
    *,
    reject_reason: str | None = None,
) -> int | None:
    """Return non-200 HTTP code for a gateway status, or None when HTTP 200 is correct.

    When ``reject_reason`` is an approval-oriented rejection, prefer 403 over 422.
    """
    value = status.value if isinstance(status, CapabilityStatus) else str(status or "").upper()
    if value == CapabilityStatus.REJECTED.value and reject_reason in {
        "approval_required",
        "approval_denied",
        "approval_expired",
    }:
        return 403
    return _STATUS_HTTP.get(value)
