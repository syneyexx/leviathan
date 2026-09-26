"""W63 — Unified exception / incident lifecycle."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping

from .status import MeasurementState, DEFAULT_TRUTH


EXCEPTION_STATUSES: tuple[str, ...] = (
    "OPEN",
    "TRIAGED",
    "IN_PROGRESS",
    "MITIGATED",
    "RESOLVED",
    "WAIVED",
)

ALLOWED_EXCEPTION_TRANSITIONS: dict[str, frozenset[str]] = {
    "OPEN": frozenset({"TRIAGED", "WAIVED"}),
    "TRIAGED": frozenset({"IN_PROGRESS", "WAIVED"}),
    "IN_PROGRESS": frozenset({"MITIGATED", "RESOLVED", "TRIAGED"}),
    "MITIGATED": frozenset({"RESOLVED", "IN_PROGRESS"}),
    "RESOLVED": frozenset(),
    "WAIVED": frozenset(),
}


@dataclass
class OpsException:
    exception_id: str
    kind: str
    severity: str  # LOW | MEDIUM | HIGH | CRITICAL
    title: str
    status: str = "OPEN"
    source: str = "UNMEASURED"
    owner: str | None = None
    linked_break_ids: list[str] = field(default_factory=list)
    history: list[dict[str, Any]] = field(default_factory=list)
    detail: str = ""

    def public_dict(self) -> dict[str, Any]:
        return {
            "exceptionId": self.exception_id,
            "kind": self.kind,
            "severity": self.severity,
            "title": self.title,
            "status": self.status,
            "source": self.source,
            "owner": self.owner,
            "linkedBreakIds": list(self.linked_break_ids),
            "history": list(self.history),
            "detail": self.detail,
            "truth": DEFAULT_TRUTH.public_dict(),
        }


class ExceptionRegistry:
    def __init__(self) -> None:
        self._items: dict[str, OpsException] = {}

    def open(self, exc: OpsException) -> OpsException:
        if exc.status not in EXCEPTION_STATUSES:
            raise ValueError(f"invalid exception status: {exc.status}")
        self._items[exc.exception_id] = exc
        return exc

    def transition(
        self,
        exception_id: str,
        *,
        new_status: str,
        actor: str,
        ts: str,
        note: str = "",
        owner: str | None = None,
    ) -> OpsException:
        exc = self._items[exception_id]
        allowed = ALLOWED_EXCEPTION_TRANSITIONS.get(exc.status, frozenset())
        if new_status not in allowed:
            raise ValueError(f"illegal exception transition {exc.status} -> {new_status}")
        if new_status == "RESOLVED" and not note:
            raise ValueError("RESOLVED requires note")
        exc.history.append(
            {"from": exc.status, "to": new_status, "actor": actor, "ts": ts, "note": note}
        )
        exc.status = new_status
        if owner is not None:
            exc.owner = owner
        return exc

    def open_items(self) -> list[dict[str, Any]]:
        return [
            e.public_dict()
            for e in self._items.values()
            if e.status not in {"RESOLVED", "WAIVED"}
        ]

    def public_dict(self) -> dict[str, Any]:
        return {
            "items": [e.public_dict() for e in self._items.values()],
            "openCount": len(self.open_items()),
            "status": (
                MeasurementState.FAIL.value
                if self.open_items()
                else MeasurementState.PASS.value if self._items else MeasurementState.EMPTY.value
            ),
            "truth": DEFAULT_TRUTH.public_dict(),
        }


def exception_from_mapping(raw: Mapping[str, Any]) -> OpsException:
    return OpsException(
        exception_id=str(raw.get("exception_id") or raw.get("exceptionId") or ""),
        kind=str(raw.get("kind") or "GENERAL"),
        severity=str(raw.get("severity") or "MEDIUM").upper(),
        title=str(raw.get("title") or ""),
        status=str(raw.get("status") or "OPEN"),
        source=str(raw.get("source") or "UNMEASURED"),
        owner=(None if raw.get("owner") is None else str(raw.get("owner"))),
        linked_break_ids=list(raw.get("linked_break_ids") or raw.get("linkedBreakIds") or []),
        detail=str(raw.get("detail") or ""),
    )
