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

from Data.modules.common.database_domains import (
    DatabaseDomain,
    DatabasePaths,
    domain_from_commit_operation,
)
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


@dataclass
class _CommitLane:
    domain: DatabaseDomain
    db_path: Path
    spool: CommitSpool
    receipts: CommitReceiptStore
    metrics: CoordinatorMetrics
    ipc: CommitIpcServer | None = None


class DbCommitCoordinator:
    """Database-aware COMMIT_WRITE authority with independent Control/Knowledge/Market lanes.

    Managed by WorkerSupervisor as pool ``db_commit``. Independent databases may
    commit concurrently; each SQLite file still has one serialized lane.
    """

    def __init__(
        self,
        db_path: Path | str | DatabasePaths,
        *,
        settings: DbCommitSettings | None = None,
        registry: CommitHandlerRegistry | None = None,
        worker_id: str | None = None,
    ) -> None:
        self.settings = settings or load_db_commit_settings()
        self.registry = registry or build_default_registry()
        self.worker_id = worker_id or f"db_commit-{os.getpid()}"
        if isinstance(db_path, DatabasePaths):
            self.paths = db_path
        else:
            single = Path(db_path)
            # Test / single-file compat: all domains share one physical DB file,
            # but spool directories remain domain-keyed to avoid collisions.
            self.paths = DatabasePaths(
                control=single, knowledge=single, market=single, legacy=None
            )
        self.db_path = self.paths.control
        self._lanes: dict[DatabaseDomain, _CommitLane] = {}
        for domain, path in self.paths:
            key = domain.value.lower()
            payloads_root = self.settings.payloads_root_for(path, domain=key)
            spool = CommitSpool(
                self.settings.spool_root_for(path, domain=key),
                settings=self.settings,
                allowed_payload_roots=[
                    payloads_root,
                    path.parent.resolve(),
                ],
            )
            self._lanes[domain] = _CommitLane(
                domain=domain,
                db_path=path,
                spool=spool,
                receipts=CommitReceiptStore(path),
                metrics=CoordinatorMetrics(),
            )
        # Compat aliases — default to CONTROL lane for legacy callers.
        control = self._lanes[DatabaseDomain.CONTROL]
        self.receipts = control.receipts
        self.spool = control.spool
        self.metrics = control.metrics
        self._stop = threading.Event()
        self._draining = False
        self._ready = False
        self._ipc: CommitIpcServer | None = None
        self._token = secrets.token_hex(16)
        self._retries: dict[str, int] = {}
        self._started_at = time.time()
        self._lock = threading.Lock()
        self._rr_order = list(DatabaseDomain)
        self._rr_index = 0

    def lane_for_intent(self, intent: CommitIntent) -> _CommitLane:
        domain = domain_from_commit_operation(intent.operation, intent.domain)
        return self._lanes[domain]

    def lane_public_status(self) -> dict[str, Any]:
        out: dict[str, Any] = {}
        for domain, lane in self._lanes.items():
            stats = lane.spool.stats()
            out[domain.value] = {
                "domain": domain.value,
                "dbPath": str(lane.db_path),
                "pendingCount": stats.pending_count,
                "inflightCount": stats.inflight_count,
                "commitCount": lane.metrics.commit_count,
                "retryCount": lane.metrics.retry_count,
                "busyCount": lane.metrics.busy_count,
                "failedCount": lane.metrics.failed_count,
                "p95LatencyMs": lane.metrics.p95_latency_ms(),
                "inflightCommitId": lane.metrics.inflight_commit_id,
                "lastAppliedCommitId": lane.metrics.last_applied_commit_id,
            }
        return out

    @classmethod
    def from_env(cls, ctx: dict[str, Any]) -> DbCommitCoordinator:
        settings = ctx["settings"]
        worker_id = str(ctx.get("worker_id") or f"db_commit-{os.getpid()}")
        paths = getattr(settings, "database_paths", None)
        if paths is not None:
            return cls(paths, worker_id=worker_id)
        return cls(settings.database_path, worker_id=worker_id)

    def startup(self) -> None:
        for lane in self._lanes.values():
            lane.spool.ensure_dirs()
            lane.receipts.initialize()
            conn = open_sqlite_connection(lane.db_path)
            try:
                lane.receipts.ensure_schema(conn)
                conn.commit()
            finally:
                conn.close()
            lane.spool.recover_inflight(
                receipt_applied=lambda intent, _lane=lane: (
                    _lane.receipts.get_by_commit_id(intent.commit_id) is not None
                    or (
                        bool(intent.idempotency_key)
                        and _lane.receipts.get_by_idempotency_key(intent.idempotency_key)
                        is not None
                    )
                )
            )
        self._start_ipc()
        self._ready = True
        pending = sum(lane.spool.stats().pending_count for lane in self._lanes.values())
        self._emit_db_writer(
            "writer gereed",
            message=f"lanes={len(self._lanes)} pending={pending}",
        )

    def _start_ipc(self) -> None:
        # One IPC endpoint per distinct DB file / lane so producers target the owner.
        started: dict[Path, CommitIpcServer] = {}
        for lane in self._lanes.values():
            resolved = lane.db_path.resolve()
            if resolved in started:
                lane.ipc = started[resolved]
                continue
            server = CommitIpcServer(
                lane.db_path,
                on_intent=self.accept_intent,
                token=self._token,
            )
            server.start()
            started[resolved] = server
            lane.ipc = server
        self._ipc = self._lanes[DatabaseDomain.CONTROL].ipc

    def shutdown(self, *, drain_current: bool = True) -> None:
        self._draining = True
        if drain_current:
            pass
        seen: set[int] = set()
        for lane in self._lanes.values():
            if lane.ipc is not None and id(lane.ipc) not in seen:
                lane.ipc.stop()
                seen.add(id(lane.ipc))
            lane.ipc = None
        self._ipc = None
        pending = sum(lane.spool.stats().pending_count for lane in self._lanes.values())
        self._emit_db_writer(
            "writer stopt",
            message=f"pending={pending}",
        )
        self._stop.set()
        self._ready = False

    def accept_intent(self, intent: CommitIntent) -> WriterAck:
        """IPC accept path — durable spool immediately; process asynchronously."""
        lane = self.lane_for_intent(intent)
        if self._draining or self._stop.is_set():
            try:
                lane.spool.enqueue(intent, allow_critical=True, check_backpressure=False)
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

        existing = lane.receipts.get_by_idempotency_key(intent.idempotency_key)
        if existing is not None:
            return WriterAck(
                status=AckStatus.ALREADY_APPLIED.value,
                commit_id=existing.commit_id,
                message="already applied",
                receipt=existing.to_dict(),
            )

        try:
            lane.spool.enqueue(intent)
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
            message=f"{intent.record_count_hint} records [{lane.domain.value}]"
            if intent.record_count_hint
            else f"lane={lane.domain.value}",
            commit_id=intent.commit_id,
            human_title=title,
            domain=domain,
        )
        return WriterAck(
            status=AckStatus.ACCEPTED_TO_WRITER.value,
            commit_id=intent.commit_id,
            message=f"queued:{lane.domain.value}",
        )

    def run_forever(self) -> None:
        self.startup()
        while not self._stop.is_set():
            try:
                processed = self.process_one()
                if not processed:
                    for lane in self._lanes.values():
                        lane.spool.retain()
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
        # Round-robin across lanes so independent DBs make progress concurrently
        # from the coordinator's perspective (each lane remains serialized).
        for _ in range(len(self._rr_order)):
            domain = self._rr_order[self._rr_index % len(self._rr_order)]
            self._rr_index += 1
            lane = self._lanes[domain]
            item = lane.spool.claim_next()
            if item is None:
                continue
            self._apply_item(item, lane=lane)
            return True
        return False

    def process_until_idle(self, *, max_items: int = 10_000) -> int:
        count = 0
        while count < max_items:
            if not self.process_one():
                break
            count += 1
        return count

    def _apply_item(self, item: SpoolItem, *, lane: _CommitLane | None = None) -> None:
        intent = item.intent
        lane = lane or self.lane_for_intent(intent)
        # Bind compat aliases to active lane for helpers that still use self.spool/receipts.
        self.spool = lane.spool
        self.receipts = lane.receipts
        self.metrics = lane.metrics
        self.db_path = lane.db_path
        title = intent.safe_human_title or intent.entity_id or intent.commit_id[:8]
        domain = intent.domain or intent.operation.split(".", 1)[0]
        lane.metrics.inflight_commit_id = intent.commit_id
        started = time.perf_counter()

        # Crash-after-commit recovery: receipt already present.
        existing = lane.receipts.get_by_idempotency_key(intent.idempotency_key)
        if existing is None:
            existing = lane.receipts.get_by_commit_id(intent.commit_id)
        if existing is not None:
            lane.spool.finalize_applied(item)
            lane.metrics.inflight_commit_id = ""
            lane.metrics.last_applied_commit_id = existing.commit_id
            return

        self._emit_db_writer(
            f"{domain.title()} '{title}' commit gestart",
            message=(
                f"{intent.record_count_hint} records [{lane.domain.value}]"
                if intent.record_count_hint
                else f"lane={lane.domain.value}"
            ),
            commit_id=intent.commit_id,
            human_title=title,
            domain=domain,
        )

        try:
            payload_path = lane.spool.validate_payload(intent)
            # Heavy read/parse OUTSIDE SQLite transaction.
            payload = load_payload_json(payload_path)
            handler = self.registry.get(intent.operation)

            def _apply() -> CommitReceipt:
                return handler.apply(
                    intent,
                    payload,
                    db_path=lane.db_path,
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
                lane.receipts.persist(receipt)

            run_with_busy_retry(_persist)
            if intent.batch_count > 1:
                conn = open_sqlite_connection(lane.db_path)
                try:
                    lane.receipts.mark_batch_applied(
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

            lane.spool.finalize_applied(item)
            duration_ms = (time.perf_counter() - started) * 1000.0
            lane.metrics.commit_count += 1
            lane.metrics.record_latency(duration_ms)
            lane.metrics.last_applied_commit_id = intent.commit_id
            self._retries.pop(intent.commit_id, None)
            self._emit_db_writer(
                f"{domain.title()} '{title}' commit voltooid",
                message=f"{receipt.record_count} records — {duration_ms:.0f}ms [{lane.domain.value}]",
                commit_id=intent.commit_id,
                human_title=title,
                domain=domain,
                duration_ms=duration_ms,
                progress_current=receipt.record_count,
            )
        except Exception as exc:  # noqa: BLE001
            self._handle_failure(item, exc, title=title, domain=domain)
        finally:
            lane.metrics.inflight_commit_id = ""

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
        pending_count = 0
        pending_bytes = 0
        oldest = 0.0
        quarantine = 0
        commit_count = 0
        retry_count = 0
        busy_count = 0
        failed_count = 0
        quarantine_m = 0
        total_latency = 0.0
        inflight = ""
        last_applied = ""
        for lane in self._lanes.values():
            stats = lane.spool.stats()
            pending_count += stats.pending_count
            pending_bytes += stats.pending_bytes
            oldest = max(oldest, float(stats.oldest_pending_age_seconds or 0.0))
            quarantine += stats.quarantine_count
            commit_count += lane.metrics.commit_count
            retry_count += lane.metrics.retry_count
            busy_count += lane.metrics.busy_count
            failed_count += lane.metrics.failed_count
            quarantine_m += lane.metrics.quarantine_count
            total_latency += lane.metrics.total_latency_ms
            if lane.metrics.inflight_commit_id:
                inflight = lane.metrics.inflight_commit_id
            if lane.metrics.last_applied_commit_id:
                last_applied = lane.metrics.last_applied_commit_id
        soft = self.settings.soft_backpressure_threshold
        hard = self.settings.hard_backpressure_threshold
        count_ratio = pending_count / max(1, self.settings.max_pending_count)
        bytes_ratio = pending_bytes / max(1, self.settings.max_pending_bytes)
        health = CommitHealth.HEALTHY
        if not self._ready or self._stop.is_set():
            health = CommitHealth.FAILED
        elif count_ratio >= hard or bytes_ratio >= hard:
            health = CommitHealth.BACKPRESSURED
        elif count_ratio >= soft or bytes_ratio >= soft or oldest > 300 or retry_count > 0:
            health = CommitHealth.DEGRADED
        sqlite_m = sqlite_metrics_snapshot()
        status = DbCommitStatus(
            health=health.value,
            worker_id=self.worker_id,
            worker_pid=os.getpid(),
            ready=self._ready,
            draining=self._draining,
            queue_depth=pending_count,
            pending_bytes=pending_bytes,
            oldest_pending_age_seconds=oldest,
            inflight_commit_id=inflight,
            last_applied_commit_id=last_applied,
            commit_count=commit_count,
            retry_count=retry_count,
            busy_count=busy_count + int(sqlite_m.get("sqlite_busy_count") or 0),
            failed_count=failed_count,
            quarantine_count=quarantine_m + quarantine,
            average_commit_latency_ms=(total_latency / commit_count if commit_count else 0.0),
            p95_commit_latency_ms=self.metrics.p95_latency_ms(),
            apply_rate_per_minute=self._apply_rate_per_minute(),
            lanes=self.lane_public_status(),
        )
        return status

    def _apply_rate_per_minute(self) -> float:
        elapsed_min = max(1e-6, (time.time() - self._started_at) / 60.0)
        total = sum(lane.metrics.commit_count for lane in self._lanes.values())
        return float(total) / elapsed_min

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
