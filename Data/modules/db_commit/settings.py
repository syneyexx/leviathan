"""DB Commit Coordinator settings."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any


def _env_bool(name: str, default: bool) -> bool:
    raw = (os.environ.get(name) or "").strip().lower()
    if not raw:
        return default
    return raw in {"1", "true", "yes", "on"}


def _env_int(name: str, default: int) -> int:
    raw = (os.environ.get(name) or "").strip()
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError:
        return default


def _env_float(name: str, default: float) -> float:
    raw = (os.environ.get(name) or "").strip()
    if not raw:
        return default
    try:
        return float(raw)
    except ValueError:
        return default


@dataclass
class DbCommitSettings:
    enabled: bool = True
    max_pending_count: int = 2_000
    max_pending_bytes: int = 2 * 1024 * 1024 * 1024  # 2 GiB
    max_oldest_age_seconds: float = 86_400.0
    soft_backpressure_threshold: float = 0.70
    hard_backpressure_threshold: float = 0.95
    max_batch_rows: int = 1_000
    target_transaction_ms: float = 250.0
    retry_limit: int = 8
    spool_retention_hours: float = 72.0
    applied_retention_hours: float = 24.0
    priority_aging_seconds: float = 120.0
    ipc_timeout_seconds: float = 1.0
    slow_transaction_ms: float = 250.0
    poll_seconds: float = 0.05
    critical_operations: tuple[str, ...] = (
        "knowledge.commit_prepared",
        "system.recovery",
    )

    def public_dict(self) -> dict[str, Any]:
        return {
            "enabled": self.enabled,
            "maxPendingCount": self.max_pending_count,
            "maxPendingBytes": self.max_pending_bytes,
            "maxOldestAgeSeconds": self.max_oldest_age_seconds,
            "softBackpressureThreshold": self.soft_backpressure_threshold,
            "hardBackpressureThreshold": self.hard_backpressure_threshold,
            "maxBatchRows": self.max_batch_rows,
            "targetTransactionMs": self.target_transaction_ms,
            "retryLimit": self.retry_limit,
            "spoolRetentionHours": self.spool_retention_hours,
            "appliedRetentionHours": self.applied_retention_hours,
            "priorityAgingSeconds": self.priority_aging_seconds,
            "ipcTimeoutSeconds": self.ipc_timeout_seconds,
            "slowTransactionMs": self.slow_transaction_ms,
        }

    def spool_root_for(self, database_path: Path) -> Path:
        return Path(database_path).resolve().parent / "commit_spool"

    def payloads_root_for(self, database_path: Path) -> Path:
        return Path(database_path).resolve().parent / "commit_payloads"


def load_db_commit_settings() -> DbCommitSettings:
    return DbCommitSettings(
        enabled=_env_bool("LEVIATHAN_DB_COMMIT_ENABLED", True),
        max_pending_count=_env_int("LEVIATHAN_DB_COMMIT_MAX_PENDING_COUNT", 2_000),
        max_pending_bytes=_env_int(
            "LEVIATHAN_DB_COMMIT_MAX_PENDING_BYTES", 2 * 1024 * 1024 * 1024
        ),
        max_oldest_age_seconds=_env_float(
            "LEVIATHAN_DB_COMMIT_MAX_OLDEST_AGE_SECONDS", 86_400.0
        ),
        soft_backpressure_threshold=_env_float(
            "LEVIATHAN_DB_COMMIT_SOFT_BACKPRESSURE", 0.70
        ),
        hard_backpressure_threshold=_env_float(
            "LEVIATHAN_DB_COMMIT_HARD_BACKPRESSURE", 0.95
        ),
        max_batch_rows=_env_int("LEVIATHAN_DB_COMMIT_MAX_BATCH_ROWS", 1_000),
        target_transaction_ms=_env_float(
            "LEVIATHAN_DB_COMMIT_TARGET_TRANSACTION_MS", 250.0
        ),
        retry_limit=_env_int("LEVIATHAN_DB_COMMIT_RETRY_LIMIT", 8),
        spool_retention_hours=_env_float(
            "LEVIATHAN_DB_COMMIT_SPOOL_RETENTION_HOURS", 72.0
        ),
        applied_retention_hours=_env_float(
            "LEVIATHAN_DB_COMMIT_APPLIED_RETENTION_HOURS", 24.0
        ),
        priority_aging_seconds=_env_float(
            "LEVIATHAN_DB_COMMIT_PRIORITY_AGING_SECONDS", 120.0
        ),
        ipc_timeout_seconds=_env_float("LEVIATHAN_DB_COMMIT_IPC_TIMEOUT_SECONDS", 1.0),
        slow_transaction_ms=_env_float(
            "LEVIATHAN_DB_COMMIT_SLOW_TRANSACTION_MS", 250.0
        ),
        poll_seconds=_env_float("LEVIATHAN_DB_COMMIT_POLL_SECONDS", 0.05),
    )
