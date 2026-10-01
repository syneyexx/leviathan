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
        from Data.modules.common.sqlite_policy import open_sqlite_connection

        conn = open_sqlite_connection(self.db_path, set_wal=False)
        try:
            yield conn
            conn.commit()
        except Exception:
            try:
                conn.rollback()
            except Exception:  # noqa: BLE001
                pass
            raise
        finally:
            conn.close()


    def initialize(self) -> None:
        from Data.modules.common.sqlite_policy import ensure_wal

        with self.connect() as conn:
            ensure_wal(conn)
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
        module_id: str | None = None,
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
        if module_id:
            clauses.append("module_id = ?")
            params.append(module_id)
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

    def console_stats(
        self,
        *,
        since_ms: float,
        until_ms: float | None = None,
        bucket_count: int = 24,
        top_limit: int = 8,
        recent_errors_limit: int = 12,
        rate_window_ms: float = 300_000.0,
    ) -> dict[str, Any]:
        """Bounded Console aggregates — single coherent read for the V2 page.

        Denominator for component shares: total events in ``[since_ms, until_ms]``.
        Log rate: events in the trailing ``rate_window_ms`` / minutes (measured).
        """
        until = float(until_ms) if until_ms is not None else _now_ms()
        since = float(since_ms)
        if until < since:
            until = since
        bucket_count = max(1, min(int(bucket_count), 96))
        top_limit = max(1, min(int(top_limit), 50))
        recent_errors_limit = max(1, min(int(recent_errors_limit), 100))
        span_ms = max(1.0, until - since)
        bucket_ms = span_ms / bucket_count

        with self.connect() as conn:
            self._ensure_schema(conn)
            rows = conn.execute(
                """
                SELECT UPPER(level) AS lvl, COUNT(*) AS c
                FROM observability_events
                WHERE created_at_ms >= ? AND created_at_ms <= ?
                GROUP BY UPPER(level)
                """,
                (since, until),
            ).fetchall()
            level_counts = {str(row["lvl"]): int(row["c"]) for row in rows}

            total_row = conn.execute(
                """
                SELECT COUNT(*) AS c FROM observability_events
                WHERE created_at_ms >= ? AND created_at_ms <= ?
                """,
                (since, until),
            ).fetchone()
            total = int(total_row["c"] if isinstance(total_row, sqlite3.Row) else total_row[0])

            # Fixed-width histogram buckets by level family.
            bucket_rows = conn.execute(
                """
                SELECT
                  CAST((created_at_ms - ?) / ? AS INTEGER) AS b,
                  UPPER(level) AS lvl,
                  COUNT(*) AS c
                FROM observability_events
                WHERE created_at_ms >= ? AND created_at_ms <= ?
                GROUP BY b, lvl
                """,
                (since, bucket_ms, since, until),
            ).fetchall()

            top_rows = conn.execute(
                """
                SELECT
                  COALESCE(NULLIF(TRIM(subsystem), ''), NULLIF(TRIM(category), ''), 'unknown') AS component,
                  COUNT(*) AS c
                FROM observability_events
                WHERE created_at_ms >= ? AND created_at_ms <= ?
                GROUP BY component
                ORDER BY c DESC
                LIMIT ?
                """,
                (since, until, top_limit),
            ).fetchall()

            error_rows = conn.execute(
                """
                SELECT sequence, event_id, created_at_ms, level, category, subsystem, name, message, source
                FROM observability_events
                WHERE created_at_ms >= ? AND created_at_ms <= ?
                  AND UPPER(level) IN ('ERROR', 'CRITICAL')
                ORDER BY sequence DESC
                LIMIT ?
                """,
                (since, until, recent_errors_limit),
            ).fetchall()

            rate_since = max(since, until - float(rate_window_ms))
            rate_row = conn.execute(
                """
                SELECT COUNT(*) AS c FROM observability_events
                WHERE created_at_ms >= ? AND created_at_ms <= ?
                """,
                (rate_since, until),
            ).fetchone()
            rate_count = int(rate_row["c"] if isinstance(rate_row, sqlite3.Row) else rate_row[0])

            cat_rows = conn.execute(
                """
                SELECT DISTINCT category FROM observability_events
                WHERE created_at_ms >= ? AND created_at_ms <= ?
                  AND TRIM(category) != ''
                ORDER BY category ASC
                LIMIT 200
                """,
                (since, until),
            ).fetchall()
            sub_rows = conn.execute(
                """
                SELECT DISTINCT subsystem FROM observability_events
                WHERE created_at_ms >= ? AND created_at_ms <= ?
                  AND TRIM(subsystem) != ''
                ORDER BY subsystem ASC
                LIMIT 200
                """,
                (since, until),
            ).fetchall()

            # Per-component rates over the rate window (events/min).
            activity_rows = conn.execute(
                """
                SELECT
                  COALESCE(NULLIF(TRIM(subsystem), ''), NULLIF(TRIM(category), ''), 'unknown') AS component,
                  COUNT(*) AS c
                FROM observability_events
                WHERE created_at_ms >= ? AND created_at_ms <= ?
                GROUP BY component
                """,
                (rate_since, until),
            ).fetchall()

            # Metric-card sparklines: per-bucket totals (+ warning/error series).
            spark_rows = conn.execute(
                """
                SELECT
                  CAST((created_at_ms - ?) / ? AS INTEGER) AS b,
                  COUNT(*) AS c,
                  SUM(CASE WHEN UPPER(level) IN ('WARNING', 'WARN') THEN 1 ELSE 0 END) AS warnings,
                  SUM(CASE WHEN UPPER(level) IN ('ERROR', 'CRITICAL') THEN 1 ELSE 0 END) AS errors,
                  SUM(CASE WHEN UPPER(level) = 'SUCCESS' THEN 1 ELSE 0 END) AS success
                FROM observability_events
                WHERE created_at_ms >= ? AND created_at_ms <= ?
                GROUP BY b
                """,
                (since, bucket_ms, since, until),
            ).fetchall()

        buckets: list[dict[str, Any]] = []
        by_bucket: dict[int, dict[str, int]] = {}
        for row in bucket_rows:
            b = int(row["b"])
            if b < 0 or b >= bucket_count:
                # Clamp last-edge events into final bucket.
                b = max(0, min(bucket_count - 1, b))
            slot = by_bucket.setdefault(
                b, {"info": 0, "success": 0, "warning": 0, "error": 0, "other": 0}
            )
            lvl = str(row["lvl"] or "").upper()
            c = int(row["c"])
            if lvl in {"INFO", "DEBUG"}:
                slot["info"] += c
            elif lvl == "SUCCESS":
                slot["success"] += c
            elif lvl in {"WARNING", "WARN"}:
                slot["warning"] += c
            elif lvl in {"ERROR", "CRITICAL"}:
                slot["error"] += c
            else:
                slot["other"] += c

        for i in range(bucket_count):
            slot = by_bucket.get(i, {"info": 0, "success": 0, "warning": 0, "error": 0, "other": 0})
            buckets.append(
                {
                    "bucket_index": i,
                    "bucket_start_ms": since + i * bucket_ms,
                    "bucket_end_ms": since + (i + 1) * bucket_ms,
                    **slot,
                    "total": sum(slot.values()),
                }
            )

        spark_map = {
            int(row["b"]): {
                "total": int(row["c"]),
                "warnings": int(row["warnings"] or 0),
                "errors": int(row["errors"] or 0),
                "success": int(row["success"] or 0),
            }
            for row in spark_rows
        }
        spark_total = [spark_map.get(i, {}).get("total", 0) for i in range(bucket_count)]
        spark_warn = [spark_map.get(i, {}).get("warnings", 0) for i in range(bucket_count)]
        spark_err = [spark_map.get(i, {}).get("errors", 0) for i in range(bucket_count)]
        spark_ok = [spark_map.get(i, {}).get("success", 0) for i in range(bucket_count)]

        rate_minutes = max(1.0 / 60.0, (until - rate_since) / 60_000.0)
        log_rate_per_min = rate_count / rate_minutes if rate_minutes > 0 else None

        top_components: list[dict[str, Any]] = []
        for rank, row in enumerate(top_rows, start=1):
            count = int(row["c"])
            share = (count / total) if total > 0 else None
            top_components.append(
                {
                    "rank": rank,
                    "component": str(row["component"]),
                    "event_count": count,
                    "share": share,
                    "share_denominator": "total_events_in_selected_period",
                }
            )

        recent_errors = [
            {
                "sequence": int(row["sequence"]),
                "event_id": row["event_id"],
                "created_at_ms": float(row["created_at_ms"]),
                "level": row["level"],
                "category": row["category"],
                "subsystem": row["subsystem"],
                "name": row["name"],
                "message": (row["message"] or "")[:240],
                "source": row["source"] or "",
            }
            for row in error_rows
        ]

        activity_by_component = {
            str(row["component"]): int(row["c"]) / rate_minutes for row in activity_rows
        }

        def _lvl(name: str) -> int:
            return int(level_counts.get(name, 0))

        warnings = _lvl("WARNING") + _lvl("WARN")
        errors = _lvl("ERROR") + _lvl("CRITICAL")

        return {
            "window": {
                "since_ms": since,
                "until_ms": until,
                "bucket_count": bucket_count,
                "bucket_ms": bucket_ms,
                "rate_window_ms": float(rate_window_ms),
            },
            "totals": {
                "events": total,
                "info": _lvl("INFO") + _lvl("DEBUG"),
                "success": _lvl("SUCCESS"),
                "warning": warnings,
                "error": errors,
                "by_level": level_counts,
            },
            "log_rate_per_min": log_rate_per_min,
            "log_rate_sample_count": rate_count,
            "buckets": buckets,
            "top_components": top_components,
            "recent_errors": recent_errors,
            "filter_options": {
                "categories": [str(r["category"]) for r in cat_rows],
                "subsystems": [str(r["subsystem"]) for r in sub_rows],
            },
            "sparklines": {
                "total": spark_total,
                "warning": spark_warn,
                "error": spark_err,
                "success": spark_ok,
                "rate": spark_total,
            },
            "activity_rate_by_component": activity_by_component,
            "truth": {
                "durable": True,
                "measured": True,
                "unmeasured_is_null": True,
                "share_denominator": "total_events_in_selected_period",
                "log_rate_is_trailing_window_average": True,
                "no_fabricated_zeros_when_store_missing": True,
            },
        }

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
