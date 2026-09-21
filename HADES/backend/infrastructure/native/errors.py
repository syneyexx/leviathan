"""Native bridge errors — mapped into the unified HADES taxonomy."""

from __future__ import annotations

from typing import Any

from errors.taxonomy import ErrorCode, normalize_error_code


class NativeRuntimeError(RuntimeError):
    def __init__(self, code: str, message: str, details: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.details = details or {}
        self.taxonomy_code: ErrorCode = normalize_error_code(code)

    def as_dict(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "message": self.message,
            "details": self.details,
            "taxonomy_code": self.taxonomy_code.value,
            "retryable": self.taxonomy_code
            in {
                ErrorCode.TIMEOUT,
                ErrorCode.DEADLINE_EXCEEDED,
                ErrorCode.OVERLOADED,
                ErrorCode.QUEUE_FULL,
                ErrorCode.NATIVE_UNAVAILABLE,
            },
        }
