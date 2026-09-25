"""SQLite persistence for operator settings overrides."""

from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class SettingsOverrideStore:
    """Central settings_overrides table (no parallel settings.db)."""

    def __init__(self, database_path: Path) -> None:
        self.path = Path(database_path)

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        from Data.modules.common.sqlite_policy import open_sqlite_connection

        self.path.parent.mkdir(parents=True, exist_ok=True)
        conn = open_sqlite_connection(self.path, set_wal=False)
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
        from Data.modules.common.sqlite_policy import ensure_wal

        with self.connect() as conn:
            ensure_wal(conn)
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS settings_overrides (
                    key TEXT PRIMARY KEY,
                    value_json TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    updated_by TEXT NOT NULL DEFAULT 'operator',
                    version INTEGER NOT NULL DEFAULT 1
                )
                """
            )

    def list_all(self) -> dict[str, Any]:
        with self.connect() as conn:
            rows = conn.execute(
                "SELECT key, value_json FROM settings_overrides ORDER BY key"
            ).fetchall()
        out: dict[str, Any] = {}
        for row in rows:
            try:
                out[str(row["key"])] = json.loads(row["value_json"])
            except json.JSONDecodeError:
                continue
        return out

    def get(self, key: str) -> Any | None:
        with self.connect() as conn:
            row = conn.execute(
                "SELECT value_json FROM settings_overrides WHERE key = ?",
                (key,),
            ).fetchone()
        if row is None:
            return None
        return json.loads(row["value_json"])

    def put(self, key: str, value: Any, *, updated_by: str = "operator") -> None:
        payload = json.dumps(value, ensure_ascii=False, separators=(",", ":"))
        now = utc_now()
        with self.connect() as conn:
            existing = conn.execute(
                "SELECT version FROM settings_overrides WHERE key = ?",
                (key,),
            ).fetchone()
            version = int(existing["version"]) + 1 if existing else 1
            conn.execute(
                """
                INSERT INTO settings_overrides(key, value_json, updated_at, updated_by, version)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(key) DO UPDATE SET
                    value_json = excluded.value_json,
                    updated_at = excluded.updated_at,
                    updated_by = excluded.updated_by,
                    version = excluded.version
                """,
                (key, payload, now, updated_by, version),
            )

    def delete(self, key: str) -> bool:
        with self.connect() as conn:
            cur = conn.execute("DELETE FROM settings_overrides WHERE key = ?", (key,))
            return cur.rowcount > 0

    def delete_keys(self, keys: list[str]) -> int:
        if not keys:
            return 0
        deleted = 0
        with self.connect() as conn:
            for key in keys:
                cur = conn.execute("DELETE FROM settings_overrides WHERE key = ?", (key,))
                deleted += cur.rowcount
        return deleted
