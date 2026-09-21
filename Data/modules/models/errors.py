"""Structured Model Control Plane errors."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class ModelControlError(Exception):
    code: str
    message: str
    provider_id: str | None = None
    model_id: str | None = None
    retryable: bool = False
    http_status: int = 400
    details: dict[str, Any] = field(default_factory=dict)

    def __str__(self) -> str:
        return f"{self.code}: {self.message}"

    def public_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "code": self.code,
            "message": self.message,
            "retryable": self.retryable,
        }
        if self.provider_id:
            payload["providerId"] = self.provider_id
        if self.model_id:
            payload["modelId"] = self.model_id
        if self.details:
            payload["details"] = dict(self.details)
        return payload


PROVIDER_OFFLINE = "PROVIDER_OFFLINE"
PROVIDER_AUTH_FAILED = "PROVIDER_AUTH_FAILED"
MODEL_NOT_FOUND = "MODEL_NOT_FOUND"
MODEL_LOAD_FAILED = "MODEL_LOAD_FAILED"
MODEL_UNLOAD_FAILED = "MODEL_UNLOAD_FAILED"
MODEL_DOWNLOAD_FAILED = "MODEL_DOWNLOAD_FAILED"
MODEL_INVALID = "MODEL_INVALID"
MODEL_UNSUPPORTED = "MODEL_UNSUPPORTED"
INSUFFICIENT_MEMORY = "INSUFFICIENT_MEMORY"
CAPABILITY_NOT_SUPPORTED = "CAPABILITY_NOT_SUPPORTED"
REQUEST_TIMEOUT = "REQUEST_TIMEOUT"
ROUTER_EXHAUSTED = "ROUTER_EXHAUSTED"
CAPACITY_TIMEOUT = "CAPACITY_TIMEOUT"
PROVIDER_NOT_FOUND = "PROVIDER_NOT_FOUND"
UNSAFE_PATH = "UNSAFE_PATH"
VALIDATION_ERROR = "VALIDATION_ERROR"
OPERATION_CONFLICT = "OPERATION_CONFLICT"
DOWNLOAD_CANCELLED = "DOWNLOAD_CANCELLED"
NETWORK_BLOCKED = "NETWORK_BLOCKED"
