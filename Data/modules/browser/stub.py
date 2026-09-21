from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class BrowserAction(str, Enum):
    NAVIGATE = "NAVIGATE"
    SCREENSHOT = "SCREENSHOT"
    EXTRACT_TEXT = "EXTRACT_TEXT"


class BrowserJobStatus(str, Enum):
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"
    UNSUPPORTED = "UNSUPPORTED"


@dataclass(frozen=True)
class BrowserJob:
    job_id: str
    action: BrowserAction
    status: BrowserJobStatus
    url: str | None
    detail: str
    metadata: dict[str, Any] = field(default_factory=dict)

    def public_dict(self) -> dict[str, Any]:
        return {
            "job_id": self.job_id,
            "action": self.action.value,
            "status": self.status.value,
            "url": self.url,
            "detail": self.detail,
            "metadata": self.metadata,
            "truth": {
                "no_fabricated_browser_results": True,
                "requires_capability_gateway_when_implemented": True,
            },
        }


class BrowserAutomationStub:
    """Honest stub — browser automation runtime is not implemented."""

    def request(self, *, action: BrowserAction, url: str | None = None) -> BrowserJob:
        import uuid

        if action == BrowserAction.NAVIGATE and not url:
            return BrowserJob(
                job_id=str(uuid.uuid4()),
                action=action,
                status=BrowserJobStatus.REJECTED,
                url=url,
                detail="NAVIGATE requires url",
            )
        return BrowserJob(
            job_id=str(uuid.uuid4()),
            action=action,
            status=BrowserJobStatus.UNSUPPORTED,
            url=url,
            detail="Browser automation runtime is not implemented",
            metadata={"implemented": False},
        )
