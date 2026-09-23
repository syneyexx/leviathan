"""Durable inference / serving requests — survive disconnect & restart without duplicating side effects.

Round 6: long-running work must survive API disconnect, frontend reload, worker
restart, and application restart (where architecture supports it) without
replaying irreversible side effects.
"""

from __future__ import annotations

import threading
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any

from .serving import InferenceJobClass


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


class DurableRequestStatus(str, Enum):
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"
    INTERRUPTED = "INTERRUPTED"
    FAILED = "FAILED"


@dataclass
class DurableServingRequest:
    request_id: str
    idempotency_key: str
    status: DurableRequestStatus
    job_class: InferenceJobClass
    model_id: str
    provider_id: str
    created_at: str
    updated_at: str
    result: dict[str, Any] | None = None
    error: str | None = None
    side_effect_fingerprint: str | None = None
    cancel_reason: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def public_dict(self) -> dict[str, Any]:
        return {
            "request_id": self.request_id,
            "idempotency_key": self.idempotency_key,
            "status": self.status.value,
            "job_class": self.job_class.value,
            "model_id": self.model_id,
            "provider_id": self.provider_id,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "result": self.result,
            "error": self.error,
            "side_effect_fingerprint": self.side_effect_fingerprint,
            "cancel_reason": self.cancel_reason,
            "metadata": dict(self.metadata),
            "truth": {
                "idempotent_replay_does_not_duplicate_side_effects": True,
                "interrupted_is_not_running": self.status != DurableRequestStatus.RUNNING,
                "disconnect_does_not_kill_durable_work": True,
            },
        }


class DurableRequestLedger:
    """In-process ledger keyed by idempotency. Restart → interrupt active rows."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._by_id: dict[str, DurableServingRequest] = {}
        self._by_key: dict[str, str] = {}

    def begin(
        self,
        *,
        idempotency_key: str,
        model_id: str,
        provider_id: str,
        job_class: InferenceJobClass = InferenceJobClass.INTERACTIVE,
        metadata: dict[str, Any] | None = None,
    ) -> tuple[DurableServingRequest, bool]:
        """Return (request, is_replay). Replay of COMPLETED returns prior result."""
        with self._lock:
            existing_id = self._by_key.get(idempotency_key)
            if existing_id:
                existing = self._by_id[existing_id]
                if existing.status == DurableRequestStatus.COMPLETED:
                    return existing, True
                if existing.status == DurableRequestStatus.RUNNING:
                    return existing, True
                if existing.status == DurableRequestStatus.PENDING:
                    existing.status = DurableRequestStatus.RUNNING
                    existing.updated_at = _utc_now()
                    return existing, False
                # INTERRUPTED / FAILED / CANCELLED → reopen as new attempt under same key
                # but mark prior fingerprint so callers can avoid side-effect duplication.
            now = _utc_now()
            request_id = str(uuid.uuid4())
            req = DurableServingRequest(
                request_id=request_id,
                idempotency_key=idempotency_key,
                status=DurableRequestStatus.RUNNING,
                job_class=job_class,
                model_id=model_id,
                provider_id=provider_id,
                created_at=now,
                updated_at=now,
                metadata=dict(metadata or {}),
            )
            if existing_id:
                prior = self._by_id[existing_id]
                req.side_effect_fingerprint = prior.side_effect_fingerprint
                req.metadata["reopened_from"] = prior.request_id
                req.metadata["prior_status"] = prior.status.value
            self._by_id[request_id] = req
            self._by_key[idempotency_key] = request_id
            return req, False

    def complete(
        self,
        request_id: str,
        *,
        result: dict[str, Any],
        side_effect_fingerprint: str | None = None,
    ) -> DurableServingRequest:
        with self._lock:
            req = self._by_id[request_id]
            req.status = DurableRequestStatus.COMPLETED
            req.result = result
            if side_effect_fingerprint is not None:
                req.side_effect_fingerprint = side_effect_fingerprint
            req.updated_at = _utc_now()
            return req

    def fail(self, request_id: str, error: str) -> DurableServingRequest:
        with self._lock:
            req = self._by_id[request_id]
            req.status = DurableRequestStatus.FAILED
            req.error = error
            req.updated_at = _utc_now()
            return req

    def cancel(self, request_id: str, reason: str = "client_disconnect") -> DurableServingRequest:
        with self._lock:
            req = self._by_id[request_id]
            if req.status in (
                DurableRequestStatus.COMPLETED,
                DurableRequestStatus.FAILED,
                DurableRequestStatus.CANCELLED,
            ):
                return req
            req.status = DurableRequestStatus.CANCELLED
            req.cancel_reason = reason
            req.updated_at = _utc_now()
            return req

    def mark_interrupted(self, request_id: str, reason: str) -> DurableServingRequest:
        with self._lock:
            req = self._by_id[request_id]
            if req.status != DurableRequestStatus.RUNNING:
                return req
            req.status = DurableRequestStatus.INTERRUPTED
            req.error = reason
            req.updated_at = _utc_now()
            return req

    def reconcile_on_restart(self) -> list[DurableServingRequest]:
        """Application restart: RUNNING is not current truth → INTERRUPTED."""
        changed: list[DurableServingRequest] = []
        with self._lock:
            for req in self._by_id.values():
                if req.status == DurableRequestStatus.RUNNING:
                    req.status = DurableRequestStatus.INTERRUPTED
                    req.error = req.error or "application_restart"
                    req.metadata["reconcile_note"] = "process restart — prior RUNNING is not current truth"
                    req.updated_at = _utc_now()
                    changed.append(req)
        return changed

    def get(self, request_id: str) -> DurableServingRequest | None:
        with self._lock:
            return self._by_id.get(request_id)

    def get_by_idempotency(self, key: str) -> DurableServingRequest | None:
        with self._lock:
            rid = self._by_key.get(key)
            return self._by_id.get(rid) if rid else None

    def list_active(self) -> list[DurableServingRequest]:
        with self._lock:
            return [
                r
                for r in self._by_id.values()
                if r.status in (DurableRequestStatus.PENDING, DurableRequestStatus.RUNNING)
            ]


_LEDGER: DurableRequestLedger | None = None
_LEDGER_LOCK = threading.Lock()


def get_durable_request_ledger() -> DurableRequestLedger:
    global _LEDGER
    with _LEDGER_LOCK:
        if _LEDGER is None:
            _LEDGER = DurableRequestLedger()
        return _LEDGER


def reset_durable_request_ledger_for_tests() -> DurableRequestLedger:
    global _LEDGER
    with _LEDGER_LOCK:
        _LEDGER = DurableRequestLedger()
        return _LEDGER
