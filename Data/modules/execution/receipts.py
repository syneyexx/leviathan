"""Immutable capability-call receipts (U177)."""

from __future__ import annotations

import json
import sqlite3
import uuid
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterator


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _parse_iso(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        text = value.strip()
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        dt = datetime.fromisoformat(text)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except ValueError:
        return None


@dataclass(frozen=True)
class CapabilityCallReceipt:
    receipt_id: str
    request_id: str
    capability_id: str
    provider_kind: str | None
    provider_ref: str | None
    status: str
    authority_decision: str
    side_effects: tuple[str, ...]
    latency_ms: float | None
    run_id: str | None = None
    job_id: str | None = None
    trace_id: str | None = None
    observation_id: str | None = None
    effect_id: str | None = None
    approval_id: str | None = None
    idempotency_key: str | None = None
    artifact_refs: tuple[str, ...] = ()
    evidence_refs: tuple[str, ...] = ()
    error: str | None = None
    recorded_at: str = field(default_factory=_utc_now)
    metadata: dict[str, Any] = field(default_factory=dict)
    requested_by: str | None = None

    def public_dict(self) -> dict[str, Any]:
        return {
            "receipt_id": self.receipt_id,
            "request_id": self.request_id,
            "capability_id": self.capability_id,
            "provider_kind": self.provider_kind,
            "provider_ref": self.provider_ref,
            "status": self.status,
            "authority_decision": self.authority_decision,
            "side_effects": list(self.side_effects),
            "latency_ms": self.latency_ms,
            "run_id": self.run_id,
            "job_id": self.job_id,
            "trace_id": self.trace_id,
            "observation_id": self.observation_id,
            "effect_id": self.effect_id,
            "approval_id": self.approval_id,
            "idempotency_key": self.idempotency_key,
            "artifact_refs": list(self.artifact_refs),
            "evidence_refs": list(self.evidence_refs),
            "error": self.error,
            "recorded_at": self.recorded_at,
            "metadata": self.metadata,
            "requested_by": self.requested_by,
            "truth": {
                "receipt_is_immutable_audit": True,
                "receipt_is_not_authorization": True,
                "provider_outcome_not_invented": True,
                "legacy_caller_may_be_unknown": True,
            },
        }


class CapabilityReceiptStore:
    """Durable capability-call receipts in the canonical SQLite database."""

    def __init__(self, db_path: Path) -> None:
        self.db_path = db_path
        self.db_path.parent.mkdir(parents=True, exist_ok=True)

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self.db_path, timeout=15, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    def initialize(self) -> None:
        with self.connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS capability_call_receipts (
                    receipt_id TEXT PRIMARY KEY,
                    request_id TEXT NOT NULL,
                    capability_id TEXT NOT NULL,
                    provider_kind TEXT,
                    provider_ref TEXT,
                    status TEXT NOT NULL,
                    authority_decision TEXT NOT NULL,
                    side_effects_json TEXT NOT NULL,
                    latency_ms REAL,
                    run_id TEXT,
                    job_id TEXT,
                    trace_id TEXT,
                    observation_id TEXT,
                    effect_id TEXT,
                    approval_id TEXT,
                    idempotency_key TEXT,
                    artifact_refs_json TEXT NOT NULL DEFAULT '[]',
                    evidence_refs_json TEXT NOT NULL DEFAULT '[]',
                    error TEXT,
                    recorded_at TEXT NOT NULL,
                    metadata_json TEXT NOT NULL DEFAULT '{}',
                    requested_by TEXT
                )
                """
            )
            cols = {row[1] for row in conn.execute("PRAGMA table_info(capability_call_receipts)").fetchall()}
            if "requested_by" not in cols:
                conn.execute("ALTER TABLE capability_call_receipts ADD COLUMN requested_by TEXT")
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_capability_receipts_run "
                "ON capability_call_receipts(run_id, recorded_at)"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_capability_receipts_trace "
                "ON capability_call_receipts(trace_id, recorded_at)"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_capability_receipts_request "
                "ON capability_call_receipts(request_id)"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_capability_receipts_capability "
                "ON capability_call_receipts(capability_id, recorded_at)"
            )

    def record(self, receipt: CapabilityCallReceipt) -> CapabilityCallReceipt:
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO capability_call_receipts(
                    receipt_id, request_id, capability_id, provider_kind, provider_ref,
                    status, authority_decision, side_effects_json, latency_ms,
                    run_id, job_id, trace_id, observation_id, effect_id, approval_id,
                    idempotency_key, artifact_refs_json, evidence_refs_json, error,
                    recorded_at, metadata_json, requested_by
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    receipt.receipt_id,
                    receipt.request_id,
                    receipt.capability_id,
                    receipt.provider_kind,
                    receipt.provider_ref,
                    receipt.status,
                    receipt.authority_decision,
                    json.dumps(list(receipt.side_effects)),
                    receipt.latency_ms,
                    receipt.run_id,
                    receipt.job_id,
                    receipt.trace_id,
                    receipt.observation_id,
                    receipt.effect_id,
                    receipt.approval_id,
                    receipt.idempotency_key,
                    json.dumps(list(receipt.artifact_refs)),
                    json.dumps(list(receipt.evidence_refs)),
                    receipt.error,
                    receipt.recorded_at,
                    json.dumps(receipt.metadata or {}),
                    receipt.requested_by,
                ),
            )
        return receipt

    def get(self, receipt_id: str) -> CapabilityCallReceipt | None:
        with self.connect() as conn:
            row = conn.execute(
                "SELECT * FROM capability_call_receipts WHERE receipt_id = ?",
                (receipt_id,),
            ).fetchone()
        return self._row(row) if row else None

    def list_for_run(self, run_id: str, *, limit: int = 100) -> list[CapabilityCallReceipt]:
        with self.connect() as conn:
            rows = conn.execute(
                """
                SELECT * FROM capability_call_receipts
                WHERE run_id = ?
                ORDER BY recorded_at ASC
                LIMIT ?
                """,
                (run_id, limit),
            ).fetchall()
        return [self._row(row) for row in rows]

    def list_for_trace(self, trace_id: str, *, limit: int = 100) -> list[CapabilityCallReceipt]:
        with self.connect() as conn:
            rows = conn.execute(
                """
                SELECT * FROM capability_call_receipts
                WHERE trace_id = ?
                ORDER BY recorded_at ASC
                LIMIT ?
                """,
                (trace_id, limit),
            ).fetchall()
        return [self._row(row) for row in rows]

    def recent(self, *, limit: int = 50) -> list[CapabilityCallReceipt]:
        with self.connect() as conn:
            rows = conn.execute(
                """
                SELECT * FROM capability_call_receipts
                ORDER BY recorded_at DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
        return [self._row(row) for row in rows]

    def recent_for_capability(
        self,
        capability_id: str,
        *,
        limit: int = 50,
    ) -> list[CapabilityCallReceipt]:
        with self.connect() as conn:
            rows = conn.execute(
                """
                SELECT * FROM capability_call_receipts
                WHERE capability_id = ?
                ORDER BY recorded_at DESC
                LIMIT ?
                """,
                (capability_id, limit),
            ).fetchall()
        return [self._row(row) for row in rows]

    def latest_by_capability(
        self,
        capability_ids: list[str] | tuple[str, ...] | None = None,
    ) -> dict[str, str]:
        """Batch map capability_id → latest recorded_at. Avoids N+1."""
        with self.connect() as conn:
            if capability_ids is not None:
                ids = [str(x) for x in capability_ids if str(x)]
                if not ids:
                    return {}
                placeholders = ",".join("?" for _ in ids)
                rows = conn.execute(
                    f"""
                    SELECT capability_id, MAX(recorded_at) AS last_used
                    FROM capability_call_receipts
                    WHERE capability_id IN ({placeholders})
                    GROUP BY capability_id
                    """,
                    ids,
                ).fetchall()
            else:
                rows = conn.execute(
                    """
                    SELECT capability_id, MAX(recorded_at) AS last_used
                    FROM capability_call_receipts
                    GROUP BY capability_id
                    """
                ).fetchall()
        return {str(row["capability_id"]): str(row["last_used"]) for row in rows if row["last_used"]}

    def aggregate_for_capability(
        self,
        capability_id: str,
        *,
        since: str | None = None,
        until: str | None = None,
    ) -> dict[str, Any]:
        clauses = ["capability_id = ?"]
        params: list[Any] = [capability_id]
        if since:
            clauses.append("recorded_at >= ?")
            params.append(since)
        if until:
            clauses.append("recorded_at < ?")
            params.append(until)
        where = " AND ".join(clauses)
        with self.connect() as conn:
            rows = conn.execute(
                f"""
                SELECT status, COUNT(*) AS cnt, AVG(latency_ms) AS avg_latency
                FROM capability_call_receipts
                WHERE {where}
                GROUP BY status
                """,
                params,
            ).fetchall()
            provider_rows = conn.execute(
                f"""
                SELECT COALESCE(provider_ref, provider_kind, 'unknown') AS provider_key,
                       COUNT(*) AS cnt,
                       SUM(CASE WHEN status = 'COMPLETED' THEN 1 ELSE 0 END) AS completed
                FROM capability_call_receipts
                WHERE {where}
                GROUP BY provider_key
                ORDER BY cnt DESC
                LIMIT 20
                """,
                params,
            ).fetchall()
        by_status = {str(row["status"]): int(row["cnt"]) for row in rows}
        latencies = [float(row["avg_latency"]) for row in rows if row["avg_latency"] is not None]
        completed = by_status.get("COMPLETED", 0)
        failed = by_status.get("FAILED", 0)
        timeout = by_status.get("TIMEOUT", 0)
        rejected = by_status.get("REJECTED", 0)
        cancelled = by_status.get("CANCELLED", 0)
        denom = completed + failed + timeout
        success_ratio = (completed / denom) if denom > 0 else None
        avg_latency = None
        if latencies:
            # Weighted by status bucket counts already averaged; recompute from raw when useful.
            with self.connect() as conn:
                row = conn.execute(
                    f"""
                    SELECT AVG(latency_ms) AS avg_latency, COUNT(*) AS total
                    FROM capability_call_receipts
                    WHERE {where} AND latency_ms IS NOT NULL
                    """,
                    params,
                ).fetchone()
            avg_latency = float(row["avg_latency"]) if row and row["avg_latency"] is not None else None
            total_with_latency = int(row["total"]) if row else 0
        else:
            total_with_latency = 0
        return {
            "capability_id": capability_id,
            "total_calls": sum(by_status.values()),
            "completed": completed,
            "failed": failed,
            "timeout": timeout,
            "rejected": rejected,
            "cancelled": cancelled,
            "by_status": by_status,
            "success_ratio": success_ratio,
            "avg_latency_ms": avg_latency,
            "latency_sample_count": total_with_latency,
            "providers": [
                {
                    "provider": str(row["provider_key"]),
                    "calls": int(row["cnt"]),
                    "completed": int(row["completed"] or 0),
                }
                for row in provider_rows
            ],
            "coverage": {
                "has_history": sum(by_status.values()) > 0,
                "success_ratio_unmeasured": denom == 0,
            },
        }

    def aggregate_global(
        self,
        *,
        since: str | None = None,
        until: str | None = None,
        bucket_days: int = 7,
    ) -> dict[str, Any]:
        clauses: list[str] = []
        params: list[Any] = []
        if since:
            clauses.append("recorded_at >= ?")
            params.append(since)
        if until:
            clauses.append("recorded_at < ?")
            params.append(until)
        where = (" WHERE " + " AND ".join(clauses)) if clauses else ""
        with self.connect() as conn:
            rows = conn.execute(
                f"""
                SELECT status, COUNT(*) AS cnt
                FROM capability_call_receipts
                {where}
                GROUP BY status
                """,
                params,
            ).fetchall()
            daily = conn.execute(
                f"""
                SELECT substr(recorded_at, 1, 10) AS day,
                       SUM(CASE WHEN status = 'COMPLETED' THEN 1 ELSE 0 END) AS completed,
                       SUM(CASE WHEN status IN ('FAILED', 'TIMEOUT') THEN 1 ELSE 0 END) AS failedish,
                       COUNT(*) AS total
                FROM capability_call_receipts
                {where}
                GROUP BY day
                ORDER BY day ASC
                """,
                params,
            ).fetchall()
        by_status = {str(row["status"]): int(row["cnt"]) for row in rows}
        completed = by_status.get("COMPLETED", 0)
        failed = by_status.get("FAILED", 0)
        timeout = by_status.get("TIMEOUT", 0)
        rejected = by_status.get("REJECTED", 0)
        cancelled = by_status.get("CANCELLED", 0)
        denom = completed + failed + timeout
        success_ratio = (completed / denom) if denom > 0 else None
        spark = [
            {
                "day": str(row["day"]),
                "completed": int(row["completed"] or 0),
                "failed": int(row["failedish"] or 0),
                "total": int(row["total"] or 0),
            }
            for row in daily
        ]
        return {
            "total_calls": sum(by_status.values()),
            "completed": completed,
            "failed": failed,
            "timeout": timeout,
            "rejected": rejected,
            "cancelled": cancelled,
            "by_status": by_status,
            "success_ratio": success_ratio,
            "spark_buckets": spark[-max(1, bucket_days) :],
            "coverage": {
                "has_history": sum(by_status.values()) > 0,
                "success_ratio_unmeasured": denom == 0,
            },
        }

    def aggregate_provider_usage(
        self,
        capability_id: str | None = None,
        *,
        since: str | None = None,
        limit: int = 20,
    ) -> list[dict[str, Any]]:
        clauses: list[str] = []
        params: list[Any] = []
        if capability_id:
            clauses.append("capability_id = ?")
            params.append(capability_id)
        if since:
            clauses.append("recorded_at >= ?")
            params.append(since)
        where = (" WHERE " + " AND ".join(clauses)) if clauses else ""
        with self.connect() as conn:
            rows = conn.execute(
                f"""
                SELECT COALESCE(provider_ref, provider_kind, 'unknown') AS provider_key,
                       provider_kind,
                       COUNT(*) AS cnt,
                       SUM(CASE WHEN status = 'COMPLETED' THEN 1 ELSE 0 END) AS completed,
                       SUM(CASE WHEN status = 'FAILED' THEN 1 ELSE 0 END) AS failed
                FROM capability_call_receipts
                {where}
                GROUP BY provider_key, provider_kind
                ORDER BY cnt DESC
                LIMIT ?
                """,
                [*params, limit],
            ).fetchall()
        return [
            {
                "provider": str(row["provider_key"]),
                "provider_kind": row["provider_kind"],
                "calls": int(row["cnt"]),
                "completed": int(row["completed"] or 0),
                "failed": int(row["failed"] or 0),
            }
            for row in rows
        ]

    def success_ratio_periods(self, *, days: int = 7) -> dict[str, Any]:
        """Current vs previous period success ratio for KPI trend."""
        now = datetime.now(timezone.utc)
        current_start = (now - timedelta(days=days)).isoformat(timespec="seconds")
        previous_start = (now - timedelta(days=days * 2)).isoformat(timespec="seconds")
        current = self.aggregate_global(since=current_start)
        previous = self.aggregate_global(since=previous_start, until=current_start)
        cur_ratio = current.get("success_ratio")
        prev_ratio = previous.get("success_ratio")
        delta = None
        if cur_ratio is not None and prev_ratio is not None:
            delta = round((cur_ratio - prev_ratio) * 100, 1)
        return {
            "period_days": days,
            "current": current,
            "previous": previous,
            "success_ratio": cur_ratio,
            "previous_success_ratio": prev_ratio,
            "delta_pp": delta,
            "unmeasured": cur_ratio is None,
        }

    @staticmethod
    def _row(row: sqlite3.Row) -> CapabilityCallReceipt:
        keys = set(row.keys())
        return CapabilityCallReceipt(
            receipt_id=row["receipt_id"],
            request_id=row["request_id"],
            capability_id=row["capability_id"],
            provider_kind=row["provider_kind"],
            provider_ref=row["provider_ref"],
            status=row["status"],
            authority_decision=row["authority_decision"],
            side_effects=tuple(json.loads(row["side_effects_json"] or "[]")),
            latency_ms=row["latency_ms"],
            run_id=row["run_id"],
            job_id=row["job_id"],
            trace_id=row["trace_id"],
            observation_id=row["observation_id"],
            effect_id=row["effect_id"],
            approval_id=row["approval_id"],
            idempotency_key=row["idempotency_key"],
            artifact_refs=tuple(json.loads(row["artifact_refs_json"] or "[]")),
            evidence_refs=tuple(json.loads(row["evidence_refs_json"] or "[]")),
            error=row["error"],
            recorded_at=row["recorded_at"],
            metadata=json.loads(row["metadata_json"] or "{}"),
            requested_by=row["requested_by"] if "requested_by" in keys else None,
        )


def build_receipt_from_result(
    *,
    result: Any,
    request: Any,
    authority_decision: str,
) -> CapabilityCallReceipt:
    """Build an immutable receipt from a CapabilityResult + CapabilityRequest."""
    telemetry = dict(getattr(result, "telemetry", None) or {})
    output = getattr(result, "output", None) or {}
    artifact_refs: list[str] = []
    if isinstance(output, dict):
        for key in ("artifact_id", "artifact_ref"):
            if output.get(key):
                artifact_refs.append(str(output[key]))
        for item in output.get("artifact_refs") or []:
            artifact_refs.append(str(item))
        if isinstance(output.get("artifact"), dict) and output["artifact"].get("artifact_id"):
            artifact_refs.append(str(output["artifact"]["artifact_id"]))
    requested_by = getattr(request, "requested_by", None) if request else None
    return CapabilityCallReceipt(
        receipt_id=str(uuid.uuid4()),
        request_id=str(getattr(result, "request_id", "") or ""),
        capability_id=str(getattr(result, "capability_id", "") or ""),
        provider_kind=getattr(result, "provider_kind", None),
        provider_ref=getattr(result, "provider_ref", None),
        status=str(getattr(getattr(result, "status", None), "value", getattr(result, "status", ""))),
        authority_decision=authority_decision,
        side_effects=tuple(
            item.value if hasattr(item, "value") else str(item)
            for item in (getattr(result, "side_effects", ()) or ())
        ),
        latency_ms=telemetry.get("duration_ms"),
        run_id=getattr(request, "run_id", None) if request else None,
        job_id=getattr(request, "job_id", None) if request else None,
        trace_id=getattr(request, "trace_id", None) if request else None,
        observation_id=telemetry.get("observation_id"),
        effect_id=telemetry.get("effect_id"),
        approval_id=getattr(result, "approval_id", None),
        idempotency_key=getattr(request, "idempotency_key", None) if request else None,
        artifact_refs=tuple(artifact_refs),
        evidence_refs=tuple(str(x) for x in (telemetry.get("evidence_refs") or ())),
        error=getattr(result, "error", None),
        requested_by=str(requested_by).strip() if requested_by else None,
        metadata={
            "reason": telemetry.get("reason"),
            "receipt_schema_version": 2,
            "requested_by": str(requested_by).strip() if requested_by else None,
        },
    )
