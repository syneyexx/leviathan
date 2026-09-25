"""Hot control-plane SQLite connection policy + bounded busy retry.

Re-exports the canonical policy from ``Data.modules.common.sqlite_policy``.
WAL is established during initialize/migration — not on every heartbeat connect.
"""

from __future__ import annotations

from Data.modules.common.sqlite_policy import (
    DEFAULT_BUSY_MAX_ATTEMPTS,
    DEFAULT_BUSY_TIMEOUT_MS,
    DEFAULT_CONNECT_TIMEOUT_S,
    WriteClass,
    begin_immediate,
    control_plane_connection,
    control_write,
    ensure_wal,
    is_transient_sqlite_error,
    open_control_connection,
    open_sqlite_connection,
    reset_sqlite_metrics,
    run_with_busy_retry,
    sqlite_connection,
    sqlite_metrics_snapshot,
    verify_wal,
    write_transaction,
)

__all__ = [
    "DEFAULT_BUSY_MAX_ATTEMPTS",
    "DEFAULT_BUSY_TIMEOUT_MS",
    "DEFAULT_CONNECT_TIMEOUT_S",
    "WriteClass",
    "begin_immediate",
    "control_plane_connection",
    "control_write",
    "ensure_wal",
    "is_transient_sqlite_error",
    "open_control_connection",
    "open_sqlite_connection",
    "reset_sqlite_metrics",
    "run_with_busy_retry",
    "sqlite_connection",
    "sqlite_metrics_snapshot",
    "verify_wal",
    "write_transaction",
]
