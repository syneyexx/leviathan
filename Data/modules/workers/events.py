"""Central worker terminal observability.

One event source → human terminal formatter + structured logger.
Do not scatter ad-hoc ``print()`` for worker lifecycle across domain code.
"""

from __future__ import annotations

import logging
import os
import re
import sys
import threading
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Mapping

MAX_HUMAN_TITLE_LEN = 120

_CONTROL_CHARS = re.compile(r"[\x00-\x1f\x7f]+")
_SECRET_KEY_HINTS = frozenset(
    {
        "api_key",
        "apikey",
        "token",
        "password",
        "secret",
        "authorization",
        "auth_header",
        "cookie",
        "private_key",
        "access_key",
        "connection_string",
        "prompt",
        "raw_prompt",
        "content",
        "body",
        "payload",
    }
)

_structured_logger = logging.getLogger("leviathan.workers.events")


class WorkerEventKind(str, Enum):
    WORKER_READY = "WORKER_READY"
    WORKER_STOPPING = "WORKER_STOPPING"
    WORKER_RESTARTED = "WORKER_RESTARTED"
    WORKER_CRASHED = "WORKER_CRASHED"
    POOL_STARTED = "POOL_STARTED"
    POOL_START_FAILED = "POOL_START_FAILED"
    JOB_QUEUED = "JOB_QUEUED"
    JOB_CLAIMED = "JOB_CLAIMED"
    JOB_STARTED = "JOB_STARTED"
    JOB_PROGRESS = "JOB_PROGRESS"
    JOB_COMPLETED = "JOB_COMPLETED"
    JOB_FAILED = "JOB_FAILED"
    JOB_CANCEL_REQUESTED = "JOB_CANCEL_REQUESTED"
    JOB_CANCELLED = "JOB_CANCELLED"
    JOB_RETRY = "JOB_RETRY"
    JOB_WAITING_RESOURCES = "JOB_WAITING_RESOURCES"
    CONTROL_PLANE_STARTED = "CONTROL_PLANE_STARTED"


@dataclass(frozen=True)
class WorkerEvent:
    event: WorkerEventKind
    timestamp: str
    pool: str | None = None
    worker_id: str | None = None
    worker_pid: int | None = None
    job_id: str | None = None
    capability_id: str | None = None
    domain: str | None = None
    entity_type: str | None = None
    entity_id: str | None = None
    human_title: str | None = None
    status: str | None = None
    attempt: int | None = None
    duration_ms: float | None = None
    progress_current: int | float | None = None
    progress_total: int | float | None = None
    error_code: str | None = None
    message: str | None = None
    extra: dict[str, Any] = field(default_factory=dict)

    def structured_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["event"] = self.event.value
        # Drop empty noise; keep allowlisted fields only for sinks.
        return {k: v for k, v in payload.items() if v is not None and v != {}}


def utc_timestamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def sanitize_human_label(value: Any, *, max_len: int = MAX_HUMAN_TITLE_LEN) -> str:
    """Strip control chars / newlines and truncate for terminal display."""
    if value is None:
        return ""
    text = str(value)
    text = _CONTROL_CHARS.sub(" ", text)
    text = " ".join(text.split())
    text = text.strip(" '\"")
    if len(text) > max_len:
        text = text[: max(1, max_len - 1)].rstrip() + "…"
    return text


def format_duration_ms(duration_ms: float | int | None) -> str:
    if duration_ms is None:
        return ""
    try:
        total_s = max(0.0, float(duration_ms) / 1000.0)
    except (TypeError, ValueError):
        return ""
    if total_s < 60.0:
        if total_s < 10.0:
            return f"{total_s:.1f}s"
        return f"{total_s:.1f}s"
    total_seconds = int(total_s)
    hours, rem = divmod(total_seconds, 3600)
    minutes, seconds = divmod(rem, 60)
    if hours:
        return f"{hours:02d}:{minutes:02d}:{seconds:02d}"
    return f"{minutes:02d}:{seconds:02d}"


def _short_job_id(job_id: str | None) -> str:
    if not job_id:
        return ""
    return job_id[:8] if len(job_id) > 8 else job_id


