"""Failure classification — do not blindly retry identical failures."""

from __future__ import annotations

from enum import Enum
from typing import Any


class FailureCategory(str, Enum):
    MISSING_INPUT = "missing_input"
    INVALID_ARGUMENTS = "invalid_arguments"
    PERMISSION_DENIED = "permission_denied"
    PROVIDER_FAILURE = "provider_failure"
    TIMEOUT = "timeout"
    CONTRADICTION = "contradiction"
    UNAVAILABLE_CAPABILITY = "unavailable_capability"
    UNSATISFIED_REQUIREMENT = "unsatisfied_requirement"
    CANCELLATION = "cancellation"
    LOOP = "loop"
    UNKNOWN = "unknown"


def classify_failure(
    *,
    error: str | None = None,
    observation_summary: str | None = None,
    payload: dict[str, Any] | None = None,
) -> FailureCategory:
    text = " ".join(
        str(x).lower()
        for x in (
            error or "",
            observation_summary or "",
            str((payload or {}).get("code") or ""),
            str((payload or {}).get("error") or ""),
        )
        if x
    )
    if not text.strip():
        return FailureCategory.UNKNOWN
    if any(t in text for t in ("cancel", "cancelled", "canceled")):
        return FailureCategory.CANCELLATION
    if any(t in text for t in ("timeout", "timed out", "deadline")):
        return FailureCategory.TIMEOUT
    if any(t in text for t in ("permission", "denied", "forbidden", "approval", "unauthorized")):
        return FailureCategory.PERMISSION_DENIED
    if any(t in text for t in ("missing", "required", "not specified", "need input")):
        return FailureCategory.MISSING_INPUT
    if any(t in text for t in ("invalid", "validation", "schema", "type error", "bad argument")):
        return FailureCategory.INVALID_ARGUMENTS
    if any(t in text for t in ("unavailable", "not found", "no handler", "unsupported")):
        return FailureCategory.UNAVAILABLE_CAPABILITY
    if any(t in text for t in ("contradict", "conflict", "inconsistent")):
        return FailureCategory.CONTRADICTION
    if any(t in text for t in ("provider", "llm", "model_", "http", "connection", "502", "503")):
        return FailureCategory.PROVIDER_FAILURE
    if any(t in text for t in ("unsatisfied", "criterion", "verification failed", "requirement")):
        return FailureCategory.UNSATISFIED_REQUIREMENT
    if "loop" in text:
        return FailureCategory.LOOP
    return FailureCategory.UNKNOWN


# Categories that must not be blindly retried with identical arguments.
NO_IDENTICAL_RETRY = frozenset(
    {
        FailureCategory.MISSING_INPUT,
        FailureCategory.INVALID_ARGUMENTS,
        FailureCategory.PERMISSION_DENIED,
        FailureCategory.UNAVAILABLE_CAPABILITY,
        FailureCategory.UNSATISFIED_REQUIREMENT,
        FailureCategory.CONTRADICTION,
    }
)


def should_blind_retry(category: FailureCategory) -> bool:
    return category not in NO_IDENTICAL_RETRY
