"""DB Commit Coordinator writer — single external worker process logic."""

from __future__ import annotations

import os
import secrets
import threading
import time
import traceback
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from Data.modules.common.sqlite_policy import (
    is_transient_sqlite_error,
    open_sqlite_connection,
    run_with_busy_retry,
    sqlite_metrics_snapshot,
)
from Data.modules.db_commit.errors import (
    DbCommitError,
    InvalidIntentError,
    PayloadHashMismatchError,
    TerminalCommitError,
    UnknownOperationError,
)
from Data.modules.db_commit.handlers.registry import (
    CommitHandlerRegistry,
    build_default_registry,
    load_payload_json,
)
from Data.modules.db_commit.ipc import CommitIpcServer
from Data.modules.db_commit.receipts import CommitReceiptStore
from Data.modules.db_commit.settings import DbCommitSettings, load_db_commit_settings
from Data.modules.db_commit.spool import CommitSpool, SpoolItem
from Data.modules.db_commit.status import DbCommitStatus
from Data.modules.db_commit.types import (
    AckStatus,
    CommitHealth,
    CommitIntent,
    CommitReceipt,
    CommitReceiptStatus,
    FailureKind,
    WriterAck,
    utc_now,
)


@dataclass
class CoordinatorMetrics:
    commit_count: int = 0
    retry_count: int = 0
    busy_count: int = 0
    failed_count: int = 0
    quarantine_count: int = 0
    total_latency_ms: float = 0.0
    latencies_ms: list[float] = field(default_factory=list)
    last_applied_commit_id: str = ""
    inflight_commit_id: str = ""

    def record_latency(self, ms: float) -> None:
        self.latencies_ms.append(ms)
        if len(self.latencies_ms) > 256:
            self.latencies_ms = self.latencies_ms[-256:]
        self.total_latency_ms += ms

    def p95_latency_ms(self) -> float | None:
        if not self.latencies_ms:
            return None
        ordered = sorted(self.latencies_ms)
        idx = min(len(ordered) - 1, int(round(0.95 * (len(ordered) - 1))))
        return ordered[idx]


