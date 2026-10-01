"""Request-bound durable idempotency for the execution gateway."""

from __future__ import annotations

import hashlib
import json
import sqlite3
import uuid
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Iterator

from .types import CapabilityRequest, CapabilityResult, CapabilityStatus


class IdempotencyRecordStatus(str, Enum):
    IN_FLIGHT = "IN_FLIGHT"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)


def execution_fingerprint(
    request: CapabilityRequest,
    *,
    schema_hash: str | None = None,
    schema_version: str | None = None,
) -> str:
    """Canonical SHA-256 of capability identity + normalized args + authority fields.

    Client forgeables such as ``_trusted_authority`` / ``approved_by_user`` are
    excluded so fingerprints bind the caller's intent, not gateway injections.
    """
    args = dict(request.arguments or {})
    for drop in (
        "_trusted_authority",
        "approved_by_user",
        "_approved_by_user",
        "_progress_cb",
        "_cancel_check",
    ):
        args.pop(drop, None)
    payload = {
        "capability_id": request.capability_id,
        "arguments": args,
        "requested_by": request.requested_by or "api",
        "approval_id": request.approval_id,
        "schema_hash": schema_hash,
        "schema_version": schema_version,
    }
    return hashlib.sha256(_canonical_json(payload).encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class IdempotencyRecord:
    idempotency_key: str
    fingerprint: str
    capability_id: str
    status: IdempotencyRecordStatus
    request_id: str
    result_json: dict[str, Any] | None = None
    created_at: str | None = None
    updated_at: str | None = None

    def public_dict(self) -> dict[str, Any]:
        return {
            "idempotency_key": self.idempotency_key,
            "fingerprint": self.fingerprint,
            "capability_id": self.capability_id,
            "status": self.status.value,
            "request_id": self.request_id,
            "result_json": self.result_json,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }


class CapabilityIdempotencyStore:
    """First-class durable idempotency records (claim / complete / fail)."""

    def __init__(self, db_path: Path) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        from Data.modules.common.sqlite_policy import open_sqlite_connection

        conn = open_sqlite_connection(self.db_path, set_wal=False)
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
            conn.close()

    def initialize(self) -> None:
        from Data.modules.common.sqlite_policy import ensure_wal

        with self.connect() as conn:
            ensure_wal(conn)
            self._ensure_schema(conn)

    def _ensure_schema(self, conn: sqlite3.Connection) -> None:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS capability_idempotency (
                idempotency_key TEXT PRIMARY KEY,
                fingerprint TEXT NOT NULL,
                capability_id TEXT NOT NULL,
                status TEXT NOT NULL,
                request_id TEXT NOT NULL,
                result_json TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_capability_idempotency_capability "
            "ON capability_idempotency(capability_id, status)"
        )

    def get(self, idempotency_key: str) -> IdempotencyRecord | None:
        with self.connect() as conn:
            self._ensure_schema(conn)
            row = conn.execute(
                "SELECT * FROM capability_idempotency WHERE idempotency_key = ?",
                (idempotency_key,),
            ).fetchone()
        return self._from_row(row) if row else None

    def claim(
        self,
        *,
        idempotency_key: str,
        fingerprint: str,
        capability_id: str,
        request_id: str,
    ) -> tuple[str, IdempotencyRecord]:
        """Atomically claim an idempotency key for execution.

        Returns ``(outcome, record)`` where outcome is one of:
        ``claimed``, ``replay``, ``in_flight``, ``conflict``.
        """
        now = utc_now()
        with self.connect() as conn:
            self._ensure_schema(conn)
            conn.execute("BEGIN IMMEDIATE")
            existing = conn.execute(
                "SELECT * FROM capability_idempotency WHERE idempotency_key = ?",
                (idempotency_key,),
            ).fetchone()
            if existing is None:
                conn.execute(
                    """
                    INSERT INTO capability_idempotency(
                        idempotency_key, fingerprint, capability_id, status,
                        request_id, result_json, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, NULL, ?, ?)
                    """,
                    (
                        idempotency_key,
                        fingerprint,
                        capability_id,
                        IdempotencyRecordStatus.IN_FLIGHT.value,
                        request_id,
                        now,
                        now,
                    ),
                )
                row = conn.execute(
                    "SELECT * FROM capability_idempotency WHERE idempotency_key = ?",
                    (idempotency_key,),
                ).fetchone()
                return "claimed", self._from_row(row)

            record = self._from_row(existing)
            if record.fingerprint != fingerprint:
                return "conflict", record
            if record.status == IdempotencyRecordStatus.COMPLETED:
                return "replay", record
            if record.status == IdempotencyRecordStatus.IN_FLIGHT:
                return "in_flight", record
            # Prior FAILED with same fingerprint — reclaim for retry.
            conn.execute(
                """
                UPDATE capability_idempotency
                SET status = ?, request_id = ?, result_json = NULL, updated_at = ?,
                    capability_id = ?, fingerprint = ?
                WHERE idempotency_key = ?
                """,
                (
                    IdempotencyRecordStatus.IN_FLIGHT.value,
                    request_id,
                    now,
                    capability_id,
                    fingerprint,
                    idempotency_key,
                ),
            )
            row = conn.execute(
                "SELECT * FROM capability_idempotency WHERE idempotency_key = ?",
                (idempotency_key,),
            ).fetchone()
            return "claimed", self._from_row(row)

    def complete(
        self,
        idempotency_key: str,
        *,
        result: CapabilityResult | dict[str, Any],
        request_id: str | None = None,
    ) -> IdempotencyRecord | None:
        payload = result.public_dict() if isinstance(result, CapabilityResult) else dict(result)
        now = utc_now()
        with self.connect() as conn:
            self._ensure_schema(conn)
            cur = conn.execute(
                """
                UPDATE capability_idempotency
                SET status = ?, result_json = ?, updated_at = ?,
                    request_id = COALESCE(?, request_id)
                WHERE idempotency_key = ?
                """,
                (
                    IdempotencyRecordStatus.COMPLETED.value,
                    json.dumps(payload),
                    now,
                    request_id,
                    idempotency_key,
                ),
            )
            if cur.rowcount == 0:
                return None
            row = conn.execute(
                "SELECT * FROM capability_idempotency WHERE idempotency_key = ?",
                (idempotency_key,),
            ).fetchone()
        return self._from_row(row) if row else None

    def fail(
        self,
        idempotency_key: str,
        *,
        result: CapabilityResult | dict[str, Any] | None = None,
        request_id: str | None = None,
    ) -> IdempotencyRecord | None:
        payload = None
        if isinstance(result, CapabilityResult):
            payload = result.public_dict()
        elif isinstance(result, dict):
            payload = dict(result)
        now = utc_now()
        with self.connect() as conn:
            self._ensure_schema(conn)
            cur = conn.execute(
                """
                UPDATE capability_idempotency
                SET status = ?, result_json = ?, updated_at = ?,
                    request_id = COALESCE(?, request_id)
                WHERE idempotency_key = ?
                """,
                (
                    IdempotencyRecordStatus.FAILED.value,
                    json.dumps(payload) if payload is not None else None,
                    now,
                    request_id,
                    idempotency_key,
                ),
            )
            if cur.rowcount == 0:
                return None
            row = conn.execute(
                "SELECT * FROM capability_idempotency WHERE idempotency_key = ?",
                (idempotency_key,),
            ).fetchone()
        return self._from_row(row) if row else None

    @staticmethod
    def result_from_record(record: IdempotencyRecord, *, request_id: str) -> CapabilityResult | None:
        if not record.result_json:
            return None
        raw = record.result_json
        try:
            status = CapabilityStatus(str(raw.get("status") or "COMPLETED"))
        except ValueError:
            status = CapabilityStatus.COMPLETED
        from Data.modules.function_runtime.types import SideEffect

        side_effects: tuple[Any, ...] = ()
        try:
            side_effects = tuple(
                SideEffect(s) if not isinstance(s, SideEffect) else s
                for s in (raw.get("side_effects") or ())
            )
        except Exception:  # noqa: BLE001
            side_effects = ()
        return CapabilityResult(
            request_id=request_id,
            capability_id=str(raw.get("capability_id") or record.capability_id),
            status=status,
            output=raw.get("output") if isinstance(raw.get("output"), dict) else raw.get("output"),
            error=raw.get("error"),
            side_effects=side_effects,  # type: ignore[arg-type]
            provider_kind=raw.get("provider_kind"),
            provider_ref=raw.get("provider_ref"),
            approval_id=raw.get("approval_id"),
            telemetry={
                **dict(raw.get("telemetry") or {}),
                "original_request_id": str(raw.get("request_id") or record.request_id),
            },
        )

    @staticmethod
    def _from_row(row: sqlite3.Row) -> IdempotencyRecord:
        raw_result = row["result_json"]
        parsed = json.loads(raw_result) if raw_result else None
        return IdempotencyRecord(
            idempotency_key=row["idempotency_key"],
            fingerprint=row["fingerprint"],
            capability_id=row["capability_id"],
            status=IdempotencyRecordStatus(row["status"]),
            request_id=row["request_id"],
            result_json=parsed if isinstance(parsed, dict) else None,
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )


def new_request_id() -> str:
    return str(uuid.uuid4())
