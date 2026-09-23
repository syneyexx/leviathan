"""Unified multimodal message schema (U241, U253, U257)."""

from __future__ import annotations

import hashlib
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def new_sync_id() -> str:
    return f"sync_{uuid.uuid4().hex[:12]}"


class PartKind(str, Enum):
    TEXT = "text"
    IMAGE = "image"
    AUDIO = "audio"
    VIDEO = "video"
    FILE = "file"
    REGION = "region"
    TIMESPAN = "timespan"


@dataclass(frozen=True)
class MultimodalPart:
    """One typed part of a multimodal message."""

    part_id: str
    kind: PartKind
    mime_type: str
    content_hash: str | None = None
    text: str | None = None
    artifact_id: str | None = None
    uri: str | None = None
    width: int | None = None
    height: int | None = None
    duration_ms: float | None = None
    # Region (U243) — crop/tile within an image/video frame
    region: dict[str, Any] | None = None  # {x,y,w,h,parent_part_id}
    # Timespan (U247/U254) — audio/video span
    timespan: dict[str, Any] | None = None  # {start_ms,end_ms,parent_part_id}
    provenance: dict[str, Any] = field(default_factory=dict)
    scope: str = "conversation"  # conversation | project | run | agent_private
    sync_id: str | None = None

    def public_dict(self) -> dict[str, Any]:
        return {
            "part_id": self.part_id,
            "kind": self.kind.value,
            "mime_type": self.mime_type,
            "content_hash": self.content_hash,
            "text": self.text,
            "artifact_id": self.artifact_id,
            "uri": self.uri,
            "width": self.width,
            "height": self.height,
            "duration_ms": self.duration_ms,
            "region": dict(self.region) if self.region else None,
            "timespan": dict(self.timespan) if self.timespan else None,
            "provenance": dict(self.provenance),
            "scope": self.scope,
            "sync_id": self.sync_id,
            "truth": {
                "part_is_data_not_authority": True,
                "provider_restrictions_are_provider_behavior": True,
            },
        }

    @classmethod
    def text_part(
        cls,
        text: str,
        *,
        sync_id: str | None = None,
        scope: str = "conversation",
    ) -> "MultimodalPart":
        raw = text.encode("utf-8")
        return cls(
            part_id=f"part_{uuid.uuid4().hex[:10]}",
            kind=PartKind.TEXT,
            mime_type="text/plain",
            content_hash=hashlib.sha256(raw).hexdigest()[:16],
            text=text,
            sync_id=sync_id,
            scope=scope,
        )

    @classmethod
    def image_part(
        cls,
        *,
        mime_type: str = "image/png",
        artifact_id: str | None = None,
        uri: str | None = None,
        content_hash: str | None = None,
        width: int | None = None,
        height: int | None = None,
        sync_id: str | None = None,
        region: dict[str, Any] | None = None,
        provenance: dict[str, Any] | None = None,
        scope: str = "conversation",
    ) -> "MultimodalPart":
        return cls(
            part_id=f"part_{uuid.uuid4().hex[:10]}",
            kind=PartKind.REGION if region else PartKind.IMAGE,
            mime_type=mime_type,
            content_hash=content_hash,
            artifact_id=artifact_id,
            uri=uri,
            width=width,
            height=height,
            region=region,
            sync_id=sync_id,
            provenance=dict(provenance or {}),
            scope=scope,
        )

    @classmethod
    def audio_part(
        cls,
        *,
        mime_type: str = "audio/wav",
        artifact_id: str | None = None,
        duration_ms: float | None = None,
        sync_id: str | None = None,
        timespan: dict[str, Any] | None = None,
        text: str | None = None,
        provenance: dict[str, Any] | None = None,
        scope: str = "conversation",
    ) -> "MultimodalPart":
        return cls(
            part_id=f"part_{uuid.uuid4().hex[:10]}",
            kind=PartKind.TIMESPAN if timespan else PartKind.AUDIO,
            mime_type=mime_type,
            artifact_id=artifact_id,
            duration_ms=duration_ms,
            timespan=timespan,
            text=text,
            sync_id=sync_id,
            provenance=dict(provenance or {}),
            scope=scope,
        )


