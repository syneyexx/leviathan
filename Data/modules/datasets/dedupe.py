"""Exact deduplication of canonical records."""

from __future__ import annotations

import json
from typing import Any

from Data.modules.common.hashing import sha256_text

from .types import CanonicalRecord


def record_fingerprint(record: CanonicalRecord) -> str:
    """Exact content fingerprint (id excluded — dedupe by payload)."""
    payload = {
        "text": record.text,
        "messages": record.messages,
        "labels": record.labels,
    }
    return sha256_text(json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str))


def exact_dedupe(records: list[CanonicalRecord]) -> tuple[list[CanonicalRecord], dict[str, Any]]:
    seen: set[str] = set()
    kept: list[CanonicalRecord] = []
    duplicate_ids: list[str] = []
    for rec in records:
        fp = record_fingerprint(rec)
        if fp in seen:
            duplicate_ids.append(rec.id)
            continue
        seen.add(fp)
        kept.append(rec)
    stats = {
        "inputCount": len(records),
        "outputCount": len(kept),
        "removedCount": len(records) - len(kept),
        "duplicateIds": duplicate_ids[:100],
        "duplicateIdsTruncated": len(duplicate_ids) > 100,
        "method": "exact_sha256",
    }
    return kept, stats