def resolve_human_title(
    *,
    capability_id: str | None = None,
    metadata: Mapping[str, Any] | None = None,
    arguments: Mapping[str, Any] | None = None,
    domain: str | None = None,
    domain_entity_type: str | None = None,
    fallback: str | None = None,
) -> str:
    """Pick an allowlisted human label from job metadata/arguments."""
    meta = dict(metadata or {})
    args = dict(arguments or {})
    candidates: list[Any] = [
        meta.get("human_title"),
        meta.get("topic"),
        meta.get("title"),
        meta.get("filename"),
        meta.get("file_name"),
        meta.get("dataset_name"),
        meta.get("repository_id"),
        meta.get("repo_id"),
        meta.get("suite_name"),
        meta.get("suite"),
        meta.get("model_name"),
        meta.get("training_job_name"),
        meta.get("job_name"),
        meta.get("agent_name"),
        meta.get("workflow_name"),
        meta.get("backup_name"),
        meta.get("name"),
        args.get("topic"),
        args.get("title"),
        args.get("filename"),
        args.get("file_name"),
        args.get("dataset_name"),
        args.get("repository_id"),
        args.get("repo_id"),
        args.get("suite_name"),
        args.get("model_name"),
        args.get("name"),
        args.get("project_title"),
    ]
    for raw in candidates:
        label = sanitize_human_label(raw)
        if label and not _looks_like_secret_key(str(raw)):
            return label

    # Domain-ish fallbacks that remain safe (ids, not content).
    for key in ("project_id", "source_id", "dataset_id", "document_id"):
        val = args.get(key) or meta.get(key)
        if val:
            return sanitize_human_label(f"{key}={val}")

    if fallback:
        return sanitize_human_label(fallback)
    if capability_id:
        return sanitize_human_label(capability_id)
    if domain:
        return sanitize_human_label(domain)
    if domain_entity_type:
        return sanitize_human_label(domain_entity_type)
    return "job"


def _looks_like_secret_key(name: str) -> bool:
    lowered = name.strip().lower().replace("-", "_")
    return any(hint in lowered for hint in _SECRET_KEY_HINTS)


def _domain_noun(pool: str | None, capability_id: str | None, domain: str | None) -> str:
    raw = (domain or pool or (capability_id or "").split(".", 1)[0] or "job").strip().lower()
    mapping = {
        "research": "Research",
        "source_ingestion": "Source",
        "dataset": "Dataset",
        "knowledge": "Knowledge",
        "knowledge_prepare": "Knowledge",
        "knowledge_commit": "Knowledge",
        "embedding": "Embedding",
        "rerank": "Rerank",
        "training": "Training",
        "training_control": "Training",
        "evaluation": "Evaluation",
        "model_download": "Model download",
        "provider_io": "Provider I/O",
        "agents": "Agent",
        "agent": "Agent",
        "coding": "Coding",
        "workflow": "Workflow",
        "backup": "Backup",
        "maintenance": "Maintenance",
        "mcp_execution": "MCP",
        "mcp": "MCP",
        "market_sim": "Market sim",
        "db_commit": "DB Commit",
        "scheduler": "Scheduler",
        "document_ai": "Document AI",
    }
    if raw in mapping:
        return mapping[raw]
    return sanitize_human_label(raw.replace("_", " ").title()) or "Job"


def _worker_tag(pool: str | None, worker_id: str | None) -> str:
    """Compact worker identity suffix for parallel readability."""
    if not worker_id and not pool:
        return "WORKER"
    # Prefer pool-slot style: research-1 from research-0-deadbeef or research-1
    if worker_id:
        parts = worker_id.split("-")
        if len(parts) >= 2 and parts[1].isdigit():
            return f"WORKER:{parts[0]}-{int(parts[1]) + 1}"
        if pool and worker_id.startswith(pool):
            return f"WORKER:{worker_id}"
        return f"WORKER:{sanitize_human_label(worker_id, max_len=40)}"
    return f"WORKER:{pool}"


