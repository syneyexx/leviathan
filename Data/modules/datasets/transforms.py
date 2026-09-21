"""Dataset transforms with explicit lineage."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Callable

from .types import CanonicalRecord, DatasetError


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


TransformFn = Callable[[CanonicalRecord], CanonicalRecord | None]


@dataclass(frozen=True)
class TransformSpec:
    name: str
    params: dict[str, Any]

    def lineage_entry(self, *, input_count: int, output_count: int) -> dict[str, Any]:
        return {
            "name": self.name,
            "params": dict(self.params),
            "inputCount": input_count,
            "outputCount": output_count,
            "appliedAt": utc_now(),
        }


def _strip_whitespace(rec: CanonicalRecord, params: dict[str, Any]) -> CanonicalRecord | None:
    text = rec.text.strip() if params.get("strip", True) else rec.text
    if params.get("collapse_whitespace"):
        text = re.sub(r"[ \t]+", " ", text)
        text = re.sub(r"\n{3,}", "\n\n", text)
    if params.get("drop_empty") and not text.strip() and not rec.messages:
        return None
    return CanonicalRecord(
        id=rec.id,
        text=text,
        messages=rec.messages,
        labels=rec.labels,
        metadata=dict(rec.metadata),
        split=rec.split,
    )


def _lowercase(rec: CanonicalRecord, params: dict[str, Any]) -> CanonicalRecord | None:
    return CanonicalRecord(
        id=rec.id,
        text=rec.text.lower(),
        messages=rec.messages,
        labels=rec.labels,
        metadata={**rec.metadata, "lowercased": True},
        split=rec.split,
    )


def _filter_min_chars(rec: CanonicalRecord, params: dict[str, Any]) -> CanonicalRecord | None:
    minimum = int(params.get("min_chars", 1))
    if len(rec.text) < minimum and not rec.messages:
        return None
    return rec


def _add_prefix(rec: CanonicalRecord, params: dict[str, Any]) -> CanonicalRecord | None:
    prefix = str(params.get("prefix") or "")
    return CanonicalRecord(
        id=rec.id,
        text=f"{prefix}{rec.text}",
        messages=rec.messages,
        labels=rec.labels,
        metadata=dict(rec.metadata),
        split=rec.split,
    )


def _set_metadata(rec: CanonicalRecord, params: dict[str, Any]) -> CanonicalRecord | None:
    extra = params.get("metadata") or {}
    if not isinstance(extra, dict):
        raise DatasetError("set_metadata.metadata must be an object", code="invalid_transform")
    return CanonicalRecord(
        id=rec.id,
        text=rec.text,
        messages=rec.messages,
        labels=rec.labels,
        metadata={**rec.metadata, **extra},
        split=rec.split,
    )


TRANSFORM_REGISTRY: dict[str, Callable[[CanonicalRecord, dict[str, Any]], CanonicalRecord | None]] = {
    "strip_whitespace": _strip_whitespace,
    "lowercase": _lowercase,
    "filter_min_chars": _filter_min_chars,
    "add_prefix": _add_prefix,
    "set_metadata": _set_metadata,
}


def apply_transforms(
    records: list[CanonicalRecord],
    transforms: list[dict[str, Any]],
) -> tuple[list[CanonicalRecord], list[dict[str, Any]]]:
    """Apply named transforms sequentially; return records + lineage entries."""
    current = list(records)
    lineage: list[dict[str, Any]] = []
    for spec_raw in transforms:
        name = str(spec_raw.get("name") or "").strip()
        if not name:
            raise DatasetError("Transform missing name", code="invalid_transform")
        if name not in TRANSFORM_REGISTRY:
            raise DatasetError(f"Unknown transform: {name}", code="unknown_transform")
        params = dict(spec_raw.get("params") or {})
        fn = TRANSFORM_REGISTRY[name]
        next_rows: list[CanonicalRecord] = []
        for rec in current:
            out = fn(rec, params)
            if out is not None:
                next_rows.append(out)
        entry = TransformSpec(name=name, params=params).lineage_entry(
            input_count=len(current),
            output_count=len(next_rows),
        )
        lineage.append(entry)
        current = next_rows
    return current, lineage
