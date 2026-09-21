"""Shared voice exceptions (no heavy imports)."""

from __future__ import annotations

from typing import Any


class VoiceProviderError(Exception):
    """Structured provider failure with a recoverable hint when possible."""

    def __init__(self, code: str, message: str, *, recovery: str | None = None, details: dict[str, Any] | None = None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.recovery = recovery
        self.details = details or {}

    def to_dict(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "message": self.message,
            "recovery": self.recovery,
            "details": self.details,
        }