def format_terminal_message(event: WorkerEvent) -> str:
    """Render a compact Dutch-style operator line (UTF-8 text, no required ANSI)."""
    kind = event.event
    title = sanitize_human_label(event.human_title) if event.human_title else ""
    noun = _domain_noun(event.pool, event.capability_id, event.domain)
    quoted = f" '{title}'" if title else ""
    duration = format_duration_ms(event.duration_ms)
    job_bit = f" — job {_short_job_id(event.job_id)}" if event.job_id else ""
    pid_bit = f" — PID {event.worker_pid}" if event.worker_pid else ""

    if kind == WorkerEventKind.CONTROL_PLANE_STARTED:
        return "[LEVIATHAN] Control Plane gestart"

    if kind == WorkerEventKind.POOL_STARTED:
        count = event.extra.get("worker_count")
        count_bit = f" — {count} worker{'s' if count != 1 else ''}" if count is not None else ""
        return f"[WORKER] {event.pool or 'pool'} pool gestart{count_bit}"

    if kind == WorkerEventKind.POOL_START_FAILED:
        reason = sanitize_human_label(event.error_code or event.message or "onbekende fout")
        return f"[WORKER] {event.pool or 'pool'} pool KON NIET STARTEN — {reason}"

    if kind == WorkerEventKind.WORKER_READY:
        label = event.worker_id or (f"{event.pool}-worker" if event.pool else "worker")
        return f"[WORKER] Pool {event.pool or '?'} worker {sanitize_human_label(label, max_len=48)} gereed{pid_bit}"

    if kind == WorkerEventKind.WORKER_STOPPING:
        label = event.worker_id or event.pool or "worker"
        return f"[WORKER] {sanitize_human_label(label, max_len=48)} gestopt"

    if kind == WorkerEventKind.WORKER_CRASHED:
        label = event.worker_id or event.pool or "worker"
        exit_code = event.extra.get("exit_code")
        exit_bit = f" — exit={exit_code}" if exit_code is not None else ""
        return f"[WORKER] {sanitize_human_label(label, max_len=48)} onverwacht gestopt{exit_bit}"

    if kind == WorkerEventKind.WORKER_RESTARTED:
        label = event.worker_id or event.pool or "worker"
        attempt = event.attempt
        attempt_bit = f" — poging {attempt}" if attempt is not None else ""
        return f"[WORKER] {sanitize_human_label(label, max_len=48)} herstart{attempt_bit}"

    if kind == WorkerEventKind.JOB_QUEUED:
        return f"[JOB] {noun}{quoted} ingepland{job_bit}"

    tag = _worker_tag(event.pool, event.worker_id)

    if kind == WorkerEventKind.JOB_CLAIMED:
        return f"[{tag}] {noun}{quoted} geclaimd{job_bit}"

    if kind == WorkerEventKind.JOB_STARTED:
        return f"[{tag}] {noun}{quoted} gestart{job_bit}"

    if kind == WorkerEventKind.JOB_WAITING_RESOURCES:
        reason = sanitize_human_label(event.error_code or event.message or "resource")
        return f"[{tag}] {noun}{quoted} wacht — {reason}"

    if kind == WorkerEventKind.JOB_PROGRESS:
        cur, tot = event.progress_current, event.progress_total
        if cur is not None and tot is not None:
            progress = f" {cur}/{tot}"
        elif cur is not None:
            progress = f" {cur}"
        elif event.message:
            progress = f" {sanitize_human_label(event.message)}"
        else:
            progress = ""
        return f"[{tag}] {noun}{quoted}{progress}"

    if kind == WorkerEventKind.JOB_COMPLETED:
        dur_bit = f" — {duration}" if duration else ""
        return f"[{tag}] {noun}{quoted} voltooid{dur_bit}"

    if kind == WorkerEventKind.JOB_FAILED:
        reason = sanitize_human_label(event.error_code or event.message or "mislukt")
        return f"[{tag}] {noun}{quoted} MISLUKT — {reason}"

    if kind == WorkerEventKind.JOB_CANCEL_REQUESTED:
        return f"[{tag}] {noun}{quoted} annulering aangevraagd"

    if kind == WorkerEventKind.JOB_CANCELLED:
        return f"[{tag}] {noun}{quoted} geannuleerd"

    if kind == WorkerEventKind.JOB_RETRY:
        attempt = event.attempt
        attempt_bit = f" — poging {attempt}" if attempt is not None else ""
        return f"[{tag}] {noun}{quoted} retry{attempt_bit}"

    return f"[{tag}] {kind.value}{quoted}"


