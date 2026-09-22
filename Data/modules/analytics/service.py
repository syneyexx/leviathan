"""Server-side LLM statistics aggregation from existing LEVIATHAN stores.

Does not invent costs or fake trends. Values are derived from durable tables
and in-process collectors that already exist.
"""

from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterator


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _parse_ts(value: str | None) -> datetime | None:
    if not value:
        return None
    raw = value.strip()
    if raw.endswith("Z"):
        raw = raw[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(raw)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


class AnalyticsService:
    """Bounded window aggregates for /api/analytics/*."""

    def __init__(self, db_path: Path) -> None:
        self.db_path = Path(db_path)

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self.db_path, timeout=30, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
        finally:
            conn.close()

    def _window(self, range_key: str) -> tuple[datetime, datetime]:
        end = utc_now()
        mapping = {
            "1h": timedelta(hours=1),
            "24h": timedelta(hours=24),
            "7d": timedelta(days=7),
            "30d": timedelta(days=30),
            "90d": timedelta(days=90),
        }
        delta = mapping.get(range_key, timedelta(days=7))
        return end - delta, end

    def _table_exists(self, conn: sqlite3.Connection, name: str) -> bool:
        row = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
            (name,),
        ).fetchone()
        return row is not None

    def overview(self, *, range_key: str = "7d") -> dict[str, Any]:
        start, end = self._window(range_key)
        start_s, end_s = start.isoformat(timespec="seconds"), end.isoformat(timespec="seconds")
        with self.connect() as conn:
            training = self._count_jobs(conn, "training_jobs", start_s, end_s)
            datasets = self._count_jobs(conn, "dataset_jobs", start_s, end_s)
            agent_missions = self._count_jobs(conn, "agent_missions", start_s, end_s, time_col="created_at")
            approvals = self._count_simple(conn, "approvals", start_s, end_s, time_col="created_at")
            verifications = self._count_simple(
                conn, "verification_reports", start_s, end_s, time_col="created_at"
            )
            jobs = self._count_jobs(conn, "jobs", start_s, end_s, time_col="created_at", status_col="state")
            status_breakdown = self._status_breakdown(conn, start_s, end_s)
        return {
            "range": range_key,
            "from": start_s,
            "to": end_s,
            "collectedAt": end_s,
            "totals": {
                "trainingJobs": training,
                "datasetJobs": datasets,
                "agentMissions": agent_missions,
                "approvals": approvals,
                "verificationReports": verifications,
                "capabilityJobs": jobs,
            },
            "statusBreakdown": status_breakdown,
            "truth": {
                "server_side_aggregation": True,
                "no_invented_cost": True,
                "no_fake_trends": True,
            },
        }

    def _count_simple(
        self,
        conn: sqlite3.Connection,
        table: str,
        start_s: str,
        end_s: str,
        *,
        time_col: str,
    ) -> dict[str, int]:
        if not self._table_exists(conn, table):
            return {"total": 0}
        row = conn.execute(
            f"SELECT COUNT(*) AS c FROM {table} WHERE {time_col} >= ? AND {time_col} <= ?",
            (start_s, end_s),
        ).fetchone()
        return {"total": int(row["c"] if row else 0)}

    def _count_jobs(
        self,
        conn: sqlite3.Connection,
        table: str,
        start_s: str,
        end_s: str,
        *,
        time_col: str = "created_at",
        status_col: str = "status",
    ) -> dict[str, int]:
        if not self._table_exists(conn, table):
            return {"total": 0, "completed": 0, "failed": 0, "running": 0, "cancelled": 0}
        rows = conn.execute(
            f"""
            SELECT {status_col} AS status, COUNT(*) AS c
            FROM {table}
            WHERE {time_col} >= ? AND {time_col} <= ?
            GROUP BY {status_col}
            """,
            (start_s, end_s),
        ).fetchall()
        out = {"total": 0, "completed": 0, "failed": 0, "running": 0, "cancelled": 0, "other": 0}
        active = {"queued", "starting", "running", "preflight", "evaluating", "exporting", "cancelling", "busy"}
        for row in rows:
            status = str(row["status"] or "").lower()
            count = int(row["c"])
            out["total"] += count
            if status in {"completed", "succeeded", "ready"}:
                out["completed"] += count
            elif status in {"failed", "error", "unverified", "interrupted"}:
                out["failed"] += count
            elif status in {"cancelled", "canceled"}:
                out["cancelled"] += count
            elif status in active:
                out["running"] += count
            else:
                out["other"] += count
        return out

    def _status_breakdown(self, conn: sqlite3.Connection, start_s: str, end_s: str) -> dict[str, Any]:
        return {
            "training": self._count_jobs(conn, "training_jobs", start_s, end_s),
            "datasets": self._count_jobs(conn, "dataset_jobs", start_s, end_s),
            "agents": self._count_jobs(conn, "agent_missions", start_s, end_s),
            "jobs": self._count_jobs(conn, "jobs", start_s, end_s, status_col="state"),
        }

    def agents(self, *, range_key: str = "7d") -> dict[str, Any]:
        start, end = self._window(range_key)
        start_s, end_s = start.isoformat(timespec="seconds"), end.isoformat(timespec="seconds")
        rows_out: list[dict[str, Any]] = []
        with self.connect() as conn:
            if not self._table_exists(conn, "agent_missions"):
                return {
                    "range": range_key,
                    "from": start_s,
                    "to": end_s,
                    "agents": [],
                    "truth": {"server_side_aggregation": True},
                }
            rows = conn.execute(
                """
                SELECT agent_id,
                       COUNT(*) AS total,
                       SUM(CASE WHEN status='completed' THEN 1 ELSE 0 END) AS completed,
                       SUM(CASE WHEN status='failed' THEN 1 ELSE 0 END) AS failed,
                       SUM(CASE WHEN status='cancelled' THEN 1 ELSE 0 END) AS cancelled,
                       SUM(CASE WHEN status IN ('queued','starting','running','cancelling') THEN 1 ELSE 0 END) AS active
                FROM agent_missions
                WHERE created_at >= ? AND created_at <= ?
                GROUP BY agent_id
                ORDER BY total DESC
                LIMIT 100
                """,
                (start_s, end_s),
            ).fetchall()
            names: dict[str, str] = {}
            if self._table_exists(conn, "agent_definitions"):
                for r in conn.execute("SELECT agent_id, name FROM agent_definitions").fetchall():
                    names[r["agent_id"]] = r["name"]
            for row in rows:
                rows_out.append(
                    {
                        "agentId": row["agent_id"],
                        "name": names.get(row["agent_id"]),
                        "total": int(row["total"]),
                        "completed": int(row["completed"] or 0),
                        "failed": int(row["failed"] or 0),
                        "cancelled": int(row["cancelled"] or 0),
                        "active": int(row["active"] or 0),
                    }
                )
        return {
            "range": range_key,
            "from": start_s,
            "to": end_s,
            "collectedAt": end_s,
            "agents": rows_out,
            "truth": {"server_side_aggregation": True, "no_quality_score": True},
        }

    def training(self, *, range_key: str = "7d") -> dict[str, Any]:
        start, end = self._window(range_key)
        start_s, end_s = start.isoformat(timespec="seconds"), end.isoformat(timespec="seconds")
        with self.connect() as conn:
            by_method: list[dict[str, Any]] = []
            by_status = self._count_jobs(conn, "training_jobs", start_s, end_s)
            if self._table_exists(conn, "training_jobs"):
                for row in conn.execute(
                    """
                    SELECT method, COUNT(*) AS c
                    FROM training_jobs
                    WHERE created_at >= ? AND created_at <= ?
                    GROUP BY method
                    ORDER BY c DESC
                    LIMIT 50
                    """,
                    (start_s, end_s),
                ).fetchall():
                    by_method.append({"method": row["method"], "count": int(row["c"])})
            checkpoint_count = 0
            if self._table_exists(conn, "training_checkpoints"):
                row = conn.execute(
                    """
                    SELECT COUNT(*) AS c FROM training_checkpoints
                    WHERE created_at >= ? AND created_at <= ?
                    """,
                    (start_s, end_s),
                ).fetchone()
                checkpoint_count = int(row["c"] if row else 0)
        return {
            "range": range_key,
            "from": start_s,
            "to": end_s,
            "collectedAt": end_s,
            "byStatus": by_status,
            "byMethod": by_method,
            "checkpoints": checkpoint_count,
            "truth": {"server_side_aggregation": True},
        }

    def datasets(self, *, range_key: str = "7d") -> dict[str, Any]:
        start, end = self._window(range_key)
        start_s, end_s = start.isoformat(timespec="seconds"), end.isoformat(timespec="seconds")
        with self.connect() as conn:
            by_status = self._count_jobs(conn, "dataset_jobs", start_s, end_s)
            dataset_count = 0
            version_count = 0
            index_count = 0
            if self._table_exists(conn, "datasets"):
                dataset_count = int(
                    conn.execute("SELECT COUNT(*) AS c FROM datasets").fetchone()["c"]
                )
            if self._table_exists(conn, "dataset_versions"):
                version_count = int(
                    conn.execute("SELECT COUNT(*) AS c FROM dataset_versions").fetchone()["c"]
                )
            if self._table_exists(conn, "dataset_indexes"):
                index_count = int(
                    conn.execute("SELECT COUNT(*) AS c FROM dataset_indexes").fetchone()["c"]
                )
            by_type: list[dict[str, Any]] = []
            if self._table_exists(conn, "dataset_jobs"):
                for row in conn.execute(
                    """
                    SELECT job_type, COUNT(*) AS c
                    FROM dataset_jobs
                    WHERE created_at >= ? AND created_at <= ?
                    GROUP BY job_type
                    ORDER BY c DESC
                    LIMIT 50
                    """,
                    (start_s, end_s),
                ).fetchall():
                    by_type.append({"jobType": row["job_type"], "count": int(row["c"])})
        return {
            "range": range_key,
            "from": start_s,
            "to": end_s,
            "collectedAt": end_s,
            "inventory": {
                "datasets": dataset_count,
                "versions": version_count,
                "indexes": index_count,
            },
            "jobsByStatus": by_status,
            "jobsByType": by_type,
            "truth": {"server_side_aggregation": True},
        }

    def tools(self, *, range_key: str = "7d") -> dict[str, Any]:
        start, end = self._window(range_key)
        start_s, end_s = start.isoformat(timespec="seconds"), end.isoformat(timespec="seconds")
        rows_out: list[dict[str, Any]] = []
        with self.connect() as conn:
            if self._table_exists(conn, "jobs"):
                for row in conn.execute(
                    """
                    SELECT capability_id,
                           COUNT(*) AS total,
                           SUM(CASE WHEN state='COMPLETED' THEN 1 ELSE 0 END) AS completed,
                           SUM(CASE WHEN state='FAILED' THEN 1 ELSE 0 END) AS failed
                    FROM jobs
                    WHERE created_at >= ? AND created_at <= ?
                    GROUP BY capability_id
                    ORDER BY total DESC
                    LIMIT 100
                    """,
                    (start_s, end_s),
                ).fetchall():
                    rows_out.append(
                        {
                            "capabilityId": row["capability_id"],
                            "total": int(row["total"]),
                            "completed": int(row["completed"] or 0),
                            "failed": int(row["failed"] or 0),
                        }
                    )
            approvals = self._count_simple(conn, "approvals", start_s, end_s, time_col="created_at")
        return {
            "range": range_key,
            "from": start_s,
            "to": end_s,
            "collectedAt": end_s,
            "capabilities": rows_out,
            "approvals": approvals,
            "truth": {"server_side_aggregation": True},
        }
