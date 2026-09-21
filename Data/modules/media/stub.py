from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class MediaAction(str, Enum):
    TRANSCODE = "TRANSCODE"
    THUMBNAIL = "THUMBNAIL"
    PROBE = "PROBE"


class MediaJobStatus(str, Enum):
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"
    UNSUPPORTED = "UNSUPPORTED"


@dataclass(frozen=True)
class MediaJob:
    job_id: str
    action: MediaAction
    status: MediaJobStatus
    path: str | None
    detail: str
    metadata: dict[str, Any] = field(default_factory=dict)

    def public_dict(self) -> dict[str, Any]:
        return {
            "job_id": self.job_id,
            "action": self.action.value,
            "status": self.status.value,
            "path": self.path,
            "detail": self.detail,
            "metadata": self.metadata,
            "truth": {"no_fabricated_media_output": True},
        }


class MediaAutomationStub:
    """Honest stub — media pipelines are not implemented."""

    def request(self, *, action: MediaAction, path: str | None = None) -> MediaJob:
        import uuid

        if not path:
            return MediaJob(
                job_id=str(uuid.uuid4()),
                action=action,
                status=MediaJobStatus.REJECTED,
                path=path,
                detail="path required",
            )
        return MediaJob(
            job_id=str(uuid.uuid4()),
            action=action,
            status=MediaJobStatus.UNSUPPORTED,
            path=path,
            detail="Media automation runtime is not implemented",
            metadata={"implemented": False},
        )
