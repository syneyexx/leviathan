"""Structured model-download errors — prefer existing model error code strings."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from Data.modules.common.secrets import redact_secrets


class ModelDownloadErrorCode(str, Enum):
    MODEL_DOWNLOAD_FAILED = "MODEL_DOWNLOAD_FAILED"
    MODEL_DOWNLOAD_CANCELLED = "DOWNLOAD_CANCELLED"
    MODEL_DOWNLOAD_STORAGE_FULL = "MODEL_DOWNLOAD_STORAGE_FULL"
    MODEL_DOWNLOAD_VERIFICATION_FAILED = "MODEL_DOWNLOAD_VERIFICATION_FAILED"
    MODEL_DOWNLOAD_SOURCE_UNAVAILABLE = "MODEL_DOWNLOAD_SOURCE_UNAVAILABLE"
    MODEL_DOWNLOAD_EXECUTION_UNAVAILABLE = "MODEL_DOWNLOAD_EXECUTION_UNAVAILABLE"
    NETWORK_BLOCKED = "NETWORK_BLOCKED"
    UNSAFE_PATH = "UNSAFE_PATH"
    VALIDATION_ERROR = "VALIDATION_ERROR"
    UNKNOWN = "MODEL_DOWNLOAD_UNKNOWN"


@dataclass
class ModelDownloadError(Exception):
    code: ModelDownloadErrorCode
    message: str
    retryable: bool = False
    http_status: int = 400
    details: dict[str, Any] = field(default_factory=dict)

    def __str__(self) -> str:
        return f"{self.code.value}: {redact_secrets(self.message)}"

    def public_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "code": self.code.value,
            "message": redact_secrets(self.message),
            "retryable": self.retryable,
        }
        if self.details:
            payload["details"] = {
                str(k): redact_secrets(str(v)) if isinstance(v, str) else v
                for k, v in self.details.items()
            }
        return payload
