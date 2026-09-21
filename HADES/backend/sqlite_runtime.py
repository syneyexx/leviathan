"""Shared SQLite connection + WAL checkpoint ownership.

Ordinary connections use WAL without truncating. PASSIVE checkpoints run on a
bounded idle/interval. TRUNCATE is reserved for shutdown/maintenance.
"""

from __future__ import annotations

import sqlite3
import threading
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator, Literal

from perf import record_checkpoint, record_sqlite

CheckpointStrategy = Literal["owned", "truncate_on_close"]

PASSIVE_INTERVAL_S = 30.0


class WalCheckpointOwner:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._last_passive: dict[str, float] = {}
        self._strategy: CheckpointStrategy = "owned"

    @property
    def strategy(self) -> CheckpointStrategy:
        return self._strategy

    def set_strategy(self, strategy: CheckpointStrategy) -> None:
        if strategy not in {"owned", "truncate_on_close"}:
            raise ValueError(strategy)
        self._strategy = strategy

    def _key(self, path: str | Path) -> str:
        return str(Path(path).expanduser().resolve())

    def should_passive(self, path: str | Path) -> bool:
        key = self._key(path)
        now = time.monotonic()
        with self._lock:
            last = self._last_passive.get(key, 0.0)
            if now - last < PASSIVE_INTERVAL_S:
                return False
            self._last_passive[key] = now
            return True

    def mark_passive(self, path: str | Path) -> None:
        with self._lock:
            self._last_passive[self._key(path)] = time.monotonic()

    def checkpoint(self, connection: sqlite3.Connection, *, kind: str, path: str | Path) -> None:
        started = time.perf_counter()
        pragma = "TRUNCATE" if kind == "truncate" else "PASSIVE"
        try:
            connection.execute(f"PRAGMA wal_checkpoint({pragma})")
        except sqlite3.Error:
            return
        record_checkpoint(kind=kind, ms=(time.perf_counter() - started) * 1000)
        if kind != "truncate":
            self.mark_passive(path)

    def truncate_file(self, path: str | Path) -> None:
        db_path = Path(path).expanduser().resolve()
        if not db_path.exists():
            return
        conn = sqlite3.connect(str(db_path), timeout=15)
        try:
            self.checkpoint(conn, kind="truncate", path=db_path)
        finally:
            conn.close()


wal_owner = WalCheckpointOwner()


@contextmanager
def sqlite_connection(
    path: str | Path,
    *,
    timeout: float = 10,
    busy_timeout: int = 5000,
) -> Iterator[sqlite3.Connection]:
    db_path = Path(path).expanduser().resolve()
    started = time.perf_counter()
    connection = sqlite3.connect(str(db_path), timeout=timeout)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    connection.execute(f"PRAGMA busy_timeout = {int(busy_timeout)}")
    busy = 0
    committed = 0
    try:
        yield connection
        connection.commit()
        committed = 1
    except sqlite3.OperationalError as exc:
        message = str(exc).lower()
        if "locked" in message or "busy" in message:
            busy = 1
        try:
            connection.rollback()
        except sqlite3.Error:
            pass
        raise
    except Exception:
        try:
            connection.rollback()
        except sqlite3.Error:
            pass
        raise
    finally:
        elapsed_ms = (time.perf_counter() - started) * 1000
        record_sqlite(opens=1, commits=committed, ms=elapsed_ms, busy=busy)
        try:
            if wal_owner.strategy == "truncate_on_close":
                wal_owner.checkpoint(connection, kind="truncate", path=db_path)
            elif wal_owner.should_passive(db_path):
                wal_owner.checkpoint(connection, kind="passive", path=db_path)
        except sqlite3.Error:
            pass
        connection.close()
