from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class VoiceAction(str, Enum):
    TRANSCRIBE = "TRANSCRIBE"
    SYNTHESIZE = "SYNTHESIZE"


class VoiceJobStatus(str, Enum):
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"
    UNSUPPORTED = "UNSUPPORTED"


@dataclass(frozen=True)
class VoiceJob:
    job_id: str
    action: VoiceAction
    status: VoiceJobStatus
    detail: str
    metadata: dict[str, Any] = field(default_factory=dict)

    def public_dict(self) -> dict[str, Any]:
        return {
            "job_id": self.job_id,
            "action": self.action.value,
            "status": self.status.value,
            "detail": self.detail,
            "metadata": self.metadata,
            "truth": {"no_fabricated_transcripts_or_audio": True},
        }


class VoiceRuntimeStub:
    """Honest stub — voice/ASR/TTS not implemented."""

    def request(self, *, action: VoiceAction, text: str | None = None) -> VoiceJob:
        import uuid

        if action == VoiceAction.SYNTHESIZE and not (text and text.strip()):
            return VoiceJob(
                job_id=str(uuid.uuid4()),
                action=action,
                status=VoiceJobStatus.REJECTED,
                detail="SYNTHESIZE requires text",
            )
        return VoiceJob(
            job_id=str(uuid.uuid4()),
            action=action,
            status=VoiceJobStatus.UNSUPPORTED,
            detail="Voice runtime is not implemented",
            metadata={"implemented": False},
        )
