from __future__ import annotations

import json
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterator

from .types import ScheduleRecord, ScheduleStatus, ScheduleTargetKind


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def utc_now_iso() -> str:
    return utc_now().isoformat(timespec="seconds")


class ScheduleStore:
    def __init__(self, db_path: Path) -> None:
        self.db_path = db_path
        self.db_path.parent.mkdir(parents=True, exist_ok=True)

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self.db_path, timeout=15, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    def initialize(self) -> None:
        with self.connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS schedules (
                    schedule_id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    status TEXT NOT NULL,
                    target_kind TEXT NOT NULL,
                    target_ref TEXT NOT NULL,
                    interval_seconds INTEGER NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    next_run_at TEXT NOT NULL,
                    last_run_at TEXT,
                    target_payload_json TEXT NOT NULL DEFAULT '{}',
                    metadata_json TEXT NOT NULL DEFAULT '{}'
                )
                """
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_schedules_next ON schedules(status, next_run_at)"
            )

    def create(
        self,
        *,
        name: str,
        target_kind: ScheduleTargetKind,
        target_ref: str,
        interval_seconds: int,
        target_payload: dict[str, Any] | None = None,
        metadata: dict[str, Any] | None = None,
        start_after_seconds: int = 0,
    ) -> ScheduleRecord:
        if interval_seconds < 1:
            raise ValueError("interval_seconds must be >= 1")
        now = utc_now()
        next_run = now + timedelta(seconds=max(0, start_after_seconds))
        record = ScheduleRecord(
            schedule_id=str(uuid.uuid4()),
            name=name.strip() or "schedule",
            status=ScheduleStatus.ACTIVE,
            target_kind=target_kind,
            target_ref=target_ref,
            interval_seconds=interval_seconds,
            created_at=now.isoformat(timespec="seconds"),
            updated_at=now.isoformat(timespec="seconds"),
            next_run_at=next_run.isoformat(timespec="seconds"),
            target_payload=target_payload or {},
            metadata=metadata or {},
        )
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO schedules(
                    schedule_id, name, status, target_kind, target_ref, interval_seconds,
                    created_at, updated_at, next_run_at, last_run_at,
                    target_payload_json, metadata_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, ?, ?)
                """,
                (
                    record.schedule_id,
                    record.name,
                    record.status.value,
                    record.target_kind.value,
                    record.target_ref,
                    record.interval_seconds,
                    record.created_at,
                    record.updated_at,
                    record.next_run_at,
                    json.dumps(record.target_payload),
                    json.dumps(record.metadata),
                ),
            )
        return record

    def get(self, schedule_id: str) -> ScheduleRecord | None:
        with self.connect() as conn:
            row = conn.execute(
                "SELECT * FROM schedules WHERE schedule_id = ?",
                (schedule_id,),
            ).fetchone()
        return self._from_row(row) if row else None

    def list(self, *, status: ScheduleStatus | None = None, limit: int = 100) -> list[ScheduleRecord]:
        params: list[Any] = []
        where = ""
        if status is not None:
            where = "WHERE status = ?"
            params.append(status.value)
        params.append(max(1, min(limit, 500)))
        with self.connect() as conn:
            rows = conn.execute(
                f"SELECT * FROM schedules {where} ORDER BY next_run_at ASC LIMIT ?",
                params,
            ).fetchall()
        return [self._from_row(row) for row in rows]

    def due(self, *, now: datetime | None = None, limit: int = 50) -> list[ScheduleRecord]:
        stamp = (now or utc_now()).isoformat(timespec="seconds")
        with self.connect() as conn:
            rows = conn.execute(
                """
                SELECT * FROM schedules
                WHERE status = ? AND next_run_at <= ?
                ORDER BY next_run_at ASC
                LIMIT ?
                """,
                (ScheduleStatus.ACTIVE.value, stamp, max(1, min(limit, 200))),
            ).fetchall()
        return [self._from_row(row) for row in rows]

    def mark_ran(self, schedule_id: str, *, ran_at: datetime | None = None) -> ScheduleRecord | None:
        record = self.get(schedule_id)
        if record is None:
            return None
        when = ran_at or utc_now()
        next_run = when + timedelta(seconds=record.interval_seconds)
        with self.connect() as conn:
            conn.execute(
                """
                UPDATE schedules
                SET last_run_at = ?, next_run_at = ?, updated_at = ?
                WHERE schedule_id = ?
                """,
                (
                    when.isoformat(timespec="seconds"),
                    next_run.isoformat(timespec="seconds"),
                    utc_now_iso(),
                    schedule_id,
                ),
            )
        return self.get(schedule_id)

    def set_status(self, schedule_id: str, status: ScheduleStatus) -> ScheduleRecord | None:
        with self.connect() as conn:
            conn.execute(
                "UPDATE schedules SET status = ?, updated_at = ? WHERE schedule_id = ?",
                (status.value, utc_now_iso(), schedule_id),
            )
        return self.get(schedule_id)

    @staticmethod
    def _from_row(row: sqlite3.Row) -> ScheduleRecord:
        return ScheduleRecord(
            schedule_id=row["schedule_id"],
            name=row["name"],
            status=ScheduleStatus(row["status"]),
            target_kind=ScheduleTargetKind(row["target_kind"]),
            target_ref=row["target_ref"],
            interval_seconds=int(row["interval_seconds"]),
            created_at=row["created_at"],
            updated_at=row["updated_at"],
            next_run_at=row["next_run_at"],
            last_run_at=row["last_run_at"],
            target_payload=json.loads(row["target_payload_json"] or "{}"),
            metadata=json.loads(row["metadata_json"] or "{}"),
        )
