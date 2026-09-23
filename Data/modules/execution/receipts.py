"""Immutable capability-call receipts (U177)."""

from __future__ import annotations

import json
import sqlite3
import uuid
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


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
            "truth": {
                "receipt_is_immutable_audit": True,
                "receipt_is_not_authorization": True,
                "provider_outcome_not_invented": True,
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
                    metadata_json TEXT NOT NULL DEFAULT '{}'
                )
                """
            )
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

    def record(self, receipt: CapabilityCallReceipt) -> CapabilityCallReceipt:
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO capability_call_receipts(
                    receipt_id, request_id, capability_id, provider_kind, provider_ref,
                    status, authority_decision, side_effects_json, latency_ms,
                    run_id, job_id, trace_id, observation_id, effect_id, approval_id,
                    idempotency_key, artifact_refs_json, evidence_refs_json, error,
                    recorded_at, metadata_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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

    @staticmethod
    def _row(row: sqlite3.Row) -> CapabilityCallReceipt:
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
        metadata={
            "reason": telemetry.get("reason"),
            "receipt_schema_version": 1,
        },
    )
