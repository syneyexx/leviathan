"""SEALED attempt semantics — one genuine holdout exposure (P1A / Master §17).

Rules:
- First exposure binds ``sealed_attempt_id`` + ``run_id``.
- Crash/restart: same attempt + same run + checkpoint resume (never from bar 0
  unless the attempt genuinely never advanced).
- Never start a new attempt for the same (dataset_version, strategy_version)
  while one is BOUND/RUNNING, or after COMPLETED (single-use holdout).
- Strategy adaptation after disclosure requires a NEW strategy_version (later
  slices); this module only enforces attempt binding.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Protocol

from .types import MarketSimError


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class SealedAttemptStatus:
    BOUND = "BOUND"
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    ABORTED = "ABORTED"


_ACTIVE = {SealedAttemptStatus.BOUND, SealedAttemptStatus.RUNNING, SealedAttemptStatus.FAILED}
_TERMINAL_CONSUMED = {SealedAttemptStatus.COMPLETED}


@dataclass
class SealedAttempt:
    sealed_attempt_id: str
    dataset_id: str
    dataset_version: str
    split_manifest_id: str
    strategy_id: str
    strategy_version: int
    run_id: str
    status: str
    bound_at: str
    checkpoint_bar_index: int = 0
    completed_at: str | None = None
    failure_reason: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def version_key(self) -> str:
        return f"{self.dataset_id}@{self.dataset_version}"

    def public_dict(self) -> dict[str, Any]:
        return {
            "sealed_attempt_id": self.sealed_attempt_id,
            "dataset_id": self.dataset_id,
            "dataset_version": self.dataset_version,
            "version_key": self.version_key,
            "split_manifest_id": self.split_manifest_id,
            "strategy_id": self.strategy_id,
            "strategy_version": self.strategy_version,
            "run_id": self.run_id,
            "status": self.status,
            "bound_at": self.bound_at,
            "checkpoint_bar_index": self.checkpoint_bar_index,
            "completed_at": self.completed_at,
            "failure_reason": self.failure_reason,
            "metadata": self.metadata,
            "truth": {
                "single_use_holdout": True,
                "crash_resumes_same_attempt": True,
                "never_restart_from_beginning": True,
                "no_strategy_adaptation_mid_attempt": True,
            },
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "SealedAttempt":
        return cls(
            sealed_attempt_id=str(payload["sealed_attempt_id"]),
            dataset_id=str(payload["dataset_id"]),
            dataset_version=str(payload["dataset_version"]),
            split_manifest_id=str(payload.get("split_manifest_id") or ""),
            strategy_id=str(payload["strategy_id"]),
            strategy_version=int(payload.get("strategy_version") or 0),
            run_id=str(payload["run_id"]),
            status=str(payload["status"]),
            bound_at=str(payload.get("bound_at") or ""),
            checkpoint_bar_index=int(payload.get("checkpoint_bar_index") or 0),
            completed_at=payload.get("completed_at"),
            failure_reason=str(payload.get("failure_reason") or ""),
            metadata=dict(payload.get("metadata") or {}),
        )


class SealedAttemptStore(Protocol):
    def get_sealed_attempt(self, sealed_attempt_id: str) -> dict[str, Any] | None: ...

    def find_sealed_attempt(
        self,
        *,
        dataset_id: str,
        dataset_version: str,
        strategy_id: str,
        strategy_version: int,
    ) -> dict[str, Any] | None: ...

    def upsert_sealed_attempt(self, attempt: dict[str, Any]) -> dict[str, Any]: ...

    def list_sealed_attempts_for_strategy_dataset(
        self,
        *,
        dataset_id: str,
        dataset_version: str,
        strategy_id: str,
    ) -> list[dict[str, Any]]: ...


class SealedAttemptBinder:
    """Canonical owner of SEALED single-attempt binding."""

    def __init__(self, store: SealedAttemptStore) -> None:
        self.store = store

    def _lineage_consumed(
        self,
        *,
        dataset_id: str,
        dataset_version: str,
        strategy_id: str,
        strategy_version: int,
        objective_hash: str,
        split_manifest_id: str,
        exclude_attempt_id: str | None = None,
    ) -> dict[str, Any] | None:
        """Return a COMPLETED attempt that already disclosed this holdout lineage.

        Adapted strategy versions share the strategy_id contamination root for a
        given dataset/version (+ optional objective). Disclosed holdouts stay
        disclosed — a new strategy version cannot re-qualify on the same SEALED.
        """
        lister = getattr(self.store, "list_sealed_attempts_for_strategy_dataset", None)
        if lister is None:
            return None
        rows = lister(
            dataset_id=dataset_id,
            dataset_version=dataset_version,
            strategy_id=strategy_id,
        )
        for raw in rows or []:
            if exclude_attempt_id and str(raw.get("sealed_attempt_id")) == exclude_attempt_id:
                continue
            if str(raw.get("status")) not in _TERMINAL_CONSUMED:
                continue
            meta = dict(raw.get("metadata") or {})
            # Exact version resume is handled elsewhere; here we catch *other*
            # versions / objective-compatible disclosures on the same holdout.
            other_version = int(raw.get("strategy_version") or 0)
            if other_version == int(strategy_version):
                # Same version — bind_or_resume handles single-use.
                continue
            other_obj = str(meta.get("objective_hash") or "")
            if objective_hash and other_obj and other_obj != objective_hash:
                # Distinct objective lineage may use a fresh protocol only when
                # the holdout dataset/version itself is new. Same disclosed
                # dataset remains contaminated for adapted strategies.
                pass
            other_manifest = str(raw.get("split_manifest_id") or "")
            if split_manifest_id and other_manifest and other_manifest != split_manifest_id:
                continue
            return raw
        return None

    def bind_or_resume(
        self,
        *,
        dataset_id: str,
        dataset_version: str,
        split_manifest_id: str,
        strategy_id: str,
        strategy_version: int,
        run_id: str,
        sealed_attempt_id: str | None = None,
        objective_hash: str | None = None,
        allow_resume_run_id: bool = True,
        metadata: dict[str, Any] | None = None,
    ) -> SealedAttempt:
        """First exposure binds; crash/restart with same run resumes."""
        obj_hash = str(objective_hash or (metadata or {}).get("objective_hash") or "")
        existing_raw = None
        if sealed_attempt_id:
            existing_raw = self.store.get_sealed_attempt(sealed_attempt_id)
        if existing_raw is None:
            existing_raw = self.store.find_sealed_attempt(
                dataset_id=dataset_id,
                dataset_version=dataset_version,
                strategy_id=strategy_id,
                strategy_version=strategy_version,
            )

        # Adapted strategy version after disclosure → refuse same holdout.
        consumed = self._lineage_consumed(
            dataset_id=dataset_id,
            dataset_version=dataset_version,
            strategy_id=strategy_id,
            strategy_version=strategy_version,
            objective_hash=obj_hash,
            split_manifest_id=split_manifest_id,
            exclude_attempt_id=str((existing_raw or {}).get("sealed_attempt_id") or "") or None,
        )
        if consumed is not None and existing_raw is None:
            raise MarketSimError(
                "HOLDOUT_LINEAGE_CONTAMINATED",
                "adapted strategy versions cannot re-qualify on a disclosed SEALED holdout; "
                "require a new dataset version / untouched holdout lineage "
                f"(prior_attempt={consumed.get('sealed_attempt_id')})",
                http_status=409,
            )

        if existing_raw is None:
            meta = dict(metadata or {})
            if obj_hash:
                meta.setdefault("objective_hash", obj_hash)
            attempt = SealedAttempt(
                sealed_attempt_id=sealed_attempt_id or str(uuid.uuid4()),
                dataset_id=dataset_id,
                dataset_version=dataset_version,
                split_manifest_id=split_manifest_id,
                strategy_id=strategy_id,
                strategy_version=strategy_version,
                run_id=run_id,
                status=SealedAttemptStatus.BOUND,
                bound_at=utc_now(),
                checkpoint_bar_index=0,
                metadata=meta,
            )
            self.store.upsert_sealed_attempt(attempt.public_dict())
            return attempt

        existing = SealedAttempt.from_dict(existing_raw)
        if existing.status in _TERMINAL_CONSUMED:
            raise MarketSimError(
                "SEALED_ALREADY_CONSUMED",
                f"SEALED holdout already completed for "
                f"{strategy_id}@v{strategy_version} on {dataset_id}@{dataset_version} "
                f"(attempt={existing.sealed_attempt_id})",
                http_status=409,
            )
        if existing.run_id != run_id:
            if allow_resume_run_id and existing.status in _ACTIVE:
                # Crash/retry with a new ephemeral run_id: resume the bound run.
                # Callers must continue the original run_id for deterministic resume.
                raise MarketSimError(
                    "SEALED_ATTEMPT_BOUND_TO_OTHER_RUN",
                    f"attempt {existing.sealed_attempt_id} bound to run {existing.run_id}, "
                    f"refusing new run {run_id}; resume the original run_id "
                    f"(resume_run_id={existing.run_id})",
                    http_status=409,
                )
            raise MarketSimError(
                "SEALED_ATTEMPT_BOUND_TO_OTHER_RUN",
                f"attempt {existing.sealed_attempt_id} bound to run {existing.run_id}, "
                f"refusing new run {run_id}",
                http_status=409,
            )
        if existing.status not in _ACTIVE and existing.status != SealedAttemptStatus.ABORTED:
            raise MarketSimError(
                "SEALED_ATTEMPT_INVALID_STATE",
                f"cannot resume attempt in status={existing.status}",
                http_status=409,
            )
        # Resume same attempt — never reset checkpoint to 0
        if existing.status == SealedAttemptStatus.FAILED:
            existing.status = SealedAttemptStatus.RUNNING
            existing.failure_reason = ""
            self.store.upsert_sealed_attempt(existing.public_dict())
        return existing

    def mark_running(self, sealed_attempt_id: str, *, checkpoint_bar_index: int | None = None) -> SealedAttempt:
        raw = self.store.get_sealed_attempt(sealed_attempt_id)
        if raw is None:
            raise MarketSimError("SEALED_ATTEMPT_NOT_FOUND", sealed_attempt_id, http_status=404)
        attempt = SealedAttempt.from_dict(raw)
        if attempt.status in _TERMINAL_CONSUMED:
            raise MarketSimError("SEALED_ALREADY_CONSUMED", sealed_attempt_id, http_status=409)
        attempt.status = SealedAttemptStatus.RUNNING
        if checkpoint_bar_index is not None:
            # Never rewind
            attempt.checkpoint_bar_index = max(attempt.checkpoint_bar_index, int(checkpoint_bar_index))
        self.store.upsert_sealed_attempt(attempt.public_dict())
        return attempt

    def checkpoint(self, sealed_attempt_id: str, *, bar_index: int) -> SealedAttempt:
        raw = self.store.get_sealed_attempt(sealed_attempt_id)
        if raw is None:
            raise MarketSimError("SEALED_ATTEMPT_NOT_FOUND", sealed_attempt_id, http_status=404)
        attempt = SealedAttempt.from_dict(raw)
        if attempt.status in _TERMINAL_CONSUMED:
            raise MarketSimError("SEALED_ALREADY_CONSUMED", sealed_attempt_id, http_status=409)
        if int(bar_index) < attempt.checkpoint_bar_index:
            raise MarketSimError(
                "SEALED_CHECKPOINT_REWIND",
                f"refusing rewind {attempt.checkpoint_bar_index} -> {bar_index}",
                http_status=409,
            )
        attempt.checkpoint_bar_index = int(bar_index)
        if attempt.status == SealedAttemptStatus.BOUND:
            attempt.status = SealedAttemptStatus.RUNNING
        self.store.upsert_sealed_attempt(attempt.public_dict())
        return attempt

    def complete(self, sealed_attempt_id: str) -> SealedAttempt:
        raw = self.store.get_sealed_attempt(sealed_attempt_id)
        if raw is None:
            raise MarketSimError("SEALED_ATTEMPT_NOT_FOUND", sealed_attempt_id, http_status=404)
        attempt = SealedAttempt.from_dict(raw)
        if attempt.status in _TERMINAL_CONSUMED:
            return attempt
        attempt.status = SealedAttemptStatus.COMPLETED
        attempt.completed_at = utc_now()
        self.store.upsert_sealed_attempt(attempt.public_dict())
        return attempt

    def fail(self, sealed_attempt_id: str, *, reason: str) -> SealedAttempt:
        raw = self.store.get_sealed_attempt(sealed_attempt_id)
        if raw is None:
            raise MarketSimError("SEALED_ATTEMPT_NOT_FOUND", sealed_attempt_id, http_status=404)
        attempt = SealedAttempt.from_dict(raw)
        if attempt.status in _TERMINAL_CONSUMED:
            raise MarketSimError("SEALED_ALREADY_CONSUMED", sealed_attempt_id, http_status=409)
        attempt.status = SealedAttemptStatus.FAILED
        attempt.failure_reason = reason
        self.store.upsert_sealed_attempt(attempt.public_dict())
        return attempt
