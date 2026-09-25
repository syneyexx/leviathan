"""Market feed CONTROL_WRITE session/checkpoint persistence.

Domain owner: market_sim. Stores coalesced feed session rows and bounded
checkpoints — never per-tick market events.
"""

from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

from Data.modules.market_sim.store import utc_now


def _loads(raw: str | None, default: Any) -> Any:
    if not raw:
        return default
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return default


class MarketFeedStore:
    """SQLite CRUD for market_feed_sessions / checkpoints / latency rollups."""

    def __init__(self, db_path: Path | str) -> None:
        self.db_path = Path(db_path)
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

    def ensure_schema(self) -> None:
        """Idempotent table create for tests / pre-migration environments."""
        with self.connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS market_feed_sessions (
                    feed_id TEXT PRIMARY KEY,
                    provider_id TEXT NOT NULL,
                    symbols_json TEXT NOT NULL DEFAULT '[]',
                    status TEXT NOT NULL DEFAULT 'DISCONNECTED',
                    restart_policy TEXT NOT NULL DEFAULT 'MANUAL',
                    connection_id TEXT NOT NULL DEFAULT '',
                    job_id TEXT,
                    capture_mode TEXT NOT NULL DEFAULT 'OFF',
                    stale_after_seconds REAL NOT NULL DEFAULT 30.0,
                    license_state TEXT NOT NULL DEFAULT 'PUBLIC_TERMS_APPLY',
                    license_note TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    metadata_json TEXT NOT NULL DEFAULT '{}',
                    checkpoint_json TEXT NOT NULL DEFAULT '{}'
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS market_feed_checkpoints (
                    feed_id TEXT NOT NULL,
                    written_at TEXT NOT NULL,
                    snapshot_json TEXT NOT NULL DEFAULT '{}',
                    metrics_json TEXT NOT NULL DEFAULT '{}',
                    PRIMARY KEY (feed_id, written_at)
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS market_feed_latency_rollups (
                    feed_id TEXT NOT NULL,
                    window_start TEXT NOT NULL,
                    window_end TEXT NOT NULL,
                    sample_count INTEGER NOT NULL DEFAULT 0,
                    p50_ms REAL,
                    p95_ms REAL,
                    p99_ms REAL,
                    mean_ms REAL,
                    max_ms REAL,
                    metadata_json TEXT NOT NULL DEFAULT '{}',
                    PRIMARY KEY (feed_id, window_start)
                )
                """
            )

    def upsert_session(self, session: dict[str, Any]) -> dict[str, Any]:
        now = utc_now()
        row = {
            "feed_id": str(session["feed_id"]),
            "provider_id": str(session.get("provider_id") or ""),
            "symbols_json": json.dumps(list(session.get("symbols") or []), ensure_ascii=False),
            "status": str(session.get("status") or "DISCONNECTED"),
            "restart_policy": str(session.get("restart_policy") or "MANUAL"),
            "connection_id": str(session.get("connection_id") or ""),
            "job_id": session.get("job_id"),
            "capture_mode": str(session.get("capture_mode") or "OFF"),
            "stale_after_seconds": float(session.get("stale_after_seconds") or 30.0),
            "license_state": str(session.get("license_state") or "PUBLIC_TERMS_APPLY"),
            "license_note": str(session.get("license_note") or ""),
            "created_at": str(session.get("created_at") or now),
            "updated_at": str(session.get("updated_at") or now),
            "metadata_json": json.dumps(dict(session.get("metadata") or {}), ensure_ascii=False),
            "checkpoint_json": json.dumps(dict(session.get("checkpoint") or {}), ensure_ascii=False),
        }
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO market_feed_sessions(
                    feed_id, provider_id, symbols_json, status, restart_policy,
                    connection_id, job_id, capture_mode, stale_after_seconds,
                    license_state, license_note, created_at, updated_at,
                    metadata_json, checkpoint_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(feed_id) DO UPDATE SET
                    provider_id=excluded.provider_id,
                    symbols_json=excluded.symbols_json,
                    status=excluded.status,
                    restart_policy=excluded.restart_policy,
                    connection_id=excluded.connection_id,
                    job_id=excluded.job_id,
                    capture_mode=excluded.capture_mode,
                    stale_after_seconds=excluded.stale_after_seconds,
                    license_state=excluded.license_state,
                    license_note=excluded.license_note,
                    updated_at=excluded.updated_at,
                    metadata_json=excluded.metadata_json,
                    checkpoint_json=excluded.checkpoint_json
                """,
                (
                    row["feed_id"],
                    row["provider_id"],
                    row["symbols_json"],
                    row["status"],
                    row["restart_policy"],
                    row["connection_id"],
                    row["job_id"],
                    row["capture_mode"],
                    row["stale_after_seconds"],
                    row["license_state"],
                    row["license_note"],
                    row["created_at"],
                    row["updated_at"],
                    row["metadata_json"],
                    row["checkpoint_json"],
                ),
            )
        return self.get_session(row["feed_id"]) or session

    def get_session(self, feed_id: str) -> dict[str, Any] | None:
        with self.connect() as conn:
            row = conn.execute(
                "SELECT * FROM market_feed_sessions WHERE feed_id=?",
                (feed_id,),
            ).fetchone()
        if row is None:
            return None
        return self._row_session(row)

    def list_sessions(self, *, limit: int = 200) -> list[dict[str, Any]]:
        with self.connect() as conn:
            rows = conn.execute(
                "SELECT * FROM market_feed_sessions ORDER BY updated_at DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [self._row_session(r) for r in rows]

    def write_checkpoint(
        self,
        feed_id: str,
        *,
        snapshot: dict[str, Any],
        metrics: dict[str, Any] | None = None,
        written_at: str | None = None,
        max_per_feed: int = 64,
    ) -> dict[str, Any]:
        ts = written_at or utc_now()
        with self.connect() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO market_feed_checkpoints(
                    feed_id, written_at, snapshot_json, metrics_json
                ) VALUES (?, ?, ?, ?)
                """,
                (
                    feed_id,
                    ts,
                    json.dumps(snapshot, ensure_ascii=False, default=str),
                    json.dumps(dict(metrics or {}), ensure_ascii=False, default=str),
                ),
            )
            rows = conn.execute(
                """
                SELECT written_at FROM market_feed_checkpoints
                WHERE feed_id=? ORDER BY written_at DESC
                """,
                (feed_id,),
            ).fetchall()
            if len(rows) > max_per_feed:
                for stale in rows[max_per_feed:]:
                    conn.execute(
                        "DELETE FROM market_feed_checkpoints WHERE feed_id=? AND written_at=?",
                        (feed_id, stale[0] if not isinstance(stale, sqlite3.Row) else stale["written_at"]),
                    )
            # Mirror latest checkpoint onto session row.
            conn.execute(
                """
                UPDATE market_feed_sessions
                SET checkpoint_json=?, updated_at=?
                WHERE feed_id=?
                """,
                (json.dumps(snapshot, ensure_ascii=False, default=str), ts, feed_id),
            )
        return {"feed_id": feed_id, "written_at": ts}

    def list_checkpoints(self, feed_id: str, *, limit: int = 32) -> list[dict[str, Any]]:
        with self.connect() as conn:
            rows = conn.execute(
                """
                SELECT * FROM market_feed_checkpoints
                WHERE feed_id=? ORDER BY written_at DESC LIMIT ?
                """,
                (feed_id, limit),
            ).fetchall()
        out: list[dict[str, Any]] = []
        for row in rows:
            out.append(
                {
                    "feed_id": row["feed_id"],
                    "written_at": row["written_at"],
                    "snapshot": _loads(row["snapshot_json"], {}),
                    "metrics": _loads(row["metrics_json"], {}),
                }
            )
        return out

    def write_latency_rollups(self, feed_id: str, rollups: list[dict[str, Any]]) -> int:
        applied = 0
        with self.connect() as conn:
            for item in rollups:
                window_start = str(item.get("window_start") or "")
                if not window_start:
                    continue
                conn.execute(
                    """
                    INSERT INTO market_feed_latency_rollups(
                        feed_id, window_start, window_end, sample_count,
                        p50_ms, p95_ms, p99_ms, mean_ms, max_ms, metadata_json
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(feed_id, window_start) DO UPDATE SET
                        window_end=excluded.window_end,
                        sample_count=excluded.sample_count,
                        p50_ms=excluded.p50_ms,
                        p95_ms=excluded.p95_ms,
                        p99_ms=excluded.p99_ms,
                        mean_ms=excluded.mean_ms,
                        max_ms=excluded.max_ms,
                        metadata_json=excluded.metadata_json
                    """,
                    (
                        feed_id,
                        window_start,
                        str(item.get("window_end") or window_start),
                        int(item.get("sample_count") or 0),
                        item.get("p50_ms"),
                        item.get("p95_ms"),
                        item.get("p99_ms"),
                        item.get("mean_ms"),
                        item.get("max_ms"),
                        json.dumps(dict(item.get("metadata") or {}), ensure_ascii=False),
                    ),
                )
                applied += 1
        return applied

    def _row_session(self, row: sqlite3.Row) -> dict[str, Any]:
        return {
            "feed_id": row["feed_id"],
            "provider_id": row["provider_id"],
            "symbols": _loads(row["symbols_json"], []),
            "status": row["status"],
            "restart_policy": row["restart_policy"],
            "connection_id": row["connection_id"],
            "job_id": row["job_id"],
            "capture_mode": row["capture_mode"],
            "stale_after_seconds": row["stale_after_seconds"],
            "license_state": row["license_state"],
            "license_note": row["license_note"],
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
            "metadata": _loads(row["metadata_json"], {}),
            "checkpoint": _loads(row["checkpoint_json"], {}),
        }
