"""Deterministic train/validation/test splits."""

from __future__ import annotations

import hashlib
from typing import Any

from .types import CanonicalRecord, DatasetError


def _stable_bucket(record_id: str, seed: int, buckets: int = 10_000) -> int:
    digest = hashlib.sha256(f"{seed}:{record_id}".encode("utf-8")).hexdigest()
    return int(digest[:8], 16) % buckets


def deterministic_split(
    records: list[CanonicalRecord],
    *,
    seed: int = 42,
    train_ratio: float = 0.8,
    val_ratio: float = 0.1,
    test_ratio: float = 0.1,
) -> tuple[list[CanonicalRecord], dict[str, Any]]:
    total = train_ratio + val_ratio + test_ratio
    if abs(total - 1.0) > 1e-6:
        raise DatasetError(
            f"Split ratios must sum to 1.0, got {total}",
            code="invalid_split",
        )
    if min(train_ratio, val_ratio, test_ratio) < 0:
        raise DatasetError("Split ratios must be non-negative", code="invalid_split")

    train_cut = int(train_ratio * 10_000)
    val_cut = train_cut + int(val_ratio * 10_000)

    out: list[CanonicalRecord] = []
    counts = {"train": 0, "validation": 0, "test": 0}
    for rec in records:
        # Honor existing split labels when already set
        if rec.split in {"train", "validation", "val", "test", "dev"}:
            label = "validation" if rec.split in {"val", "dev"} else rec.split
            if label == "test":
                label = "test"
            out.append(
                CanonicalRecord(
                    id=rec.id,
                    text=rec.text,
                    messages=rec.messages,
                    labels=rec.labels,
                    metadata=dict(rec.metadata),
                    split=label,
                )
            )
            counts[label] = counts.get(label, 0) + 1
            continue
        bucket = _stable_bucket(rec.id, seed)
        if bucket < train_cut:
            label = "train"
        elif bucket < val_cut:
            label = "validation"
        else:
            label = "test"
        out.append(
            CanonicalRecord(
                id=rec.id,
                text=rec.text,
                messages=rec.messages,
                labels=rec.labels,
                metadata=dict(rec.metadata),
                split=label,
            )
        )
        counts[label] += 1

    summary = {
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
    return out, summary
