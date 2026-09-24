"""Bounded durable stream event channel for provider_io workers.

Designed for multi-process Windows/Linux without making SQLite a per-token bus:
workers may coalesce deltas; consumers poll by sequence.
"""

from __future__ import annotations

import json
import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

from .errors import ProviderError, ProviderErrorCode
from .types import StreamEvent, StreamEventType


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


class ProviderStreamStore:
    def __init__(self, db_path: Path | str, *, max_events_per_job: int = 2000) -> None:
        self.db_path = Path(db_path)
        self.max_events_per_job = max(64, int(max_events_per_job))
        self._lock = threading.Lock()
        self._seq: dict[str, int] = {}
        self._buffer_counts: dict[str, int] = {}

    def connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.db_path), timeout=30.0, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
        return conn

    def initialize(self) -> None:
        with self.connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS provider_stream_events (
                    job_id TEXT NOT NULL,
                    sequence INTEGER NOT NULL,
                    event_type TEXT NOT NULL,
                    timestamp TEXT NOT NULL,
                    correlation_id TEXT,
                    payload_json TEXT NOT NULL,
                    PRIMARY KEY (job_id, sequence)
                )
                """
            )
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_provider_stream_job
                ON provider_stream_events(job_id, sequence)
                """
            )
            conn.commit()

    def append(
        self,
        job_id: str,
        event_type: StreamEventType | str,
        payload: dict[str, Any] | None = None,
        *,
        correlation_id: str | None = None,
    ) -> StreamEvent:
        et = event_type if isinstance(event_type, StreamEventType) else StreamEventType(str(event_type))
        with self._lock:
            seq = self._seq.get(job_id, 0) + 1
            count = self._buffer_counts.get(job_id, 0) + 1
            if count > self.max_events_per_job and et == StreamEventType.DELTA:
                raise ProviderError(
                    ProviderErrorCode.EXECUTION_CAPACITY_EXHAUSTED,
                    "Provider stream buffer saturated — refusing to drop tokens",
                    retryable=False,
                    details={"job_id": job_id, "max_events": self.max_events_per_job},
                )
            self._seq[job_id] = seq
            self._buffer_counts[job_id] = count
        event = StreamEvent(
            job_id=job_id,
            sequence=seq,
            event_type=et,
            timestamp=_utc_now(),
            payload=dict(payload or {}),
            correlation_id=correlation_id,
        )
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO provider_stream_events(
                    job_id, sequence, event_type, timestamp, correlation_id, payload_json
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    event.job_id,
                    event.sequence,
                    event.event_type.value,
                    event.timestamp,
                    event.correlation_id,
                    json.dumps(event.payload, ensure_ascii=False),
                ),
            )
            conn.commit()
        return event

    def read_after(
        self,
        job_id: str,
        after_sequence: int = 0,
        *,
        limit: int = 100,
    ) -> list[StreamEvent]:
        with self.connect() as conn:
            rows = conn.execute(
                """
                SELECT * FROM provider_stream_events
                WHERE job_id = ? AND sequence > ?
                ORDER BY sequence ASC
                LIMIT ?
                """,
                (job_id, int(after_sequence), max(1, min(int(limit), 500))),
            ).fetchall()
        return [self._from_row(r) for r in rows]

    def iter_until_terminal(
        self,
        job_id: str,
        *,
        after_sequence: int = 0,
        poll_seconds: float = 0.05,
        timeout_seconds: float = 120.0,
    ) -> Iterator[StreamEvent]:
        import time

        seq = after_sequence
        deadline = time.monotonic() + timeout_seconds
        terminal = {
            StreamEventType.COMPLETED,
            StreamEventType.CANCELLED,
            StreamEventType.FAILED,
        }
        while time.monotonic() < deadline:
            events = self.read_after(job_id, seq, limit=200)
            if not events:
                time.sleep(poll_seconds)
                continue
            for event in events:
                seq = event.sequence
                yield event
                if event.event_type in terminal:
                    return
        raise TimeoutError(f"Timed out waiting for provider stream job={job_id}")

    def purge_job(self, job_id: str) -> None:
        with self.connect() as conn:
            conn.execute("DELETE FROM provider_stream_events WHERE job_id = ?", (job_id,))
            conn.commit()
        with self._lock:
            self._seq.pop(job_id, None)
            self._buffer_counts.pop(job_id, None)

    @staticmethod
    def _from_row(row: sqlite3.Row) -> StreamEvent:
        payload = json.loads(row["payload_json"] or "{}")
        return StreamEvent(
            job_id=row["job_id"],
            sequence=int(row["sequence"]),
            event_type=StreamEventType(row["event_type"]),
            timestamp=row["timestamp"],
            payload=payload if isinstance(payload, dict) else {},
            correlation_id=row["correlation_id"],
        )
