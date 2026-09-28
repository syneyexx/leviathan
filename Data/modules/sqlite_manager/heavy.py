"""Central classification of heavy operator SQLite work.

Row LIMIT alone is NOT a cost bound — expensive aggregates over huge tables
remain heavy even with LIMIT 1. Classification is centralized here so routes
do not scatter thresholds.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

# Bounded interactive browsing may remain inline when all of these hold.
_INLINE_DB_BYTES = 64 * 1024 * 1024  # 64 MiB
_INLINE_OFFSET_MAX = 10_000
_INLINE_LIMIT_MAX = 200
_HEAVY_SQL_MARKERS = re.compile(
    r"\b(GROUP\s+BY|DISTINCT|UNION|INTERSECT|EXCEPT|RECURSIVE|"
    r"WINDOW|MATCH|ORDER\s+BY|JOIN|HAVING|WITH)\b",
    re.IGNORECASE,
)
_AGG_MARKERS = re.compile(
    r"\b(COUNT|SUM|AVG|MIN|MAX|TOTAL|GROUP_CONCAT)\s*\(",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class QueryCostDecision:
    heavy: bool
    reason: str
    capability: str
    db_size_bytes: int = 0

    def public_dict(self) -> dict[str, Any]:
        return {
            "heavy": self.heavy,
            "reason": self.reason,
            "capability": self.capability,
            "dbSizeBytes": self.db_size_bytes,
        }


def _db_size(path: Path) -> int:
    try:
        return int(Path(path).stat().st_size)
    except OSError:
        return 0


def classify_operator_query(
    *,
    sql: str,
    domain: str,
    db_path: Path,
    limit: int = 200,
    force_async: bool = False,
    export: bool = False,
    search: str | None = None,
    offset: int = 0,
    table_scan: bool = False,
) -> QueryCostDecision:
    """Decide whether operator SQL stays inline or must use sqlite_ops."""
    size = _db_size(db_path)
    text = str(sql or "")
    capability = "sqlite_ops.query"

    if export:
        return QueryCostDecision(
            True, "export_request", "sqlite_ops.export", db_size_bytes=size
        )
    if force_async:
        return QueryCostDecision(
            True, "operator_requested_async", capability, db_size_bytes=size
        )
    if search and str(search).strip():
        return QueryCostDecision(
            True, "search", "sqlite_ops.search", db_size_bytes=size
        )
    if table_scan and (offset > _INLINE_OFFSET_MAX or size > _INLINE_DB_BYTES):
        return QueryCostDecision(
            True, "large_table_scan", "sqlite_ops.scan", db_size_bytes=size
        )
    if size > _INLINE_DB_BYTES:
        if _HEAVY_SQL_MARKERS.search(text) or _AGG_MARKERS.search(text):
            cap = "sqlite_ops.analytics" if _AGG_MARKERS.search(text) else capability
            return QueryCostDecision(
                True, "large_db_expensive_sql", cap, db_size_bytes=size
            )
        if offset > _INLINE_OFFSET_MAX:
            return QueryCostDecision(
                True, "large_db_deep_offset", "sqlite_ops.scan", db_size_bytes=size
            )
    if _AGG_MARKERS.search(text) and size > (16 * 1024 * 1024):
        return QueryCostDecision(
            True, "aggregate_on_nontrivial_db", "sqlite_ops.analytics", db_size_bytes=size
        )
    if re.search(r"\bWITH\s+RECURSIVE\b", text, re.IGNORECASE):
        return QueryCostDecision(
            True, "recursive_cte", "sqlite_ops.analytics", db_size_bytes=size
        )
    if limit > _INLINE_LIMIT_MAX:
        return QueryCostDecision(
            True, "large_result_limit", capability, db_size_bytes=size
        )
    # Cheap SELECT / page browse.
    return QueryCostDecision(False, "bounded_inline", "inline", db_size_bytes=size)


def classify_integrity_kind(kind: str, *, db_path: Path) -> QueryCostDecision:
    kind_l = str(kind or "quick_check").strip().lower()
    size = _db_size(db_path)
    if kind_l in {"integrity_check", "full", "integrity"}:
        return QueryCostDecision(
            True, "full_integrity_check", "maintenance.db.integrity", db_size_bytes=size
        )
    if size > _INLINE_DB_BYTES:
        return QueryCostDecision(
            True, "quick_check_large_db", "maintenance.db.integrity", db_size_bytes=size
        )
    return QueryCostDecision(False, "bounded_quick_check", "inline", db_size_bytes=size)


def classify_checkpoint_mode(mode: str) -> QueryCostDecision:
    mode_u = str(mode or "PASSIVE").strip().upper()
    if mode_u in {"FULL", "RESTART", "TRUNCATE"}:
        return QueryCostDecision(
            True, f"blocking_checkpoint_{mode_u}", "maintenance.db.checkpoint"
        )
    return QueryCostDecision(False, "passive_checkpoint", "inline")
