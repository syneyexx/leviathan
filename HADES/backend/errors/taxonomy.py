"""HADES error taxonomy — stable codes across API, native, and UI.

User-facing responses should use these codes. Raw stack traces stay in local logs only.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class ErrorCode(str, Enum):
    VALIDATION_ERROR = "VALIDATION_ERROR"
    NOT_FOUND = "NOT_FOUND"
    CONFLICT = "CONFLICT"
    PERMISSION_DENIED = "PERMISSION_DENIED"
    POLICY_DENIED = "POLICY_DENIED"
    TIMEOUT = "TIMEOUT"
    DEADLINE_EXCEEDED = "DEADLINE_EXCEEDED"
    CANCELLED = "CANCELLED"
    OVERLOADED = "OVERLOADED"
    QUEUE_FULL = "QUEUE_FULL"
    DEPENDENCY_UNAVAILABLE = "DEPENDENCY_UNAVAILABLE"
    MODEL_UNAVAILABLE = "MODEL_UNAVAILABLE"
    NATIVE_UNAVAILABLE = "NATIVE_UNAVAILABLE"
    PLUGIN_FAILURE = "PLUGIN_FAILURE"
    EXECUTION_FAILED = "EXECUTION_FAILED"
    VERIFICATION_FAILED = "VERIFICATION_FAILED"
    INTERNAL_ERROR = "INTERNAL_ERROR"
    SHUTTING_DOWN = "SHUTTING_DOWN"


# Native protocol codes mapped into the unified taxonomy where they differ by name.
_NATIVE_ALIAS = {
    "INVALID_REQUEST": ErrorCode.VALIDATION_ERROR,
    "INVALID_PARAMS": ErrorCode.VALIDATION_ERROR,
    "UNSUPPORTED_VERSION": ErrorCode.VALIDATION_ERROR,
    "UNSUPPORTED_PROTOCOL": ErrorCode.VALIDATION_ERROR,
    "PARSE_ERROR": ErrorCode.VALIDATION_ERROR,
    "UNKNOWN_METHOD": ErrorCode.NOT_FOUND,
    "TIMEOUT": ErrorCode.TIMEOUT,
    "DEADLINE_EXCEEDED": ErrorCode.DEADLINE_EXCEEDED,
    "CANCELLED": ErrorCode.CANCELLED,
    "OVERLOADED": ErrorCode.OVERLOADED,
    "QUEUE_FULL": ErrorCode.QUEUE_FULL,
    "SHUTTING_DOWN": ErrorCode.SHUTTING_DOWN,
    "NATIVE_UNAVAILABLE": ErrorCode.NATIVE_UNAVAILABLE,
    "EXECUTABLE_NOT_FOUND": ErrorCode.NATIVE_UNAVAILABLE,
    "PROCESS_START_FAILED": ErrorCode.EXECUTION_FAILED,
    "RUNTIME_ERROR": ErrorCode.EXECUTION_FAILED,
    "INTERNAL_ERROR": ErrorCode.INTERNAL_ERROR,
    "OUTPUT_LIMIT": ErrorCode.VALIDATION_ERROR,
    "ACCESS_DENIED": ErrorCode.PERMISSION_DENIED,
}


RETRYABLE = {
    ErrorCode.TIMEOUT,
    ErrorCode.DEADLINE_EXCEEDED,
    ErrorCode.OVERLOADED,
    ErrorCode.QUEUE_FULL,
    ErrorCode.DEPENDENCY_UNAVAILABLE,
    ErrorCode.MODEL_UNAVAILABLE,
    ErrorCode.NATIVE_UNAVAILABLE,
}

USER_ACTION_REQUIRED = {
    ErrorCode.VALIDATION_ERROR,
    ErrorCode.PERMISSION_DENIED,
    ErrorCode.POLICY_DENIED,
    ErrorCode.NOT_FOUND,
}

PERMISSION_REQUIRED = {
    ErrorCode.PERMISSION_DENIED,
    ErrorCode.POLICY_DENIED,
}


@dataclass
class HadesError(Exception):
    code: ErrorCode
    message: str
    details: dict[str, Any] = field(default_factory=dict)
    retryable: bool | None = None
    trace_id: str | None = None
    request_id: str | None = None

    def __post_init__(self) -> None:
        if self.retryable is None:
            self.retryable = self.code in RETRYABLE
        Exception.__init__(self, self.message)

    def as_dict(self) -> dict[str, Any]:
        body: dict[str, Any] = {
            "code": self.code.value,
            "message": self.message,
            "details": dict(self.details),
            "retryable": bool(self.retryable),
            "user_action_required": self.code in USER_ACTION_REQUIRED,
            "permission_required": self.code in PERMISSION_REQUIRED,
            "cancelled": self.code == ErrorCode.CANCELLED,
            "permanent": self.code in {ErrorCode.VALIDATION_ERROR, ErrorCode.NOT_FOUND, ErrorCode.INTERNAL_ERROR}
            and self.code not in RETRYABLE,
        }
        if self.trace_id:
            body["trace_id"] = self.trace_id
        if self.request_id:
            body["request_id"] = self.request_id
        return body

    def http_status(self) -> int:
        mapping = {
            ErrorCode.VALIDATION_ERROR: 400,
            ErrorCode.NOT_FOUND: 404,
            ErrorCode.CONFLICT: 409,
            ErrorCode.PERMISSION_DENIED: 403,
            ErrorCode.POLICY_DENIED: 403,
            ErrorCode.TIMEOUT: 504,
            ErrorCode.DEADLINE_EXCEEDED: 504,
            ErrorCode.CANCELLED: 499,
            ErrorCode.OVERLOADED: 503,
            ErrorCode.QUEUE_FULL: 503,
            ErrorCode.DEPENDENCY_UNAVAILABLE: 503,
            ErrorCode.MODEL_UNAVAILABLE: 503,
            ErrorCode.NATIVE_UNAVAILABLE: 503,
            ErrorCode.PLUGIN_FAILURE: 502,
            ErrorCode.EXECUTION_FAILED: 502,
            ErrorCode.VERIFICATION_FAILED: 422,
            ErrorCode.INTERNAL_ERROR: 500,
            ErrorCode.SHUTTING_DOWN: 503,
        }
        return mapping.get(self.code, 500)


def normalize_error_code(raw: str | None) -> ErrorCode:
    if not raw:
        return ErrorCode.INTERNAL_ERROR
    text = str(raw).strip().upper()
    if text in _NATIVE_ALIAS:
        return _NATIVE_ALIAS[text]
    try:
        return ErrorCode(text)
    except ValueError:
        return ErrorCode.INTERNAL_ERROR


def from_native_error(code: str, message: str, details: dict[str, Any] | None = None) -> HadesError:
    return HadesError(code=normalize_error_code(code), message=message, details=details or {})
