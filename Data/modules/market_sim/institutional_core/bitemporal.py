"""W39 — Bitemporal records: effective_time / observed_at / recorded_at / lineage.

Complements pit_fabric — does not invent market quotes.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from typing import Any, Mapping, Sequence

from .status import MeasurementState, DEFAULT_TRUTH


def _canon(obj: Any) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), default=str)


def content_hash(payload: Mapping[str, Any]) -> str:
    return hashlib.sha256(_canon(dict(payload)).encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class BitemporalStamp:
    """Three clocks — never conflate business effective, observation, and record time."""

    effective_time: str  # when the fact was true in the business world
    observed_at: str  # when the system first observed / received the fact
    recorded_at: str  # when this version was written to storage

    def public_dict(self) -> dict[str, Any]:
        return {
            "effectiveTime": self.effective_time,
            "observedAt": self.observed_at,
            "recordedAt": self.recorded_at,
            "truth": {
                "clocks_are_distinct": True,
                "effective_ne_observed_allowed": True,
            },
        }


@dataclass
class LineageRef:
    parent_version_id: str | None
    source_system: str
    source_ref: str | None = None
    transform: str | None = None

    def public_dict(self) -> dict[str, Any]:
        return {
            "parentVersionId": self.parent_version_id,
            "sourceSystem": self.source_system,
            "sourceRef": self.source_ref,
            "transform": self.transform,
        }


@dataclass
class BitemporalRecord:
    entity_id: str
    version_id: str
    stamp: BitemporalStamp
    payload: dict[str, Any]
    lineage: LineageRef
    superseded_by: str | None = None
    status: str = MeasurementState.OBSERVED.value

    def payload_hash(self) -> str:
        return content_hash(self.payload)

    def public_dict(self) -> dict[str, Any]:
        return {
            "entityId": self.entity_id,
            "versionId": self.version_id,
            "stamp": self.stamp.public_dict(),
            "payload": dict(self.payload),
            "payloadHash": self.payload_hash(),
            "lineage": self.lineage.public_dict(),
            "supersededBy": self.superseded_by,
            "status": self.status,
            "truth": DEFAULT_TRUTH.public_dict(),
        }


class BitemporalStore:
    """Append-friendly version store with as-of queries on effective & recorded axes."""

    def __init__(self) -> None:
        self._versions: dict[str, list[BitemporalRecord]] = {}

    def append(self, record: BitemporalRecord) -> BitemporalRecord:
        versions = self._versions.setdefault(record.entity_id, [])
        if versions and record.lineage.parent_version_id:
            for prior in versions:
                if prior.version_id == record.lineage.parent_version_id and prior.superseded_by is None:
                    prior.superseded_by = record.version_id
        versions.append(record)
        return record

    def versions(self, entity_id: str) -> list[BitemporalRecord]:
        return list(self._versions.get(entity_id, []))

    def as_of_effective(
        self,
        entity_id: str,
        *,
        effective_time: str,
        recorded_at: str | None = None,
    ) -> BitemporalRecord | None:
        """Latest version whose effective_time <= as-of, optionally filtered by recorded_at."""
        candidates = [
            v
            for v in self._versions.get(entity_id, [])
            if v.stamp.effective_time <= effective_time
            and (recorded_at is None or v.stamp.recorded_at <= recorded_at)
        ]
        if not candidates:
            return None
        candidates.sort(key=lambda v: (v.stamp.effective_time, v.stamp.recorded_at, v.version_id))
        return candidates[-1]

    def lineage_chain(self, entity_id: str, version_id: str) -> list[dict[str, Any]]:
        by_id = {v.version_id: v for v in self._versions.get(entity_id, [])}
        chain: list[dict[str, Any]] = []
        current = by_id.get(version_id)
        seen: set[str] = set()
        while current is not None and current.version_id not in seen:
            seen.add(current.version_id)
            chain.append(current.public_dict())
            parent = current.lineage.parent_version_id
            current = by_id.get(parent) if parent else None
        return chain

    def public_dict(self) -> dict[str, Any]:
        return {
            "entityCount": len(self._versions),
            "versionCount": sum(len(v) for v in self._versions.values()),
            "truth": {
                **DEFAULT_TRUTH.public_dict(),
                "complements_pit_fabric": True,
                "does_not_invent_quotes": True,
            },
        }


def build_record(
    *,
    entity_id: str,
    version_id: str,
    effective_time: str,
    observed_at: str,
    recorded_at: str,
    payload: Mapping[str, Any],
    source_system: str,
    parent_version_id: str | None = None,
    source_ref: str | None = None,
    transform: str | None = None,
) -> BitemporalRecord:
    return BitemporalRecord(
        entity_id=entity_id,
        version_id=version_id,
        stamp=BitemporalStamp(
            effective_time=effective_time,
            observed_at=observed_at,
            recorded_at=recorded_at,
        ),
        payload=dict(payload),
        lineage=LineageRef(
            parent_version_id=parent_version_id,
            source_system=source_system,
            source_ref=source_ref,
            transform=transform,
        ),
    )


def compare_clocks(stamp: BitemporalStamp) -> dict[str, Any]:
    return {
        "effectiveVsObserved": (
            "aligned"
            if stamp.effective_time == stamp.observed_at
            else "diverged"
        ),
        "observedVsRecorded": (
            "aligned"
            if stamp.observed_at == stamp.recorded_at
            else "diverged"
        ),
        "lateArrival": stamp.observed_at > stamp.effective_time,
        "truth": {"late_arrival_is_valid_bitemporal_case": True},
    }