@dataclass
class MultimodalMessage:
    message_id: str
    role: str
    parts: list[MultimodalPart]
    created_at: str = field(default_factory=_utc_now)
    run_id: str | None = None
    conversation_id: str | None = None
    sync_id: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def public_dict(self) -> dict[str, Any]:
        return {
            "message_id": self.message_id,
            "role": self.role,
            "parts": [p.public_dict() for p in self.parts],
            "created_at": self.created_at,
            "run_id": self.run_id,
            "conversation_id": self.conversation_id,
            "sync_id": self.sync_id,
            "metadata": dict(self.metadata),
            "truth": {
                "same_conversation_project_context_model": True,
                "no_parallel_voice_memory": True,
            },
        }

    def as_history_dict(self) -> dict[str, Any]:
        """Flatten for ContextBuilder while preserving multimodal provenance."""
        texts = [p.text for p in self.parts if p.kind == PartKind.TEXT and p.text]
        content = "\n".join(texts) if texts else f"[{len(self.parts)} multimodal parts]"
        return {
            "role": self.role,
            "content": content,
            "message_id": self.message_id,
            "sync_id": self.sync_id,
            "parts": [p.public_dict() for p in self.parts],
            "run_id": self.run_id,
            "conversation_id": self.conversation_id,
        }


@dataclass
class MultimodalSession:
    """Project/conversation session that fuses text + images + audio (U253/U257)."""

    session_id: str
    conversation_id: str | None = None
    run_id: str | None = None
    project_id: str | None = None
    messages: list[MultimodalMessage] = field(default_factory=list)
    created_at: str = field(default_factory=_utc_now)
    metadata: dict[str, Any] = field(default_factory=dict)

    def append(
        self,
        role: str,
        parts: list[MultimodalPart],
        *,
        sync_id: str | None = None,
    ) -> MultimodalMessage:
        sid = sync_id or new_sync_id()
        normalized = [
            MultimodalPart(
                part_id=p.part_id,
                kind=p.kind,
                mime_type=p.mime_type,
                content_hash=p.content_hash,
                text=p.text,
                artifact_id=p.artifact_id,
                uri=p.uri,
                width=p.width,
                height=p.height,
                duration_ms=p.duration_ms,
                region=p.region,
                timespan=p.timespan,
                provenance=dict(p.provenance),
                scope=p.scope,
                sync_id=p.sync_id or sid,
            )
            for p in parts
        ]
        msg = MultimodalMessage(
            message_id=f"msg_{uuid.uuid4().hex[:12]}",
            role=role,
            parts=normalized,
            run_id=self.run_id,
            conversation_id=self.conversation_id,
            sync_id=sid,
        )
        self.messages.append(msg)
        return msg

    def history_for_context(self) -> list[dict[str, Any]]:
        return [m.as_history_dict() for m in self.messages]

    def public_dict(self) -> dict[str, Any]:
        return {
            "session_id": self.session_id,
            "conversation_id": self.conversation_id,
            "run_id": self.run_id,
            "project_id": self.project_id,
            "messages": [m.public_dict() for m in self.messages],
            "created_at": self.created_at,
            "metadata": dict(self.metadata),
            "truth": {
                "single_context_run_history": True,
                "voice_uses_same_conversation_model": True,
            },
        }


class MultimodalSessionRegistry:
    """In-process registry for multimodal project sessions (U253/U257)."""

    def __init__(self) -> None:
        self._sessions: dict[str, MultimodalSession] = {}

    def create(
        self,
        *,
        conversation_id: str | None = None,
        run_id: str | None = None,
        project_id: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> MultimodalSession:
        session = MultimodalSession(
            session_id=f"mms_{uuid.uuid4().hex[:12]}",
            conversation_id=conversation_id,
            run_id=run_id,
            project_id=project_id,
            metadata=dict(metadata or {}),
        )
        self._sessions[session.session_id] = session
        return session

    def get(self, session_id: str) -> MultimodalSession | None:
        return self._sessions.get(session_id)

    def require(self, session_id: str) -> MultimodalSession:
        session = self.get(session_id)
        if session is None:
            raise KeyError(f"Unknown multimodal session: {session_id}")
        return session

    def list(self, *, limit: int = 50) -> list[MultimodalSession]:
        items = list(self._sessions.values())
        items.sort(key=lambda s: s.created_at, reverse=True)
        return items[:limit]
