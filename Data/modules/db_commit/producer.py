"""Producer API — submit CommitIntent via IPC with durable spool fallback.

ACCEPTED_TO_WRITER / ACCEPTED_TO_SPOOL is NOT COMMITTED.
Durable completion requires a CommitReceipt.
"""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from Data.modules.common.atomic import atomic_write_bytes, ensure_dir
from Data.modules.common.hashing import sha256_bytes, sha256_file

from .errors import DbCommitBackpressureError, DbCommitSpoolUnavailableError
from .ipc import CommitIpcClient
from .receipts import CommitReceiptStore
from .settings import DbCommitSettings, load_db_commit_settings
from .spool import CommitSpool
from .types import AckStatus, CommitIntent, CommitPriority, CommitReceipt


@dataclass
class SubmitResult:
    ack_status: str
    commit_id: str
    intent: CommitIntent
    receipt: CommitReceipt | None = None
    message: str = ""

    @property
    def accepted(self) -> bool:
        return self.ack_status in {
            AckStatus.ACCEPTED_TO_WRITER.value,
            AckStatus.ACCEPTED_TO_SPOOL.value,
            AckStatus.ALREADY_APPLIED.value,
        }

    @property
    def committed(self) -> bool:
        return self.receipt is not None and self.ack_status == AckStatus.ALREADY_APPLIED.value

    def public_dict(self) -> dict[str, Any]:
        return {
            "ackStatus": self.ack_status,
            "commitId": self.commit_id,
            "committed": self.committed,
            "message": self.message,
            "receipt": self.receipt.to_dict() if self.receipt else None,
        }


class CommitProducer:
    """Domain producers use this — never submit raw SQL / arbitrary callables."""

    def __init__(
        self,
        db_path: Path | str,
        *,
        settings: DbCommitSettings | None = None,
        spool: CommitSpool | None = None,
        receipts: CommitReceiptStore | None = None,
    ) -> None:
        self.db_path = Path(db_path)
        self.settings = settings or load_db_commit_settings()
        self.payloads_root = self.settings.payloads_root_for(self.db_path)
        ensure_dir(self.payloads_root)
        self.spool = spool or CommitSpool(
            self.settings.spool_root_for(self.db_path),
            settings=self.settings,
            allowed_payload_roots=[
                self.payloads_root,
                self.db_path.parent,
                Path(self.db_path).resolve().parent,
            ],
        )
        self.receipts = receipts or CommitReceiptStore(self.db_path)
        self.ipc = CommitIpcClient(
            self.db_path,
            timeout_seconds=self.settings.ipc_timeout_seconds,
        )

    def write_payload(self, payload: dict[str, Any], *, name: str | None = None) -> tuple[Path, str]:
        """Atomically write an immutable prepared payload under approved roots."""
        ensure_dir(self.payloads_root)
        raw = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        digest = sha256_bytes(raw)
        filename = name or f"{digest[:16]}_{uuid.uuid4().hex[:8]}.json"
        path = self.payloads_root / filename
        if not path.exists():
            atomic_write_bytes(path, raw)
        return path, digest

    def submit(
        self,
        *,
        operation: str,
        domain: str,
        payload: dict[str, Any] | None = None,
        payload_ref: str | Path | None = None,
        payload_hash: str | None = None,
        idempotency_key: str | None = None,
        priority: CommitPriority | str = CommitPriority.P2_DOMAIN,
        entity_type: str = "",
        entity_id: str = "",
        record_count_hint: int = 0,
        safe_human_title: str = "",
        source_job_id: str = "",
        producer_worker_id: str = "",
        trace_id: str = "",
        sequence_key: str = "",
        sequence_number: int = 0,
        metadata: dict[str, Any] | None = None,
        batch_index: int = 0,
        batch_count: int = 1,
        allow_critical: bool = False,
    ) -> SubmitResult:
        if not self.settings.enabled:
            raise DbCommitSpoolUnavailableError("db_commit disabled")

        # Idempotency short-circuit against durable receipts.
        if idempotency_key:
            existing = self.receipts.get_by_idempotency_key(idempotency_key)
            if existing is not None:
                intent = CommitIntent.create(
                    operation=operation,
                    domain=domain,
                    idempotency_key=idempotency_key,
                    commit_id=existing.commit_id,
                    entity_type=entity_type,
                    entity_id=entity_id,
                    safe_human_title=safe_human_title,
                )
                return SubmitResult(
                    ack_status=AckStatus.ALREADY_APPLIED.value,
                    commit_id=existing.commit_id,
                    intent=intent,
                    receipt=existing,
                    message="already applied",
                )

        ref = ""
        digest = payload_hash or ""
        estimated = 0
        if payload is not None:
            path, digest = self.write_payload(payload)
            ref = str(path)
            estimated = path.stat().st_size
        elif payload_ref is not None:
            path = Path(payload_ref)
            if not path.is_absolute():
                path = (self.payloads_root / path).resolve()
            if not digest:
                digest = sha256_file(path)
            ref = str(path)
            estimated = path.stat().st_size if path.is_file() else 0
        else:
            # Empty payload ops (noop) still need a stable empty hash ref.
            path, digest = self.write_payload({"_empty": True})
            ref = str(path)

        intent = CommitIntent.create(
            operation=operation,
            domain=domain,
            idempotency_key=idempotency_key,
            entity_type=entity_type,
            entity_id=entity_id,
            payload_ref=ref,
            payload_hash=digest,
            priority=priority,
            record_count_hint=record_count_hint or int((payload or {}).get("_record_count") or 0),
            estimated_bytes=estimated,
            producer_worker_id=producer_worker_id,
            source_job_id=source_job_id,
            trace_id=trace_id,
            sequence_key=sequence_key,
            sequence_number=sequence_number,
            safe_human_title=safe_human_title,
            metadata=metadata,
            batch_index=batch_index,
            batch_count=batch_count,
        )

        # Fast path: IPC to live writer.
        ack = self.ipc.submit(intent)
        if ack is not None and ack.status in {
            AckStatus.ACCEPTED_TO_WRITER.value,
            AckStatus.ACCEPTED_TO_SPOOL.value,
            AckStatus.ALREADY_APPLIED.value,
        }:
            receipt = None
            if ack.receipt:
                receipt = CommitReceipt.from_dict(ack.receipt)
            return SubmitResult(
                ack_status=ack.status,
                commit_id=intent.commit_id,
                intent=intent,
                receipt=receipt,
                message=ack.message,
            )

        # Durable fallback — never fall back to direct heavy SQLite write.
        try:
            self.spool.enqueue(intent, allow_critical=allow_critical)
        except DbCommitBackpressureError as exc:
            return SubmitResult(
                ack_status=AckStatus.BACKPRESSURE.value,
                commit_id=intent.commit_id,
                intent=intent,
                message=str(exc),
            )
        except DbCommitSpoolUnavailableError as exc:
            return SubmitResult(
                ack_status=AckStatus.SPOOL_UNAVAILABLE.value,
                commit_id=intent.commit_id,
                intent=intent,
                message=str(exc),
            )

        return SubmitResult(
            ack_status=AckStatus.ACCEPTED_TO_SPOOL.value,
            commit_id=intent.commit_id,
            intent=intent,
            message="spooled",
        )
