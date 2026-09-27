"""Bounded SQLite / DB-commit contention telemetry for observability surfaces (W176)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from Data.modules.common.sqlite_policy import sqlite_metrics_snapshot

UNMEASURED = "UNMEASURED"


def _file_size(path: Path) -> int | str:
    try:
        if path.is_file():
            return int(path.stat().st_size)
    except OSError:
        pass
    return UNMEASURED


def _wal_path(db_path: Path) -> Path:
    return Path(str(db_path) + "-wal")


def commit_queue_depth(database_path: Path | str | None) -> int | str:
    if not database_path:
        return UNMEASURED
    try:
        from Data.modules.db_commit.settings import load_db_commit_settings
        from Data.modules.db_commit.spool import CommitSpool

        settings = load_db_commit_settings()
        if not settings.enabled:
            return UNMEASURED
        root = settings.spool_root_for(Path(database_path))
        if not root.exists():
            return 0
        spool = CommitSpool(root, settings=settings)
        return int(spool.stats().pending_count)
    except Exception:  # noqa: BLE001
        return UNMEASURED


def db_contention_snapshot(database_path: Path | str | None) -> dict[str, Any]:
    path = Path(database_path) if database_path else None
    metrics = sqlite_metrics_snapshot()
    busy_retries = int(metrics.get("sqlite_busy_retry_success") or 0) + int(
        metrics.get("sqlite_busy_count") or 0
    )
    return {
        "dbFileSize": _file_size(path) if path is not None else UNMEASURED,
        "walSize": _file_size(_wal_path(path)) if path is not None else UNMEASURED,
        "busyRetries": busy_retries,
        "busyRetrySuccess": int(metrics.get("sqlite_busy_retry_success") or 0),
        "busyRetryExhausted": int(metrics.get("sqlite_busy_retry_exhausted") or 0),
        "sqliteBusyCount": int(metrics.get("sqlite_busy_count") or 0),
        "commitQueueDepth": commit_queue_depth(path),
        "truth": {
            "boundedPayload": True,
            "unmeasuredIsNotZero": True,
            "fromSqlitePolicy": True,
        },
    }


def three_database_contention_snapshot(paths: Any | None = None) -> dict[str, Any]:
    """Per-domain contention for CONTROL / KNOWLEDGE / MARKET (OBS-001)."""
    out: dict[str, Any] = {
        "domains": {},
        "truth": {
            "perDomain": True,
            "unmeasuredIsNotZero": True,
            "notControlOnly": True,
        },
    }
    if paths is None:
        try:
            from Data.backend.config import load_settings

            paths = load_settings().database_paths
        except Exception:  # noqa: BLE001
            out["domains"] = {
                "CONTROL": {"status": UNMEASURED},
                "KNOWLEDGE": {"status": UNMEASURED},
                "MARKET": {"status": UNMEASURED},
            }
            return out
    mapping = {
        "CONTROL": getattr(paths, "control", None),
        "KNOWLEDGE": getattr(paths, "knowledge", None),
        "MARKET": getattr(paths, "market", None),
    }
    for name, path in mapping.items():
        if path is None:
            out["domains"][name] = {"status": UNMEASURED}
        else:
            snap = db_contention_snapshot(path)
            snap["domain"] = name
            snap["path"] = str(path)
            out["domains"][name] = snap
    return out
