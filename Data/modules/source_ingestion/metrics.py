"""Source ingestion observability counters (process-local, thread-safe)."""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from typing import Any


@dataclass
class _Hist:
    count: int = 0
    total_seconds: float = 0.0

    def observe(self, seconds: float) -> None:
        self.count += 1
        self.total_seconds += max(0.0, seconds)


@dataclass
class IngestionMetrics:
    uploads_accepted: int = 0
    uploads_rejected: int = 0
    bytes_ingested: int = 0
    archives_processed: int = 0
    archive_members_processed: int = 0
    parse_success: int = 0
    parse_failed: int = 0
    parse_cache_hits: int = 0
    content_duplicates: int = 0
    ocr_requested: int = 0
    ocr_succeeded: int = 0
    ocr_failed: int = 0
    ocr_unavailable: int = 0
    dataset_routes_requested: int = 0
    dataset_routes_succeeded: int = 0
    dataset_routes_failed: int = 0
    quarantine_count: int = 0
    brain_sync_failed: int = 0
    phase_latency: dict[str, _Hist] = field(default_factory=dict)
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    def inc(self, name: str, delta: int = 1) -> None:
        with self._lock:
            current = getattr(self, name, None)
            if isinstance(current, int):
                setattr(self, name, current + delta)

    def observe_phase(self, phase: str, seconds: float) -> None:
        with self._lock:
            hist = self.phase_latency.setdefault(phase, _Hist())
            hist.observe(seconds)

    def public_dict(self) -> dict[str, Any]:
        with self._lock:
            phases = {
                k: {
                    "count": v.count,
                    "total_seconds": round(v.total_seconds, 4),
                    "avg_seconds": round(v.total_seconds / v.count, 4) if v.count else None,
                }
                for k, v in self.phase_latency.items()
            }
            return {
                "uploads_accepted": self.uploads_accepted,
                "uploads_rejected": self.uploads_rejected,
                "bytes_ingested": self.bytes_ingested,
                "archives_processed": self.archives_processed,
                "archive_members_processed": self.archive_members_processed,
                "parse_success": self.parse_success,
                "parse_failed": self.parse_failed,
                "parse_cache_hits": self.parse_cache_hits,
                "content_duplicates": self.content_duplicates,
                "ocr_requested": self.ocr_requested,
                "ocr_succeeded": self.ocr_succeeded,
                "ocr_failed": self.ocr_failed,
                "ocr_unavailable": self.ocr_unavailable,
                "dataset_routes_requested": self.dataset_routes_requested,
                "dataset_routes_succeeded": self.dataset_routes_succeeded,
                "dataset_routes_failed": self.dataset_routes_failed,
                "quarantine_count": self.quarantine_count,
                "brain_sync_failed": self.brain_sync_failed,
                "phase_latency": phases,
            }


_METRICS = IngestionMetrics()


def ingestion_metrics() -> IngestionMetrics:
    return _METRICS


class PhaseTimer:
    def __init__(self, phase: str) -> None:
        self.phase = phase
        self._start = time.monotonic()

    def __enter__(self) -> "PhaseTimer":
        return self

    def __exit__(self, *args: Any) -> None:
        ingestion_metrics().observe_phase(self.phase, time.monotonic() - self._start)
