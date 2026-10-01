"""Deterministic train/validation/test splits — streaming."""

from __future__ import annotations

import hashlib
from typing import Any, Iterable, Iterator

from .types import CanonicalRecord, DatasetError


def _stable_bucket(record_id: str, seed: int, buckets: int = 10_000) -> int:
    digest = hashlib.sha256(f"{seed}:{record_id}".encode("utf-8")).hexdigest()
    return int(digest[:8], 16) % buckets


def assign_split_label(
    record: CanonicalRecord,
    *,
    seed: int = 42,
    train_ratio: float = 0.8,
    val_ratio: float = 0.1,
    test_ratio: float = 0.1,
) -> str:
    """Record-local split assignment — same semantics as ``iter_deterministic_split``."""
    total = train_ratio + val_ratio + test_ratio
    if abs(total - 1.0) > 1e-6:
        raise DatasetError(
            f"Split ratios must sum to 1.0, got {total}",
            code="invalid_split",
        )
    if min(train_ratio, val_ratio, test_ratio) < 0:
        raise DatasetError("Split ratios must be non-negative", code="invalid_split")

    if record.split in {"train", "validation", "val", "test", "dev"}:
        return "validation" if record.split in {"val", "dev"} else record.split

    train_cut = int(train_ratio * 10_000)
    val_cut = train_cut + int(val_ratio * 10_000)
    bucket = _stable_bucket(record.id, seed)
    if bucket < train_cut:
        return "train"
    if bucket < val_cut:
        return "validation"
    return "test"


def iter_deterministic_split(
    records: Iterable[CanonicalRecord],
    *,
    seed: int = 42,
    train_ratio: float = 0.8,
    val_ratio: float = 0.1,
    test_ratio: float = 0.1,
) -> tuple[Iterator[CanonicalRecord], dict[str, Any]]:
    """Stream split-labeled records; counters updated during iteration."""
    counts = {"train": 0, "validation": 0, "test": 0}
    summary: dict[str, Any] = {
        "seed": seed,
        "ratios": {
            "train": train_ratio,
            "validation": val_ratio,
            "test": test_ratio,
        },
        "counts": counts,
        "method": "sha256_bucket",
        "deterministic": True,
    }

    def _gen() -> Iterator[CanonicalRecord]:
        for rec in records:
            label = assign_split_label(
                rec,
                seed=seed,
                train_ratio=train_ratio,
                val_ratio=val_ratio,
                test_ratio=test_ratio,
            )
            counts[label] = counts.get(label, 0) + 1
            yield CanonicalRecord(
                id=rec.id,
                text=rec.text,
                messages=rec.messages,
                labels=rec.labels,
                metadata=dict(rec.metadata),
                split=label,
            )

    return _gen(), summary
