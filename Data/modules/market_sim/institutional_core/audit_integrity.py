"""W61 — Hash-chained audit extending institutional_ops.AuditLog."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from typing import Any, Mapping, Sequence

from .status import MeasurementState, DEFAULT_TRUTH


def _canon(obj: Any) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), default=str)


GENESIS_HASH = "0" * 64


@dataclass
class ChainedAuditEvent:
    event_id: str
    kind: str
    actor: str
    detail: str
    ts: str
    prev_hash: str
    event_hash: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    def compute_hash(self) -> str:
        payload = {
            "event_id": self.event_id,
            "kind": self.kind,
            "actor": self.actor,
            "detail": self.detail,
            "ts": self.ts,
            "prev_hash": self.prev_hash,
            "metadata": self.metadata,
        }
        return hashlib.sha256(_canon(payload).encode("utf-8")).hexdigest()

    def public_dict(self) -> dict[str, Any]:
        return {
            "eventId": self.event_id,
            "kind": self.kind,
            "actor": self.actor,
            "detail": self.detail,
            "ts": self.ts,
            "prevHash": self.prev_hash,
            "eventHash": self.event_hash,
            "metadata": dict(self.metadata),
            "truth": {
                **DEFAULT_TRUTH.public_dict(),
                "append_only_hash_chain": True,
                "extends_institutional_ops_audit_log": True,
            },
        }


class HashChainedAuditLog:
    """Hash-chained extension around institutional_ops.AuditLog semantics."""

    def __init__(self) -> None:
        self._events: list[ChainedAuditEvent] = []
        self._base_log = None
        try:
            from ..institutional_ops import AuditLog

            self._base_log = AuditLog()
        except Exception:  # noqa: BLE001
            self._base_log = None

    def _last_hash(self) -> str:
        if not self._events:
            return GENESIS_HASH
        return self._events[-1].event_hash

    def append(
        self,
        *,
        event_id: str,
        kind: str,
        actor: str,
        detail: str,
        ts: str,
        metadata: Mapping[str, Any] | None = None,
    ) -> ChainedAuditEvent:
        event = ChainedAuditEvent(
            event_id=event_id,
            kind=kind,
            actor=actor,
            detail=detail,
            ts=ts,
            prev_hash=self._last_hash(),
            metadata=dict(metadata or {}),
        )
        event.event_hash = event.compute_hash()
        self._events.append(event)
        if self._base_log is not None:
            from ..institutional_ops import AuditEvent

            self._base_log.append(
                AuditEvent(
                    event_id=event_id,
                    kind=kind,
                    actor=actor,
                    detail=detail,
                    ts=ts,
                    metadata={**dict(metadata or {}), "eventHash": event.event_hash, "prevHash": event.prev_hash},
                )
            )
        return event

    def list_events(self) -> list[dict[str, Any]]:
        return [e.public_dict() for e in self._events]

    def verify(self) -> dict[str, Any]:
        """Detect corruption / broken chain / tampered payloads."""
        errors: list[str] = []
        expected_prev = GENESIS_HASH
        for idx, event in enumerate(self._events):
            if event.prev_hash != expected_prev:
                errors.append(f"broken_prev_link:{idx}:{event.event_id}")
            recomputed = event.compute_hash()
            if recomputed != event.event_hash:
                errors.append(f"payload_tamper:{idx}:{event.event_id}")
            expected_prev = event.event_hash
        ok = not errors
        return {
            "ok": ok,
            "status": MeasurementState.PASS.value if ok else MeasurementState.FAIL.value,
            "eventCount": len(self._events),
            "errors": errors,
            "tipHash": self._last_hash() if self._events else GENESIS_HASH,
            "truth": {
                **DEFAULT_TRUTH.public_dict(),
                "corruption_detected_when_not_ok": not ok,
            },
        }

    def public_dict(self) -> dict[str, Any]:
        return {
            "events": self.list_events(),
            "verify": self.verify(),
            "baseAuditMirrored": self._base_log is not None,
            "truth": DEFAULT_TRUTH.public_dict(),
        }


def detect_corruption(events: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Verify an exported chain without needing the live log object."""
    errors: list[str] = []
    expected_prev = GENESIS_HASH
    for idx, raw in enumerate(events):
        prev = str(raw.get("prevHash") or raw.get("prev_hash") or "")
        event_hash = str(raw.get("eventHash") or raw.get("event_hash") or "")
        event = ChainedAuditEvent(
            event_id=str(raw.get("eventId") or raw.get("event_id") or ""),
            kind=str(raw.get("kind") or ""),
            actor=str(raw.get("actor") or ""),
            detail=str(raw.get("detail") or ""),
            ts=str(raw.get("ts") or ""),
            prev_hash=prev,
            metadata=dict(raw.get("metadata") or {}),
        )
        if prev != expected_prev:
            errors.append(f"broken_prev_link:{idx}")
        recomputed = event.compute_hash()
        if event_hash and recomputed != event_hash:
            errors.append(f"payload_tamper:{idx}")
        expected_prev = event_hash or recomputed
    return {
        "ok": not errors,
        "status": MeasurementState.PASS.value if not errors else MeasurementState.FAIL.value,
        "errors": errors,
    }
