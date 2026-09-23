"""Durable bounded observability event history (SQLite)."""

from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator


class EventStore:
    """Append-only event history with monotonic sequence and retention."""

    def __init__(
        self,
        db_path: Path,
        *,
        max_rows: int = 50_000,
        retention_days: int = 14,
    ) -> None:
        if max_rows < 100:
            raise ValueError("max_rows must be >= 100")
        self.db_path = Path(db_path)
        self.max_rows = max_rows
        self.retention_days = max(1, retention_days)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self.db_path, timeout=30, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def initialize(self) -> None:
        with self.connect() as conn:
            self._ensure_schema(conn)

    def _ensure_schema(self, conn: sqlite3.Connection) -> None:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS observability_events (
                sequence INTEGER PRIMARY KEY AUTOINCREMENT,
                event_id TEXT NOT NULL UNIQUE,
                created_at_ms REAL NOT NULL,
                level TEXT NOT NULL,
                category TEXT NOT NULL,
                subsystem TEXT NOT NULL,
                name TEXT NOT NULL,
                message TEXT NOT NULL DEFAULT '',
                payload_json TEXT NOT NULL DEFAULT '{}',
                source TEXT NOT NULL DEFAULT '',
                request_id TEXT,
                correlation_id TEXT,
                parent_correlation_id TEXT,
                actor TEXT,
                run_id TEXT,
                job_id TEXT,
                workflow_id TEXT,
                workflow_run_id TEXT,
                workflow_step_id TEXT,
                module_id TEXT,
                mcp_server_id TEXT,
                tool_id TEXT,
                capability_id TEXT,
                research_project_id TEXT,
                dataset_id TEXT,
                evidence_id TEXT,
                duration_ms REAL,
                success INTEGER,
                redacted INTEGER NOT NULL DEFAULT 1
            )
            """
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_obs_events_created "
            "ON observability_events(created_at_ms DESC)"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_obs_events_level "
            "ON observability_events(level, created_at_ms DESC)"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_obs_events_category "
            "ON observability_events(category, created_at_ms DESC)"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_obs_events_correlation "
            "ON observability_events(correlation_id, sequence)"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_obs_events_subsystem "
            "ON observability_events(subsystem, created_at_ms DESC)"
        )

    def append(self, event: dict[str, Any]) -> int:
        """Persist one event; returns assigned sequence number."""
        with self.connect() as conn:
            self._ensure_schema(conn)
            cur = conn.execute(
                """
                INSERT INTO observability_events(
                    event_id, created_at_ms, level, category, subsystem, name, message,
                    payload_json, source, request_id, correlation_id, parent_correlation_id,
                    actor, run_id, job_id, workflow_id, workflow_run_id, workflow_step_id,
                    module_id, mcp_server_id, tool_id, capability_id, research_project_id,
                    dataset_id, evidence_id, duration_ms, success, redacted
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    event["event_id"],
                    float(event["created_at_ms"]),
                    event["level"],
                    event["category"],
                    event.get("subsystem") or event["category"],
                    event["name"],
                    event.get("message") or "",
                    json.dumps(event.get("payload") or {}, default=str, separators=(",", ":")),
                    event.get("source") or "",
                    event.get("request_id"),
                    event.get("correlation_id"),
                    event.get("parent_correlation_id"),
                    event.get("actor"),
                    event.get("run_id"),
                    event.get("job_id"),
                    event.get("workflow_id"),
                    event.get("workflow_run_id"),
                    event.get("workflow_step_id"),
                    event.get("module_id"),
                    event.get("mcp_server_id"),
                    event.get("tool_id"),
                    event.get("capability_id"),
                    event.get("research_project_id"),
                    event.get("dataset_id"),
                    event.get("evidence_id"),
                    event.get("duration_ms"),
                    None if event.get("success") is None else (1 if event.get("success") else 0),
                    1 if event.get("redacted", True) else 0,
                ),
            )
            sequence = int(cur.lastrowid)
            self._enforce_bounds(conn)
            return sequence

    def _enforce_bounds(self, conn: sqlite3.Connection) -> None:
        # Retention by age
        cutoff_ms = _now_ms() - (self.retention_days * 86_400_000)
        conn.execute(
            "DELETE FROM observability_events WHERE created_at_ms < ?",
            (cutoff_ms,),
        )
        # Cap total rows (keep newest)
        row = conn.execute("SELECT COUNT(*) AS c FROM observability_events").fetchone()
        count = int(row["c"] if isinstance(row, sqlite3.Row) else row[0])
        if count > self.max_rows:
            overflow = count - self.max_rows
            conn.execute(
                """
                DELETE FROM observability_events WHERE sequence IN (
                    SELECT sequence FROM observability_events
                    ORDER BY sequence ASC LIMIT ?
                )
                """,
                (overflow,),
            )

    def query(
        self,
        *,
        limit: int = 100,
        before_sequence: int | None = None,
        after_sequence: int | None = None,
        level: str | None = None,
        category: str | None = None,
        subsystem: str | None = None,
        source: str | None = None,
        correlation_id: str | None = None,
        q: str | None = None,
        since_ms: float | None = None,
        until_ms: float | None = None,
        newest_first: bool = True,
    ) -> list[dict[str, Any]]:
        limit = max(1, min(int(limit), 1000))
        clauses: list[str] = []
        params: list[Any] = []

        if before_sequence is not None:
            clauses.append("sequence < ?")
            params.append(int(before_sequence))
        if after_sequence is not None:
            clauses.append("sequence > ?")
            params.append(int(after_sequence))
        if level:
            clauses.append("UPPER(level) = UPPER(?)")
            params.append(level)
        if category:
            clauses.append("category = ?")
            params.append(category)
        if subsystem:
            clauses.append("subsystem = ?")
            params.append(subsystem)
        if source:
            clauses.append("source = ?")
            params.append(source)
        if correlation_id:
            clauses.append("correlation_id = ?")
            params.append(correlation_id)
        if since_ms is not None:
            clauses.append("created_at_ms >= ?")
            params.append(float(since_ms))
        if until_ms is not None:
            clauses.append("created_at_ms <= ?")
            params.append(float(until_ms))
        if q:
            clauses.append(
                "(message LIKE ? OR name LIKE ? OR category LIKE ? OR subsystem LIKE ? OR event_id LIKE ?)"
            )
            like = f"%{q}%"
            params.extend([like, like, like, like, like])

        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        order = "DESC" if newest_first else "ASC"
        sql = f"SELECT * FROM observability_events {where} ORDER BY sequence {order} LIMIT ?"
        params.append(limit)

        with self.connect() as conn:
            self._ensure_schema(conn)
            rows = conn.execute(sql, params).fetchall()
        return [self._row_to_dict(row) for row in rows]

    def get_after(self, sequence: int, *, limit: int = 200) -> list[dict[str, Any]]:
        """Events with sequence > cursor, oldest-first (for SSE backfill)."""
        return self.query(
            limit=limit,
            after_sequence=sequence,
            newest_first=False,
        )

    def latest_sequence(self) -> int:
        with self.connect() as conn:
            self._ensure_schema(conn)
            row = conn.execute(
                "SELECT COALESCE(MAX(sequence), 0) AS s FROM observability_events"
            ).fetchone()
            return int(row["s"] if isinstance(row, sqlite3.Row) else row[0])

    def counts_by_level(self, *, since_ms: float | None = None) -> dict[str, int]:
        clauses: list[str] = []
        params: list[Any] = []
        if since_ms is not None:
            clauses.append("created_at_ms >= ?")
            params.append(float(since_ms))
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        with self.connect() as conn:
            self._ensure_schema(conn)
            rows = conn.execute(
                f"SELECT UPPER(level) AS lvl, COUNT(*) AS c FROM observability_events {where} GROUP BY UPPER(level)",
                params,
            ).fetchall()
        return {str(row["lvl"]): int(row["c"]) for row in rows}

    def cleanup(self) -> dict[str, int]:
        with self.connect() as conn:
            self._ensure_schema(conn)
            before = conn.execute("SELECT COUNT(*) AS c FROM observability_events").fetchone()
            before_n = int(before["c"])
            self._enforce_bounds(conn)
            after = conn.execute("SELECT COUNT(*) AS c FROM observability_events").fetchone()
            after_n = int(after["c"])
        return {"before": before_n, "after": after_n, "deleted": before_n - after_n}

    @staticmethod
    def _row_to_dict(row: sqlite3.Row) -> dict[str, Any]:
        payload_raw = row["payload_json"] or "{}"
        try:
            payload = json.loads(payload_raw)
        except json.JSONDecodeError:
            payload = {"_parse_error": True, "raw": payload_raw[:200]}
        success_raw = row["success"]
        return {
            "sequence": int(row["sequence"]),
            "event_id": row["event_id"],
            "created_at_ms": float(row["created_at_ms"]),
            "level": row["level"],
            "category": row["category"],
            "subsystem": row["subsystem"],
            "name": row["name"],
            "message": row["message"] or "",
            "payload": payload if isinstance(payload, dict) else {"value": payload},
            "source": row["source"] or "",
            "request_id": row["request_id"],
            "correlation_id": row["correlation_id"],
            "parent_correlation_id": row["parent_correlation_id"],
            "actor": row["actor"],
            "run_id": row["run_id"],
            "job_id": row["job_id"],
            "workflow_id": row["workflow_id"],
            "workflow_run_id": row["workflow_run_id"],
            "workflow_step_id": row["workflow_step_id"],
            "module_id": row["module_id"],
            "mcp_server_id": row["mcp_server_id"],
            "tool_id": row["tool_id"],
            "capability_id": row["capability_id"],
            "research_project_id": row["research_project_id"],
            "dataset_id": row["dataset_id"],
            "evidence_id": row["evidence_id"],
            "duration_ms": row["duration_ms"],
            "success": None if success_raw is None else bool(success_raw),
            "redacted": bool(row["redacted"]),
        }


def _now_ms() -> float:
    import time

    return time.time() * 1000
