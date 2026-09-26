"""Canonical memory / record-size policy for dataset data-plane operations.

Integrated with Worker Fabric ResourceAdmission via reservedRamBytes estimates.
Does NOT claim OS-level HARD memory enforcement unless explicitly implemented.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any


DEFAULT_MEMORY_BUDGET_BYTES = 512 * 1024 * 1024
DEFAULT_BATCH_ROWS = 16_384
DEFAULT_MAX_RECORD_BYTES = 16 * 1024 * 1024
DEFAULT_MAX_FINDINGS = 200
DEFAULT_SPILL_BUDGET_BYTES = 20 * 1024 * 1024 * 1024
DEFAULT_FULL_LOAD_REFUSE_BYTES = 64 * 1024 * 1024
DEFAULT_CSV_FIELD_MAX_BYTES = 8 * 1024 * 1024
DEFAULT_TOKEN_STATS_EXACT_MAX_ROWS = 100_000
DEFAULT_TOKEN_STATS_RESERVOIR = 10_000


class MemoryEnforcement:
    HARD_ENFORCED = "HARD_ENFORCED"
    SOFT_ENFORCED = "SOFT_ENFORCED"
    ADMISSION_ONLY = "ADMISSION_ONLY"
    UNMEASURED = "UNMEASURED"


@dataclass(frozen=True)
class DatasetMemoryPolicy:
    """Single resource contract for heavy dataset operations."""

    memory_budget_bytes: int = DEFAULT_MEMORY_BUDGET_BYTES
    batch_rows: int = DEFAULT_BATCH_ROWS
    max_record_bytes: int = DEFAULT_MAX_RECORD_BYTES
    max_findings: int = DEFAULT_MAX_FINDINGS
    spill_budget_bytes: int = DEFAULT_SPILL_BUDGET_BYTES
    full_load_refuse_bytes: int = DEFAULT_FULL_LOAD_REFUSE_BYTES
    csv_field_max_bytes: int = DEFAULT_CSV_FIELD_MAX_BYTES
    token_stats_exact_max_rows: int = DEFAULT_TOKEN_STATS_EXACT_MAX_ROWS
    token_stats_reservoir: int = DEFAULT_TOKEN_STATS_RESERVOIR
    thread_limit: int = 4
    rust_threshold_bytes: int = 32 * 1024 * 1024
    native_mode: str = "auto"  # auto | python | rust
    enforcement: str = MemoryEnforcement.SOFT_ENFORCED

    def public_dict(self) -> dict[str, Any]:
        return {
            "memoryBudgetBytes": self.memory_budget_bytes,
            "batchRows": self.batch_rows,
            "maxRecordBytes": self.max_record_bytes,
            "maxFindings": self.max_findings,
            "spillBudgetBytes": self.spill_budget_bytes,
            "fullLoadRefuseBytes": self.full_load_refuse_bytes,
            "csvFieldMaxBytes": self.csv_field_max_bytes,
            "threadLimit": self.thread_limit,
            "rustThresholdBytes": self.rust_threshold_bytes,
            "nativeMode": self.native_mode,
            "memoryEnforcement": self.enforcement,
            "truth": {
                "hardOsEnforcement": False,
                "admissionIntegrated": True,
                "childRssMonitoring": self.enforcement
                in {MemoryEnforcement.SOFT_ENFORCED, MemoryEnforcement.HARD_ENFORCED},
            },
        }


def _env_int(name: str, default: int) -> int:
    raw = (os.getenv(name) or "").strip()
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError:
        return default


def resolve_dataset_memory_policy(*, settings: Any | None = None) -> DatasetMemoryPolicy:
    """Resolve policy from optional settings + environment overrides."""
    nc = getattr(settings, "native_compute", None) if settings is not None else None

    mem_mb = _env_int("LEVIATHAN_NATIVE_MEMORY_BUDGET_MB", 0)
    if mem_mb <= 0 and nc is not None:
        try:
            mem_mb = int(getattr(nc, "memory_budget_mb", 0) or 0)
        except (TypeError, ValueError):
            mem_mb = 0
    memory_budget = max(64, mem_mb) * 1024 * 1024 if mem_mb > 0 else DEFAULT_MEMORY_BUDGET_BYTES

    max_rec_mb = _env_int("LEVIATHAN_NATIVE_MAX_RECORD_MB", 0)
    if max_rec_mb <= 0 and nc is not None:
        try:
            max_rec_mb = int(getattr(nc, "max_record_mb", 0) or 0)
        except (TypeError, ValueError):
            max_rec_mb = 0
    max_record = max(1, max_rec_mb) * 1024 * 1024 if max_rec_mb > 0 else DEFAULT_MAX_RECORD_BYTES

    batch_rows = _env_int("LEVIATHAN_DATASET_BATCH_ROWS", DEFAULT_BATCH_ROWS)
    if nc is not None and getattr(nc, "batch_rows", None):
        try:
            batch_rows = int(nc.batch_rows)
        except (TypeError, ValueError):
            pass

    threads = _env_int("LEVIATHAN_NATIVE_THREADS", 4)
    if nc is not None and getattr(nc, "threads", None):
        try:
            threads = int(nc.threads)
        except (TypeError, ValueError):
            pass

    rust_mb = _env_int("LEVIATHAN_NATIVE_RUST_THRESHOLD_MB", 32)
    if nc is not None and getattr(nc, "rust_threshold_mb", None) is not None:
        try:
            rust_mb = int(nc.rust_threshold_mb)
        except (TypeError, ValueError):
            pass

    native_mode = (os.getenv("LEVIATHAN_NATIVE_COMPUTE_MODE") or "").strip().lower()
    if not native_mode and nc is not None:
        native_mode = str(getattr(nc, "mode", "") or "").strip().lower()
    if native_mode not in {"auto", "python", "rust"}:
        native_mode = "auto"

    return DatasetMemoryPolicy(
        memory_budget_bytes=memory_budget,
        batch_rows=max(64, batch_rows),
        max_record_bytes=max(64 * 1024, max_record),
        max_findings=max(1, _env_int("LEVIATHAN_DATASET_MAX_FINDINGS", DEFAULT_MAX_FINDINGS)),
        spill_budget_bytes=max(
            64 * 1024 * 1024,
            _env_int("LEVIATHAN_DATASET_SPILL_BUDGET_BYTES", DEFAULT_SPILL_BUDGET_BYTES),
        ),
        full_load_refuse_bytes=max(
            1024 * 1024,
            _env_int("LEVIATHAN_DATASET_FULL_LOAD_REFUSE_BYTES", DEFAULT_FULL_LOAD_REFUSE_BYTES),
        ),
        csv_field_max_bytes=max(
            64 * 1024,
            _env_int("LEVIATHAN_DATASET_CSV_FIELD_MAX_BYTES", DEFAULT_CSV_FIELD_MAX_BYTES),
        ),
        thread_limit=max(1, min(64, threads)),
        rust_threshold_bytes=max(1024 * 1024, rust_mb * 1024 * 1024),
        native_mode=native_mode,
        enforcement=MemoryEnforcement.SOFT_ENFORCED,
    )
