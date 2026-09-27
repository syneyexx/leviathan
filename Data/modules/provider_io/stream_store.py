"""Bounded durable stream event channel for provider_io workers.

Designed for multi-process Windows/Linux without making SQLite a per-token bus:
workers may coalesce deltas; consumers poll by sequence.

PROVIDER-001: connections go through sqlite_policy (no hot-path journal_mode churn).
PROVIDER-002: sequence is durable in SQLite — not a process-local counter alone.
"""

from __future__ import annotations

import json
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

from Data.modules.common.sqlite_policy import open_sqlite_connection

from .errors import ProviderError, ProviderErrorCode
from .types import StreamEvent, StreamEventType


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


class ProviderStreamStore:
    def __init__(self, db_path: Path | str, *, max_events_per_job: int = 2000) -> None:
        self.db_path = Path(db_path)
        self.max_events_per_job = max(64, int(max_events_per_job))
        self._lock = threading.Lock()
        # Process-local caches are soft hints only — authoritative seq lives in SQLite.
        self._seq: dict[str, int] = {}
        self._buffer_counts: dict[str, int] = {}

    def connect(self):
        # set_wal=False: WAL is established at schema init / migration, not on every append.
        return open_sqlite_connection(self.db_path, set_wal=False)

    def initialize(self) -> None:
        from Data.backend.db_upgrade import apply_wave3_canonical_ddl
        from Data.modules.common.sqlite_policy import open_sqlite_connection

        conn = open_sqlite_connection(self.db_path, set_wal=True)
        try:
            apply_wave3_canonical_ddl(conn, "provider_stream_events")
            conn.commit()
        finally:
            conn.close()

    def _next_sequence(self, conn, job_id: str) -> int:
        row = conn.execute(
            "SELECT COALESCE(MAX(sequence), 0) AS m FROM provider_stream_events WHERE job_id = ?",
            (job_id,),
        ).fetchone()
        return int(row["m"] if row is not None else 0) + 1

    def _event_count(self, conn, job_id: str) -> int:
        row = conn.execute(
            "SELECT COUNT(*) AS c FROM provider_stream_events WHERE job_id = ?",
            (job_id,),
        ).fetchone()
        return int(row["c"] if row is not None else 0)

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
            conn = self.connect()
            try:
                count = self._event_count(conn, job_id)
                if count >= self.max_events_per_job and et == StreamEventType.DELTA:
                    raise ProviderError(
                        ProviderErrorCode.EXECUTION_CAPACITY_EXHAUSTED,
                        "Provider stream buffer saturated — refusing to drop tokens",
                        retryable=False,
                        details={"job_id": job_id, "max_events": self.max_events_per_job},
                    )
                # Durable sequence: allocate under connection lock + process lock.
                # Retry on PRIMARY KEY collision (cross-process race).
                event: StreamEvent | None = None
                last_exc: Exception | None = None
                for _ in range(8):
                    seq = self._next_sequence(conn, job_id)
                    event = StreamEvent(
                        job_id=job_id,
                        sequence=seq,
                        event_type=et,
                        timestamp=_utc_now(),
                        payload=dict(payload or {}),
                        correlation_id=correlation_id,
                    )
                    try:
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
                        self._seq[job_id] = seq
                        self._buffer_counts[job_id] = count + 1
                        return event
                    except Exception as exc:  # noqa: BLE001 — UNIQUE race across processes
                        last_exc = exc
                        try:
                            conn.rollback()
                        except Exception:  # noqa: BLE001
                            pass
                        msg = str(exc).lower()
                        if "unique" in msg or "constraint" in msg:
                            continue
                        raise
                raise ProviderError(
                    ProviderErrorCode.EXECUTION_CAPACITY_EXHAUSTED,
                    f"Failed to allocate durable stream sequence: {last_exc}",
                    retryable=True,
                    details={"job_id": job_id},
                )
            finally:
                conn.close()

    def read_after(
        self,
        job_id: str,
        after_sequence: int = 0,
        *,
        limit: int = 100,
    ) -> list[StreamEvent]:
        conn = self.connect()
        try:
            rows = conn.execute(
                """
                SELECT * FROM provider_stream_events
                WHERE job_id = ? AND sequence > ?
                ORDER BY sequence ASC
                LIMIT ?
                """,
                (job_id, int(after_sequence), max(1, min(int(limit), 500))),
            ).fetchall()
        finally:
            conn.close()
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
        conn = self.connect()
        try:
            conn.execute("DELETE FROM provider_stream_events WHERE job_id = ?", (job_id,))
            conn.commit()
        finally:
            conn.close()
        with self._lock:
            self._seq.pop(job_id, None)
            self._buffer_counts.pop(job_id, None)

    @staticmethod
    def _from_row(row: Any) -> StreamEvent:
        payload = json.loads(row["payload_json"] or "{}")
        return StreamEvent(
            job_id=row["job_id"],
            sequence=int(row["sequence"]),
            event_type=StreamEventType(row["event_type"]),
            timestamp=row["timestamp"],
            payload=payload if isinstance(payload, dict) else {},
            correlation_id=row["correlation_id"],
        )
