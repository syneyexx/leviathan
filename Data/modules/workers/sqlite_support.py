"""Hot control-plane SQLite connection policy + bounded busy retry.

WAL is established during initialize/migration — not on every heartbeat connect.
"""

from __future__ import annotations

import random
import sqlite3
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Callable, Iterator, TypeVar

T = TypeVar("T")

DEFAULT_CONNECT_TIMEOUT_S = 15.0
DEFAULT_BUSY_TIMEOUT_MS = 5000
# Bounded exponential backoff with jitter (seconds ranges per failed attempt).
_BUSY_RETRY_SLEEP_RANGES: tuple[tuple[float, float], ...] = (
    (0.020, 0.050),
    (0.050, 0.100),
    (0.100, 0.250),
)
DEFAULT_BUSY_MAX_ATTEMPTS = 1 + len(_BUSY_RETRY_SLEEP_RANGES)  # 4 total tries


def is_transient_sqlite_error(exc: BaseException) -> bool:
    """True only for genuine lock/busy contention — never schema/programming bugs."""
    if not isinstance(exc, sqlite3.OperationalError):
        return False
    msg = str(exc).lower()
    return (
        "database is locked" in msg
        or "database table is locked" in msg
        or "busy" in msg
        or "locked" in msg
    )


def ensure_wal(conn: sqlite3.Connection) -> str:
    """Set WAL once (initialize/migration). Tolerates DB already in WAL."""
    row = conn.execute("PRAGMA journal_mode = WAL").fetchone()
    mode = str(row[0] if row is not None else "").lower()
    return mode


def open_control_connection(
    db_path: Path | str,
    *,
    timeout: float = DEFAULT_CONNECT_TIMEOUT_S,
    busy_timeout_ms: int = DEFAULT_BUSY_TIMEOUT_MS,
    foreign_keys: bool = True,
    row_factory: bool = True,
) -> sqlite3.Connection:
    """Operational control-plane connection — busy_timeout yes, journal_mode no."""
    conn = sqlite3.connect(
        str(db_path),
        timeout=float(timeout),
        check_same_thread=False,
    )
    if row_factory:
        conn.row_factory = sqlite3.Row
    if foreign_keys:
        conn.execute("PRAGMA foreign_keys = ON")
    conn.execute(f"PRAGMA busy_timeout = {int(busy_timeout_ms)}")
    return conn


@contextmanager
def control_plane_connection(
    db_path: Path | str,
    *,
    timeout: float = DEFAULT_CONNECT_TIMEOUT_S,
    busy_timeout_ms: int = DEFAULT_BUSY_TIMEOUT_MS,
    foreign_keys: bool = True,
    commit: bool = True,
) -> Iterator[sqlite3.Connection]:
    conn = open_control_connection(
        db_path,
        timeout=timeout,
        busy_timeout_ms=busy_timeout_ms,
        foreign_keys=foreign_keys,
    )
    try:
        yield conn
        if commit:
            conn.commit()
    except Exception:
        try:
            conn.rollback()
        except Exception:  # noqa: BLE001
            pass
        raise
    finally:
        conn.close()


def run_with_busy_retry(
    fn: Callable[[], T],
    *,
    max_attempts: int = DEFAULT_BUSY_MAX_ATTEMPTS,
    sleep_ranges: tuple[tuple[float, float], ...] = _BUSY_RETRY_SLEEP_RANGES,
    rng: random.Random | None = None,
) -> T:
    """Retry only transient SQLITE_BUSY / locked errors with bounded backoff+jitter."""
    attempts = max(1, int(max_attempts))
    roller = rng or random.Random()
    last: BaseException | None = None
    for attempt in range(attempts):
        try:
            return fn()
        except Exception as exc:  # noqa: BLE001 — filtered below
            if not is_transient_sqlite_error(exc):
                raise
            last = exc
            if attempt >= attempts - 1:
                break
            lo, hi = sleep_ranges[min(attempt, len(sleep_ranges) - 1)]
            time.sleep(roller.uniform(lo, hi))
    assert last is not None
    raise last
