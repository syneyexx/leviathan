"""Human review / annotation queue with adjudication metadata (U270)."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class AnnotationStatus(str, Enum):
    PENDING = "pending"
    IN_REVIEW = "in_review"
    AGREED = "agreed"
    DISAGREED = "disagreed"
    ADJUDICATED = "adjudicated"
    REJECTED = "rejected"


@dataclass
class AnnotationItem:
    item_id: str
    dataset_id: str
    version_id: str | None
    record_id: str
    label_type: str
    status: AnnotationStatus = AnnotationStatus.PENDING
    labels: list[dict[str, Any]] = field(default_factory=list)
    adjudication: dict[str, Any] | None = None
    created_at: str = field(default_factory=_utc_now)
    updated_at: str = field(default_factory=_utc_now)
    metadata: dict[str, Any] = field(default_factory=dict)

    def public_dict(self) -> dict[str, Any]:
        return {
            "item_id": self.item_id,
            "dataset_id": self.dataset_id,
            "version_id": self.version_id,
            "record_id": self.record_id,
            "label_type": self.label_type,
            "status": self.status.value,
            "labels": list(self.labels),
            "adjudication": dict(self.adjudication) if self.adjudication else None,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "metadata": dict(self.metadata),
            "truth": {
                "disagreement_requires_adjudication": True,
                "uncertain_labels_are_explicit": True,
            },
        }


class AnnotationQueue:
    """In-process + store-backed annotation queue for preference/synthetic labels."""

    def __init__(self) -> None:
        self._items: dict[str, AnnotationItem] = {}

    def enqueue(
        self,
        *,
        dataset_id: str,
        record_id: str,
        label_type: str = "preference",
        version_id: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> AnnotationItem:
        item = AnnotationItem(
            item_id=f"ann_{uuid.uuid4().hex[:12]}",
            dataset_id=dataset_id,
            version_id=version_id,
            record_id=record_id,
            label_type=label_type,
            metadata=dict(metadata or {}),
        )
        self._items[item.item_id] = item
        return item

    def get(self, item_id: str) -> AnnotationItem | None:
        return self._items.get(item_id)

    def list(self, *, dataset_id: str | None = None, limit: int = 100) -> list[AnnotationItem]:
        items = list(self._items.values())
        if dataset_id:
            items = [i for i in items if i.dataset_id == dataset_id]
        items.sort(key=lambda i: i.created_at, reverse=True)
        return items[:limit]

    def submit_label(
        self,
        item_id: str,
        *,
        annotator: str,
        label: dict[str, Any],
        uncertain: bool = False,
    ) -> AnnotationItem:
        item = self._items.get(item_id)
        if item is None:
            raise KeyError(f"Unknown annotation item: {item_id}")
        entry = {
            "annotator": annotator,
            "label": dict(label),
            "uncertain": uncertain,
            "at": _utc_now(),
        }
        item.labels.append(entry)
        item.status = AnnotationStatus.IN_REVIEW
        item.updated_at = _utc_now()
        # Disagreement detection when ≥2 certain labels differ.
        certain = [x for x in item.labels if not x.get("uncertain")]
        if len(certain) >= 2:
            payloads = {json_dumps_stable(x["label"]) for x in certain}
            item.status = (
                AnnotationStatus.DISAGREED if len(payloads) > 1 else AnnotationStatus.AGREED
            )
        return item

    def adjudicate(
        self,
        item_id: str,
        *,
        adjudicator: str,
        final_label: dict[str, Any],
        note: str = "",
    ) -> AnnotationItem:
        item = self._items.get(item_id)
        if item is None:
            raise KeyError(f"Unknown annotation item: {item_id}")
        item.adjudication = {
            "adjudicator": adjudicator,
            "final_label": dict(final_label),
            "note": note,
            "at": _utc_now(),
        }
        item.status = AnnotationStatus.ADJUDICATED
        item.updated_at = _utc_now()
        return item


def json_dumps_stable(value: Any) -> str:
    import json

    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
