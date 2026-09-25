"""Canonical SQLite operational policy for LEVIATHAN.

WAL is established during database initialization / migration — not on every
hot control-plane or heartbeat connection.

Write classes:
  CONTROL_WRITE  — tiny, latency-sensitive, direct SQLite allowed
  COMMIT_WRITE   — substantial mutations via the DB Commit Coordinator
  MAINTENANCE_WRITE — optional; treated like COMMIT_WRITE for routing
"""

from __future__ import annotations

import os
import random
import sqlite3
import time
from contextlib import contextmanager
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Iterator, TypeVar

T = TypeVar("T")

DEFAULT_CONNECT_TIMEOUT_S = 15.0
DEFAULT_BUSY_TIMEOUT_MS = 5000
DEFAULT_SLOW_TX_MS = 250.0

_BUSY_RETRY_SLEEP_RANGES: tuple[tuple[float, float], ...] = (
    (0.020, 0.050),
    (0.050, 0.100),
    (0.100, 0.250),
)
DEFAULT_BUSY_MAX_ATTEMPTS = 1 + len(_BUSY_RETRY_SLEEP_RANGES)

# Process-local metrics (aggregated into ObservabilityHub by callers).
_METRICS: dict[str, int] = {
    "sqlite_busy_count": 0,
    "sqlite_busy_retry_success": 0,
    "sqlite_busy_retry_exhausted": 0,
    "slow_transaction_count": 0,
}


class WriteClass(str, Enum):
    CONTROL_WRITE = "CONTROL_WRITE"
    COMMIT_WRITE = "COMMIT_WRITE"
    MAINTENANCE_WRITE = "MAINTENANCE_WRITE"


@dataclass(frozen=True)
class ControlWriteSpec:
    """Declarative guard metadata for CONTROL_WRITE operations."""

    operation: str
    expected_max_rows: int = 8
    expected_max_ms: float = 50.0
    write_class: WriteClass = WriteClass.CONTROL_WRITE


def sqlite_metrics_snapshot() -> dict[str, int]:
    return dict(_METRICS)


def reset_sqlite_metrics() -> None:
    for key in _METRICS:
        _METRICS[key] = 0


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


def verify_wal(conn: sqlite3.Connection) -> str:
    row = conn.execute("PRAGMA journal_mode").fetchone()
    return str(row[0] if row is not None else "").lower()


def open_sqlite_connection(
    db_path: Path | str,
    *,
    timeout: float = DEFAULT_CONNECT_TIMEOUT_S,
    busy_timeout_ms: int = DEFAULT_BUSY_TIMEOUT_MS,
    foreign_keys: bool = True,
    row_factory: bool = True,
    set_wal: bool = False,
) -> sqlite3.Connection:
    """Operational connection — busy_timeout yes; journal_mode only when set_wal."""
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
    if set_wal:
        ensure_wal(conn)
    return conn


# Alias used by control-plane callers.
open_control_connection = open_sqlite_connection


@contextmanager
def sqlite_connection(
    db_path: Path | str,
    *,
    timeout: float = DEFAULT_CONNECT_TIMEOUT_S,
    busy_timeout_ms: int = DEFAULT_BUSY_TIMEOUT_MS,
    foreign_keys: bool = True,
    commit: bool = True,
    set_wal: bool = False,
    store: str | None = None,
    operation: str | None = None,
    write_class: WriteClass | str | None = None,
    slow_tx_ms: float | None = None,
) -> Iterator[sqlite3.Connection]:
    """Context-managed connection with rollback-on-error and optional slow-tx log."""
    conn = open_sqlite_connection(
        db_path,
        timeout=timeout,
        busy_timeout_ms=busy_timeout_ms,
        foreign_keys=foreign_keys,
        set_wal=set_wal,
    )
    started = time.perf_counter()
    rows_hint = 0
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
        duration_ms = (time.perf_counter() - started) * 1000.0
        threshold = (
            DEFAULT_SLOW_TX_MS
            if slow_tx_ms is None
            else float(slow_tx_ms)
        )
        if duration_ms >= threshold:
            _METRICS["slow_transaction_count"] += 1
            _emit_slow_transaction(
                store=store or "unknown",
                operation=operation or "unknown",
                duration_ms=duration_ms,
                rows=rows_hint,
                write_class=write_class,
            )
        conn.close()


# Backward-compatible alias.
control_plane_connection = sqlite_connection


def begin_immediate(conn: sqlite3.Connection) -> None:
    """Acquire write ownership deterministically before mutation."""
    conn.execute("BEGIN IMMEDIATE")


@contextmanager
def write_transaction(
    conn: sqlite3.Connection,
    *,
    immediate: bool = True,
    store: str | None = None,
    operation: str | None = None,
    write_class: WriteClass | str | None = WriteClass.COMMIT_WRITE,
    slow_tx_ms: float | None = None,
    rows: int | None = None,
) -> Iterator[sqlite3.Connection]:
    """Bounded write transaction helper. Caller owns connection lifetime."""
    started = time.perf_counter()
    if immediate:
        begin_immediate(conn)
    else:
        conn.execute("BEGIN")
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
        duration_ms = (time.perf_counter() - started) * 1000.0
        threshold = DEFAULT_SLOW_TX_MS if slow_tx_ms is None else float(slow_tx_ms)
        if duration_ms >= threshold:
            _METRICS["slow_transaction_count"] += 1
            _emit_slow_transaction(
                store=store or "unknown",
                operation=operation or "unknown",
                duration_ms=duration_ms,
                rows=int(rows or 0),
                write_class=write_class,
            )


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
    busy_seen = 0
    for attempt in range(attempts):
        try:
            result = fn()
            if busy_seen:
                _METRICS["sqlite_busy_retry_success"] += 1
            return result
        except Exception as exc:  # noqa: BLE001 — filtered below
            if not is_transient_sqlite_error(exc):
                raise
            busy_seen += 1
            _METRICS["sqlite_busy_count"] += 1
            last = exc
            if attempt >= attempts - 1:
                break
            lo, hi = sleep_ranges[min(attempt, len(sleep_ranges) - 1)]
            time.sleep(roller.uniform(lo, hi))
    _METRICS["sqlite_busy_retry_exhausted"] += 1
    assert last is not None
    raise last


def control_write(
    db_path: Path | str,
    fn: Callable[[sqlite3.Connection], T],
    *,
    spec: ControlWriteSpec | None = None,
    busy_timeout_ms: int = DEFAULT_BUSY_TIMEOUT_MS,
) -> T:
    """Tiny CONTROL_WRITE: open → mutate → commit → close, with busy retry."""

    def _once() -> T:
        with sqlite_connection(
            db_path,
            busy_timeout_ms=busy_timeout_ms,
            commit=True,
            store=spec.operation.split(".", 1)[0] if spec else "control",
            operation=spec.operation if spec else "control_write",
            write_class=WriteClass.CONTROL_WRITE,
            slow_tx_ms=(spec.expected_max_ms * 4) if spec else 100.0,
        ) as conn:
            return fn(conn)

    return run_with_busy_retry(_once)


def _emit_slow_transaction(
    *,
    store: str,
    operation: str,
    duration_ms: float,
    rows: int,
    write_class: WriteClass | str | None,
) -> None:
    wc = write_class.value if isinstance(write_class, WriteClass) else (write_class or "")
    line = (
        f"[DB] slow transaction — store={store} operation={operation} "
        f"duration={duration_ms:.0f}ms rows={rows} pid={os.getpid()}"
    )
    if wc:
        line += f" write_class={wc}"
    print(line, flush=True)
