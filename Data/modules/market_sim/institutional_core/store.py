"""Optional in-memory / SQLite-ready persistence helpers for institutional_core.

Not a second JobRuntime or InstitutionalDatabase — local scratch/state only.
"""

from __future__ import annotations

import json
import sqlite3
import threading
from dataclasses import dataclass, field
from typing import Any, Iterable, Mapping


def _canon(obj: Any) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), default=str)


@dataclass
class MemoryStore:
    """Thread-safe key→JSON document store for institutional domain objects."""

    namespace: str = "institutional_core"
    _docs: dict[str, dict[str, Any]] = field(default_factory=dict)
    _lock: threading.RLock = field(default_factory=threading.RLock)

    def put(self, key: str, doc: Mapping[str, Any]) -> None:
        with self._lock:
            self._docs[str(key)] = dict(doc)

    def get(self, key: str) -> dict[str, Any] | None:
        with self._lock:
            raw = self._docs.get(str(key))
            return dict(raw) if raw is not None else None

    def delete(self, key: str) -> bool:
        with self._lock:
            return self._docs.pop(str(key), None) is not None

    def list_keys(self, prefix: str = "") -> list[str]:
        with self._lock:
            keys = sorted(self._docs)
            if prefix:
                keys = [k for k in keys if k.startswith(prefix)]
            return keys

    def items(self, prefix: str = "") -> list[tuple[str, dict[str, Any]]]:
        with self._lock:
            out: list[tuple[str, dict[str, Any]]] = []
            for key in sorted(self._docs):
                if prefix and not key.startswith(prefix):
                    continue
                out.append((key, dict(self._docs[key])))
            return out

    def clear(self) -> None:
        with self._lock:
            self._docs.clear()

    def public_dict(self) -> dict[str, Any]:
        with self._lock:
            return {
                "namespace": self.namespace,
                "count": len(self._docs),
                "keys": sorted(self._docs),
                "truth": {
                    "in_memory_only": True,
                    "not_institutional_database": True,
                    "not_job_runtime": True,
                },
            }


class SqliteReadyStore:
    """Minimal SQLite document table — schema-ready, not a competing metadata DB."""

    def __init__(self, path: str = ":memory:", table: str = "institutional_docs") -> None:
        self.path = path
        self.table = table
        self._conn = sqlite3.connect(path, check_same_thread=False)
        self._lock = threading.RLock()
        self._ensure_schema()

    def _ensure_schema(self) -> None:
        with self._lock:
            self._conn.execute(
                f"""
                CREATE TABLE IF NOT EXISTS {self.table} (
                    doc_key TEXT PRIMARY KEY,
                    payload TEXT NOT NULL,
                    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
            self._conn.commit()

    def put(self, key: str, doc: Mapping[str, Any]) -> None:
        payload = _canon(dict(doc))
        with self._lock:
            self._conn.execute(
                f"""
                INSERT INTO {self.table} (doc_key, payload, updated_at)
                VALUES (?, ?, CURRENT_TIMESTAMP)
                ON CONFLICT(doc_key) DO UPDATE SET
                    payload=excluded.payload,
                    updated_at=CURRENT_TIMESTAMP
                """,
                (str(key), payload),
            )
            self._conn.commit()

    def get(self, key: str) -> dict[str, Any] | None:
        with self._lock:
            row = self._conn.execute(
                f"SELECT payload FROM {self.table} WHERE doc_key = ?",
                (str(key),),
            ).fetchone()
        if not row:
            return None
        return json.loads(row[0])

    def delete(self, key: str) -> bool:
        with self._lock:
            cur = self._conn.execute(
                f"DELETE FROM {self.table} WHERE doc_key = ?",
                (str(key),),
            )
            self._conn.commit()
            return cur.rowcount > 0

    def list_keys(self, prefix: str = "") -> list[str]:
        with self._lock:
            if prefix:
                rows = self._conn.execute(
                    f"SELECT doc_key FROM {self.table} WHERE doc_key LIKE ? ORDER BY doc_key",
                    (f"{prefix}%",),
                ).fetchall()
            else:
                rows = self._conn.execute(
                    f"SELECT doc_key FROM {self.table} ORDER BY doc_key"
                ).fetchall()
        return [r[0] for r in rows]

    def bulk_put(self, items: Iterable[tuple[str, Mapping[str, Any]]]) -> int:
        count = 0
        for key, doc in items:
            self.put(key, doc)
            count += 1
        return count

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    def public_dict(self) -> dict[str, Any]:
        return {
            "path": self.path,
            "table": self.table,
            "count": len(self.list_keys()),
            "truth": {
                "sqlite_ready_helper": True,
                "not_second_metadata_db": True,
                "not_job_runtime": True,
            },
        }