class WorkerEventEmitter:
    """Emit lifecycle events to the terminal and structured logger.

    Terminal writes are one complete line + flush (process-safe enough for
    concurrent workers writing to inherited stdout/stderr).
    """

    def __init__(
        self,
        *,
        stream: Any | None = None,
        enable_terminal: bool = True,
        enable_structured: bool = True,
        logger: logging.Logger | None = None,
    ) -> None:
        self._stream = stream if stream is not None else sys.stdout
        self._enable_terminal = enable_terminal
        self._enable_structured = enable_structured
        self._logger = logger or _structured_logger
        self._lock = threading.Lock()
        self._progress_last_emit: dict[str, float] = {}
        self.progress_min_interval_s = 2.0

    def emit(self, event: WorkerEvent) -> str:
        line = format_terminal_message(event)
        if self._enable_terminal:
            with self._lock:
                try:
                    self._stream.write(line + "\n")
                    self._stream.flush()
                except Exception:  # noqa: BLE001 — never break workers on log I/O
                    pass
        if self._enable_structured:
            level = logging.INFO
            if event.event in {
                WorkerEventKind.JOB_FAILED,
                WorkerEventKind.WORKER_CRASHED,
                WorkerEventKind.POOL_START_FAILED,
            }:
                level = logging.ERROR
            elif event.event in {
                WorkerEventKind.JOB_RETRY,
                WorkerEventKind.WORKER_RESTARTED,
                WorkerEventKind.JOB_WAITING_RESOURCES,
            }:
                level = logging.WARNING
            try:
                self._logger.log(level, line, extra={"worker_event": event.structured_dict()})
            except Exception:  # noqa: BLE001
                pass
        return line

    def emit_kind(self, kind: WorkerEventKind, **kwargs: Any) -> str:
        extra = dict(kwargs.pop("extra", None) or {})
        # Remaining kwargs fold into extra (never print secrets).
        for key, value in list(kwargs.items()):
            if key in {
                "timestamp",
                "pool",
                "worker_id",
                "worker_pid",
                "job_id",
                "capability_id",
                "domain",
                "entity_type",
                "entity_id",
                "human_title",
                "status",
                "attempt",
                "duration_ms",
                "progress_current",
                "progress_total",
                "error_code",
                "message",
            }:
                continue
            kwargs.pop(key, None)
            if _looks_like_secret_key(key):
                continue
            if isinstance(value, (str, int, float, bool)) or value is None:
                extra[key] = value
        event = WorkerEvent(
            event=kind,
            timestamp=kwargs.pop("timestamp", None) or utc_timestamp(),
            pool=kwargs.pop("pool", None),
            worker_id=kwargs.pop("worker_id", None),
            worker_pid=kwargs.pop("worker_pid", None),
            job_id=kwargs.pop("job_id", None),
            capability_id=kwargs.pop("capability_id", None),
            domain=kwargs.pop("domain", None),
            entity_type=kwargs.pop("entity_type", None),
            entity_id=kwargs.pop("entity_id", None),
            human_title=sanitize_human_label(kwargs.pop("human_title", None)) or None,
            status=kwargs.pop("status", None),
            attempt=kwargs.pop("attempt", None),
            duration_ms=kwargs.pop("duration_ms", None),
            progress_current=kwargs.pop("progress_current", None),
            progress_total=kwargs.pop("progress_total", None),
            error_code=sanitize_human_label(kwargs.pop("error_code", None), max_len=160) or None,
            message=sanitize_human_label(kwargs.pop("message", None), max_len=160) or None,
            extra=extra,
        )
        return self.emit(event)

    def control_plane_started(self) -> str:
        return self.emit_kind(WorkerEventKind.CONTROL_PLANE_STARTED)

    def pool_started(self, pool: str, *, worker_count: int) -> str:
        return self.emit_kind(
            WorkerEventKind.POOL_STARTED,
            pool=pool,
            extra={"worker_count": int(worker_count)},
        )

    def pool_start_failed(self, pool: str, *, reason: str) -> str:
        return self.emit_kind(
            WorkerEventKind.POOL_START_FAILED,
            pool=pool,
            error_code=reason,
        )

    def worker_ready(
        self,
        *,
        pool: str,
        worker_id: str,
        worker_pid: int | None = None,
    ) -> str:
        return self.emit_kind(
            WorkerEventKind.WORKER_READY,
            pool=pool,
            worker_id=worker_id,
            worker_pid=worker_pid if worker_pid is not None else os.getpid(),
        )

    def worker_stopping(self, *, pool: str | None = None, worker_id: str | None = None) -> str:
        return self.emit_kind(WorkerEventKind.WORKER_STOPPING, pool=pool, worker_id=worker_id)

    def worker_crashed(
        self,
        *,
        pool: str | None = None,
        worker_id: str | None = None,
        exit_code: int | None = None,
        reason: str | None = None,
    ) -> str:
        return self.emit_kind(
            WorkerEventKind.WORKER_CRASHED,
            pool=pool,
            worker_id=worker_id,
            error_code=reason,
            extra={"exit_code": exit_code} if exit_code is not None else {},
        )

    def worker_restarted(
        self,
        *,
        pool: str | None = None,
        worker_id: str | None = None,
        attempt: int | None = None,
    ) -> str:
        return self.emit_kind(
            WorkerEventKind.WORKER_RESTARTED,
            pool=pool,
            worker_id=worker_id,
            attempt=attempt,
        )

    def job_queued(
        self,
        *,
        job_id: str,
        capability_id: str,
        human_title: str | None = None,
        pool: str | None = None,
        domain: str | None = None,
        metadata: Mapping[str, Any] | None = None,
        arguments: Mapping[str, Any] | None = None,
    ) -> str:
        title = human_title or resolve_human_title(
            capability_id=capability_id,
            metadata=metadata,
            arguments=arguments,
            domain=domain,
        )
        return self.emit_kind(
            WorkerEventKind.JOB_QUEUED,
            pool=pool,
            job_id=job_id,
            capability_id=capability_id,
            domain=domain,
            human_title=title,
        )

    def job_started(
        self,
        *,
        job_id: str,
        capability_id: str,
        pool: str | None = None,
        worker_id: str | None = None,
        worker_pid: int | None = None,
        human_title: str | None = None,
        domain: str | None = None,
        attempt: int | None = None,
        metadata: Mapping[str, Any] | None = None,
        arguments: Mapping[str, Any] | None = None,
    ) -> str:
        title = human_title or resolve_human_title(
            capability_id=capability_id,
            metadata=metadata,
            arguments=arguments,
            domain=domain,
        )
        return self.emit_kind(
            WorkerEventKind.JOB_STARTED,
            pool=pool,
            worker_id=worker_id,
            worker_pid=worker_pid,
            job_id=job_id,
            capability_id=capability_id,
            domain=domain,
            human_title=title,
            attempt=attempt,
            status="running",
        )

    def job_progress(
        self,
        *,
        job_id: str,
        capability_id: str,
        progress_current: int | float | None = None,
        progress_total: int | float | None = None,
        message: str | None = None,
        pool: str | None = None,
        worker_id: str | None = None,
        human_title: str | None = None,
        domain: str | None = None,
        force: bool = False,
    ) -> str | None:
        """Coarse progress only — rate-limited unless ``force``."""
        now = time.monotonic()
        last = self._progress_last_emit.get(job_id, 0.0)
        if not force and (now - last) < self.progress_min_interval_s:
            return None
        self._progress_last_emit[job_id] = now
        return self.emit_kind(
            WorkerEventKind.JOB_PROGRESS,
            pool=pool,
            worker_id=worker_id,
            job_id=job_id,
            capability_id=capability_id,
            domain=domain,
            human_title=human_title,
            progress_current=progress_current,
            progress_total=progress_total,
            message=message,
            status="running",
        )

    def job_completed(
        self,
        *,
        job_id: str,
        capability_id: str,
        duration_ms: float | None = None,
        pool: str | None = None,
        worker_id: str | None = None,
        human_title: str | None = None,
        domain: str | None = None,
        metadata: Mapping[str, Any] | None = None,
        arguments: Mapping[str, Any] | None = None,
    ) -> str:
        title = human_title or resolve_human_title(
            capability_id=capability_id,
            metadata=metadata,
            arguments=arguments,
            domain=domain,
        )
        self._progress_last_emit.pop(job_id, None)
        return self.emit_kind(
            WorkerEventKind.JOB_COMPLETED,
            pool=pool,
            worker_id=worker_id,
            job_id=job_id,
            capability_id=capability_id,
            domain=domain,
            human_title=title,
            duration_ms=duration_ms,
            status="completed",
        )

    def job_failed(
        self,
        *,
        job_id: str,
        capability_id: str,
        error_code: str | None = None,
        message: str | None = None,
        duration_ms: float | None = None,
        pool: str | None = None,
        worker_id: str | None = None,
        human_title: str | None = None,
        domain: str | None = None,
        metadata: Mapping[str, Any] | None = None,
        arguments: Mapping[str, Any] | None = None,
    ) -> str:
        title = human_title or resolve_human_title(
            capability_id=capability_id,
            metadata=metadata,
            arguments=arguments,
            domain=domain,
        )
        self._progress_last_emit.pop(job_id, None)
        return self.emit_kind(
            WorkerEventKind.JOB_FAILED,
            pool=pool,
            worker_id=worker_id,
            job_id=job_id,
            capability_id=capability_id,
            domain=domain,
            human_title=title,
            duration_ms=duration_ms,
            error_code=error_code or message,
            message=message,
            status="failed",
        )

    def job_waiting_resources(
        self,
        *,
        job_id: str,
        capability_id: str,
        reason: str,
        pool: str | None = None,
        worker_id: str | None = None,
        human_title: str | None = None,
        domain: str | None = None,
    ) -> str:
        return self.emit_kind(
            WorkerEventKind.JOB_WAITING_RESOURCES,
            pool=pool,
            worker_id=worker_id,
            job_id=job_id,
            capability_id=capability_id,
            domain=domain,
            human_title=human_title,
            error_code=reason,
            status="waiting",
        )

    def job_retry(
        self,
        *,
        job_id: str,
        capability_id: str,
        attempt: int | None = None,
        pool: str | None = None,
        worker_id: str | None = None,
        human_title: str | None = None,
        domain: str | None = None,
    ) -> str:
        return self.emit_kind(
            WorkerEventKind.JOB_RETRY,
            pool=pool,
            worker_id=worker_id,
            job_id=job_id,
            capability_id=capability_id,
            domain=domain,
            human_title=human_title,
            attempt=attempt,
            status="retry",
        )

    def job_cancelled(
        self,
        *,
        job_id: str,
        capability_id: str,
        pool: str | None = None,
        worker_id: str | None = None,
        human_title: str | None = None,
        domain: str | None = None,
    ) -> str:
        return self.emit_kind(
            WorkerEventKind.JOB_CANCELLED,
            pool=pool,
            worker_id=worker_id,
            job_id=job_id,
            capability_id=capability_id,
            domain=domain,
            human_title=human_title,
            status="cancelled",
        )


# Process-wide default emitter (workers + supervisor + control-plane enqueue).
_default_emitter: WorkerEventEmitter | None = None
_default_lock = threading.Lock()


def get_worker_event_emitter() -> WorkerEventEmitter:
    global _default_emitter
    with _default_lock:
        if _default_emitter is None:
            _default_emitter = WorkerEventEmitter()
        return _default_emitter


def set_worker_event_emitter(emitter: WorkerEventEmitter | None) -> None:
    """Test hook — replace or clear the process-wide emitter."""
    global _default_emitter
    with _default_lock:
        _default_emitter = emitter
