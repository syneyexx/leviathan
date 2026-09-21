"""Media domain events — thin helpers over HADES run-event sinks when available."""

from __future__ import annotations

from typing import Any, Callable

from media.models import ProjectStage

EventEmitter = Callable[[str, dict[str, Any]], None]


MEDIA_EVENTS = (
    "media.project.stage",
    "media.project.progress",
    "media.trend.detected",
    "media.opportunity.created",
    "media.asset.generated",
    "media.render.progress",
    "media.publish.status",
    "media.metrics.updated",
    "media.learning.created",
    "media.capability.changed",
)


class MediaEventBus:
    """Best-effort event fan-out. Never raises into the orchestrator."""

    def __init__(self, emit: EventEmitter | None = None) -> None:
        self._emit = emit
        self._buffer: list[dict[str, Any]] = []

    def set_emitter(self, emit: EventEmitter | None) -> None:
        self._emit = emit

    def emit(self, event_type: str, payload: dict[str, Any] | None = None) -> None:
        record = {"type": event_type, "payload": dict(payload or {})}
        self._buffer.append(record)
        if len(self._buffer) > 500:
            self._buffer = self._buffer[-250:]
        if self._emit is None:
            return
        try:
            self._emit(event_type, record["payload"])
        except Exception:
            return

    def project_stage(self, project_id: str, stage: ProjectStage | str, **extra: Any) -> None:
        self.emit(
            "media.project.stage",
            {"project_id": project_id, "stage": str(stage), **extra},
        )

    def project_progress(self, project_id: str, *, stage: str, progress: float, detail: str = "") -> None:
        self.emit(
            "media.project.progress",
            {
                "project_id": project_id,
                "stage": stage,
                "progress": max(0.0, min(1.0, float(progress))),
                "detail": detail,
            },
        )

    def recent(self, limit: int = 50) -> list[dict[str, Any]]:
        return list(self._buffer[-max(1, min(int(limit), 200)) :])