class DbCommitCoordinator:
    """Serialized COMMIT_WRITE authority. Managed by WorkerSupervisor as db_commit."""

    def __init__(
        self,
        db_path: Path | str,
        *,
        settings: DbCommitSettings | None = None,
        registry: CommitHandlerRegistry | None = None,
        worker_id: str | None = None,
    ) -> None:
        self.db_path = Path(db_path)
        self.settings = settings or load_db_commit_settings()
        self.registry = registry or build_default_registry()
        self.worker_id = worker_id or f"db_commit-{os.getpid()}"
        self.receipts = CommitReceiptStore(self.db_path)
        payloads_root = self.settings.payloads_root_for(self.db_path)
        self.spool = CommitSpool(
            self.settings.spool_root_for(self.db_path),
            settings=self.settings,
            allowed_payload_roots=[
                payloads_root,
                self.db_path.parent.resolve(),
            ],
        )
        self.metrics = CoordinatorMetrics()
        self._stop = threading.Event()
        self._draining = False
        self._ready = False
        self._ipc: CommitIpcServer | None = None
        self._token = secrets.token_hex(16)
        self._retries: dict[str, int] = {}
        self._started_at = time.time()
        self._lock = threading.Lock()

    @classmethod
    def from_env(cls, ctx: dict[str, Any]) -> DbCommitCoordinator:
        settings = ctx["settings"]
        worker_id = str(ctx.get("worker_id") or f"db_commit-{os.getpid()}")
        return cls(settings.database_path, worker_id=worker_id)

    def startup(self) -> None:
        self.spool.ensure_dirs()
        self.receipts.initialize()
        self._verify_schema()
        self.spool.recover_inflight(receipt_applied=self._receipt_exists)
        self._start_ipc()
        self._ready = True
        self._emit_db_writer(
            "writer gereed",
            message=f"pending={self.spool.stats().pending_count}",
        )

    def _verify_schema(self) -> None:
        conn = open_sqlite_connection(self.db_path)
        try:
            self.receipts.ensure_schema(conn)
            conn.commit()
        finally:
            conn.close()

    def _start_ipc(self) -> None:
        self._ipc = CommitIpcServer(
            self.db_path,
            on_intent=self.accept_intent,
            token=self._token,
        )
        self._ipc.start()

    def shutdown(self, *, drain_current: bool = True) -> None:
        self._draining = True
        if drain_current and self.metrics.inflight_commit_id:
            # Finish current only — do not drain multi-hour backlog.
            pass
        if self._ipc is not None:
            self._ipc.stop()
            self._ipc = None
        stats = self.spool.stats()
        self._emit_db_writer(
            "writer stopt",
            message=f"pending={stats.pending_count}",
        )
        self._stop.set()
        self._ready = False

    def accept_intent(self, intent: CommitIntent) -> WriterAck:
        """IPC accept path — durable spool immediately; process asynchronously."""
        if self._draining or self._stop.is_set():
            # Still spool so producers do not fall back to direct writes.
            try:
                self.spool.enqueue(intent, allow_critical=True, check_backpressure=False)
            except Exception as exc:  # noqa: BLE001
                return WriterAck(
                    status=AckStatus.SPOOL_UNAVAILABLE.value,
                    commit_id=intent.commit_id,
                    message=str(exc),
                )
            return WriterAck(
                status=AckStatus.ACCEPTED_TO_SPOOL.value,
                commit_id=intent.commit_id,
                message="draining",
            )

        existing = self.receipts.get_by_idempotency_key(intent.idempotency_key)
        if existing is not None:
            return WriterAck(
                status=AckStatus.ALREADY_APPLIED.value,
                commit_id=existing.commit_id,
                message="already applied",
                receipt=existing.to_dict(),
            )

        try:
            self.spool.enqueue(intent)
        except Exception as exc:  # noqa: BLE001
            code = getattr(exc, "code", "DB_COMMIT_ERROR")
            status = (
                AckStatus.BACKPRESSURE.value
                if code == "DB_COMMIT_BACKPRESSURE"
                else AckStatus.SPOOL_UNAVAILABLE.value
            )
            return WriterAck(status=status, commit_id=intent.commit_id, message=str(exc))

        title = intent.safe_human_title or intent.entity_id or intent.commit_id[:8]
        domain = intent.domain or intent.operation.split(".", 1)[0]
        self._emit_db_writer(
            f"{domain.title()} '{title}' commit ingepland",
            message=f"{intent.record_count_hint} records" if intent.record_count_hint else None,
            commit_id=intent.commit_id,
            human_title=title,
            domain=domain,
        )
        return WriterAck(
            status=AckStatus.ACCEPTED_TO_WRITER.value,
            commit_id=intent.commit_id,
            message="queued",
        )

    def run_forever(self) -> None:
        self.startup()
        while not self._stop.is_set():
            try:
                processed = self.process_one()
                if not processed:
                    self.spool.retain()
                    time.sleep(float(self.settings.poll_seconds))
            except Exception as exc:  # noqa: BLE001
                self._emit_db_writer(
                    "writer fout",
                    message=str(exc)[:200],
                    error_code="WRITER_LOOP_ERROR",
                )
                time.sleep(0.2)

    def process_one(self) -> bool:
        if not self._ready:
            return False
        item = self.spool.claim_next()
        if item is None:
            return False
        self._apply_item(item)
        return True

    def process_until_idle(self, *, max_items: int = 10_000) -> int:
        count = 0
        while count < max_items:
            if not self.process_one():
                break
            count += 1
        return count

    def _apply_item(self, item: SpoolItem) -> None:
        intent = item.intent
        title = intent.safe_human_title or intent.entity_id or intent.commit_id[:8]
        domain = intent.domain or intent.operation.split(".", 1)[0]
        self.metrics.inflight_commit_id = intent.commit_id
        started = time.perf_counter()

        # Crash-after-commit recovery: receipt already present.
        existing = self.receipts.get_by_idempotency_key(intent.idempotency_key)
        if existing is None:
            existing = self.receipts.get_by_commit_id(intent.commit_id)
        if existing is not None:
            self.spool.finalize_applied(item)
            self.metrics.inflight_commit_id = ""
            self.metrics.last_applied_commit_id = existing.commit_id
            return

        self._emit_db_writer(
            f"{domain.title()} '{title}' commit gestart",
            message=(
                f"{intent.record_count_hint} records"
                if intent.record_count_hint
                else None
            ),
            commit_id=intent.commit_id,
            human_title=title,
            domain=domain,
        )

        try:
            payload_path = self.spool.validate_payload(intent)
            # Heavy read/parse OUTSIDE SQLite transaction.
            payload = load_payload_json(payload_path)
            handler = self.registry.get(intent.operation)

            def _apply() -> CommitReceipt:
                return handler.apply(
                    intent,
                    payload,
                    db_path=self.db_path,
                    settings=self.settings,
                )

            receipt = run_with_busy_retry(_apply)
            # Persist canonical receipt (idempotency).
            if not receipt.applied_at:
                receipt.applied_at = utc_now()
            if not receipt.commit_id:
                receipt.commit_id = intent.commit_id
            if not receipt.idempotency_key:
                receipt.idempotency_key = intent.idempotency_key

            def _persist() -> None:
                self.receipts.persist(receipt)

            run_with_busy_retry(_persist)
            if intent.batch_count > 1:
                conn = open_sqlite_connection(self.db_path)
                try:
                    self.receipts.mark_batch_applied(
                        conn,
                        commit_id=intent.commit_id,
                        batch_index=intent.batch_index,
                        batch_count=intent.batch_count,
                        batch_hash=intent.batch_hash,
                        record_count=receipt.record_count,
                    )
                    conn.commit()
                finally:
                    conn.close()

            self.spool.finalize_applied(item)
            duration_ms = (time.perf_counter() - started) * 1000.0
            self.metrics.commit_count += 1
            self.metrics.record_latency(duration_ms)
            self.metrics.last_applied_commit_id = intent.commit_id
            self._retries.pop(intent.commit_id, None)
            self._emit_db_writer(
                f"{domain.title()} '{title}' commit voltooid",
                message=f"{receipt.record_count} records — {duration_ms:.0f}ms",
                commit_id=intent.commit_id,
                human_title=title,
                domain=domain,
                duration_ms=duration_ms,
                progress_current=receipt.record_count,
            )
        except Exception as exc:  # noqa: BLE001
            self._handle_failure(item, exc, title=title, domain=domain)
        finally:
            self.metrics.inflight_commit_id = ""

    def _handle_failure(
        self,
        item: SpoolItem,
        exc: BaseException,
        *,
        title: str,
        domain: str,
    ) -> None:
        intent = item.intent
        kind = self._classify_failure(exc)
        attempts = self._retries.get(intent.commit_id, 0) + 1
        self._retries[intent.commit_id] = attempts
        self.metrics.retry_count += 1
        code = getattr(exc, "code", type(exc).__name__)

        if is_transient_sqlite_error(exc):
            self.metrics.busy_count += 1
            self._emit_db_writer(
                f"{domain.title()} '{title}' commit retry — SQLITE_BUSY",
                commit_id=intent.commit_id,
                human_title=title,
                domain=domain,
                error_code="SQLITE_BUSY",
                attempt=attempts,
            )

        if kind == FailureKind.TERMINAL or attempts > int(self.settings.retry_limit):
            self.metrics.failed_count += 1
            if isinstance(exc, (PayloadHashMismatchError, InvalidIntentError, UnknownOperationError)):
                self.metrics.quarantine_count += 1
                self.spool.quarantine(item.path, reason=str(code))
                self._emit_db_writer(
                    f"Commit {intent.commit_id[:8]} in quarantaine — {code}",
                    commit_id=intent.commit_id,
                    error_code=str(code),
                    domain=domain,
                )
            else:
                self.spool.mark_failed(item, reason=f"{code}: {exc}")
                self._emit_db_writer(
                    f"Commit {intent.commit_id[:8]} MISLUKT — {code}",
                    commit_id=intent.commit_id,
                    error_code=str(code),
                    domain=domain,
                )
            return

        # Retryable: return to pending.
        self.spool.return_to_pending(item)
        time.sleep(min(0.5, 0.05 * attempts))

    def _classify_failure(self, exc: BaseException) -> FailureKind:
        if is_transient_sqlite_error(exc):
            return FailureKind.RETRYABLE
        if isinstance(
            exc,
            (
                PayloadHashMismatchError,
                InvalidIntentError,
                UnknownOperationError,
                TerminalCommitError,
                ValueError,
                TypeError,
                KeyError,
                AttributeError,
                ImportError,
                ModuleNotFoundError,
            ),
        ):
            return FailureKind.TERMINAL
        if isinstance(exc, DbCommitError):
            code = getattr(exc, "code", "")
            if code in {
                "PAYLOAD_HASH_MISMATCH",
                "INVALID_INTENT",
                "UNKNOWN_OPERATION",
                "FORBIDDEN_PAYLOAD_PATH",
            }:
                return FailureKind.TERMINAL
        if isinstance(exc, OSError):
            return FailureKind.RETRYABLE
        return FailureKind.RETRYABLE

    def _receipt_exists(self, intent: CommitIntent) -> bool:
        if self.receipts.get_by_commit_id(intent.commit_id) is not None:
            return True
        if intent.idempotency_key and self.receipts.get_by_idempotency_key(
            intent.idempotency_key
        ):
            return True
        return False

    def status(self) -> DbCommitStatus:
        stats = self.spool.stats()
        soft = self.settings.soft_backpressure_threshold
        hard = self.settings.hard_backpressure_threshold
        count_ratio = stats.pending_count / max(1, self.settings.max_pending_count)
        bytes_ratio = stats.pending_bytes / max(1, self.settings.max_pending_bytes)
        health = CommitHealth.HEALTHY
        if not self._ready or self._stop.is_set():
            health = CommitHealth.FAILED
        elif count_ratio >= hard or bytes_ratio >= hard:
            health = CommitHealth.BACKPRESSURED
        elif (
            count_ratio >= soft
            or bytes_ratio >= soft
            or stats.oldest_pending_age_seconds > 300
            or self.metrics.retry_count > 0
        ):
            health = CommitHealth.DEGRADED
        sqlite_m = sqlite_metrics_snapshot()
        return DbCommitStatus(
            health=health.value,
            worker_id=self.worker_id,
            worker_pid=os.getpid(),
            ready=self._ready,
            draining=self._draining,
            queue_depth=stats.pending_count,
            pending_bytes=stats.pending_bytes,
            oldest_pending_age_seconds=stats.oldest_pending_age_seconds,
            inflight_commit_id=self.metrics.inflight_commit_id,
            last_applied_commit_id=self.metrics.last_applied_commit_id,
            commit_count=self.metrics.commit_count,
            retry_count=self.metrics.retry_count,
            busy_count=self.metrics.busy_count + int(sqlite_m.get("sqlite_busy_count") or 0),
            failed_count=self.metrics.failed_count,
            quarantine_count=self.metrics.quarantine_count + stats.quarantine_count,
            average_commit_latency_ms=(
                self.metrics.total_latency_ms / self.metrics.commit_count
                if self.metrics.commit_count
                else 0.0
            ),
            p95_commit_latency_ms=self.metrics.p95_latency_ms(),
            apply_rate_per_minute=self._apply_rate_per_minute(),
        )

    def _apply_rate_per_minute(self) -> float:
        elapsed_min = max(1e-6, (time.time() - self._started_at) / 60.0)
        return float(self.metrics.commit_count) / elapsed_min

    def _emit_db_writer(
        self,
        text: str,
        *,
        message: str | None = None,
        commit_id: str | None = None,
        human_title: str | None = None,
        domain: str | None = None,
        duration_ms: float | None = None,
        error_code: str | None = None,
        attempt: int | None = None,
        progress_current: int | None = None,
    ) -> None:
        line = f"[DB-WRITER] {text}"
        if message:
            line = f"{line} — {message}"
        print(line, flush=True)
        try:
            from Data.modules.workers.events import (
                WorkerEvent,
                WorkerEventKind,
                get_worker_event_emitter,
                utc_timestamp,
            )

            kind = WorkerEventKind.JOB_PROGRESS
            if error_code:
                kind = WorkerEventKind.JOB_FAILED
            elif "voltooid" in text:
                kind = WorkerEventKind.JOB_COMPLETED
            elif "gestart" in text and "pool" not in text:
                kind = WorkerEventKind.JOB_STARTED
            elif "ingepland" in text:
                kind = WorkerEventKind.JOB_QUEUED
            get_worker_event_emitter().emit(
                WorkerEvent(
                    event=kind,
                    timestamp=utc_timestamp(),
                    pool="db_commit",
                    worker_id=self.worker_id,
                    worker_pid=os.getpid(),
                    job_id=commit_id,
                    domain=domain or "db_commit",
                    human_title=human_title,
                    duration_ms=duration_ms,
                    error_code=error_code,
                    attempt=attempt,
                    progress_current=progress_current,
                    message=text,
                    extra={"channel": "DB-WRITER"},
                )
            )
        except Exception:  # noqa: BLE001
            pass
