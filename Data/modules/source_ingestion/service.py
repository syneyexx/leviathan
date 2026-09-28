"""Source Ingestion service — accept uploads, enqueue jobs, status/cancel/retry."""

from __future__ import annotations

import threading
import uuid
from pathlib import Path
from typing import Any, BinaryIO

from Data.modules.common.atomic import ensure_dir
from Data.modules.common.corpus import CorpusLayout
from Data.modules.jobs.runtime import JobRuntime
from Data.modules.jobs.states import JobState
from Data.modules.research.store import ResearchStore, utc_now
from Data.modules.research.types import (
    BrainStatus,
    ParseStatus,
    ResearchError,
    ResearchSource,
    SourceType,
)
from Data.modules.research.uploads import sanitize_filename, stream_hash_and_write

from .detection import detect_source_type, MIME_BY_EXT
from .execution_gate import allow_inprocess_execution
from .pipeline import SourceIngestionPipeline
from .settings import SourceIngestionSettings, load_source_ingestion_settings
from .store import IngestionStore
from .types import (
    CAPABILITY_BRAIN_RETRY,
    CAPABILITY_DOCUMENT_AI_OCR,
    CAPABILITY_OCR_EXTRACT,
    CAPABILITY_PROCESS,
    ERROR_DOCUMENT_AI_UNAVAILABLE,
    ERROR_OCR_UNAVAILABLE,
    IngestionError,
    IngestionPhase,
)


class _PeekReplayStream:
    """Replay a peek buffer then continue reading the underlying stream (no full-file copy)."""

    def __init__(self, head: bytes, rest: BinaryIO) -> None:
        self._head = head or b""
        self._rest = rest
        self._offset = 0

    def read(self, size: int = -1) -> bytes:
        if size == 0:
            return b""
        if self._offset < len(self._head):
            if size is None or size < 0:
                out = self._head[self._offset :]
                self._offset = len(self._head)
                more = self._rest.read() or b""
                return out + more
            take = min(size, len(self._head) - self._offset)
            out = self._head[self._offset : self._offset + take]
            self._offset += take
            if take < size:
                more = self._rest.read(size - take) or b""
                return out + more
            return out
        return self._rest.read() if size is None or size < 0 else (self._rest.read(size) or b"")


class SourceIngestionService:
    """Facade used by Research (and future callers) for durable source ingestion."""

    def __init__(
        self,
        *,
        research_store: ResearchStore,
        ingestion_store: IngestionStore,
        settings: SourceIngestionSettings,
        sources_root: Path,
        snapshots_root: Path,
        staging_root: Path,
        knowledge: Any | None = None,
        job_runtime: JobRuntime | None = None,
        dataset_service: Any | None = None,
    ) -> None:
        self.research = research_store
        self.ingestion = ingestion_store
        self.settings = settings
        self.sources_root = ensure_dir(Path(sources_root))
        self.snapshots_root = ensure_dir(Path(snapshots_root))
        self.staging_root = ensure_dir(Path(staging_root))
        self.knowledge = knowledge
        self.jobs = job_runtime
        self.dataset_service = dataset_service
        self._lock = threading.Lock()
        self._bg_stop = threading.Event()
        self._bg_thread: threading.Thread | None = None
        self._wake = threading.Event()

    @classmethod
    def from_corpus(
        cls,
        *,
        research_store: ResearchStore,
        corpus: CorpusLayout,
        database_path: Path,
        knowledge: Any | None = None,
        job_runtime: JobRuntime | None = None,
        dataset_service: Any | None = None,
        settings: SourceIngestionSettings | None = None,
    ) -> "SourceIngestionService":
        cfg = settings or load_source_ingestion_settings()
        ingestion_store = IngestionStore(database_path)
        ingestion_store.initialize()
        staging = ensure_dir(corpus.research / "staging")
        return cls(
            research_store=research_store,
            ingestion_store=ingestion_store,
            settings=cfg,
            sources_root=corpus.research_sources,
            snapshots_root=corpus.research_snapshots,
            staging_root=staging,
            knowledge=knowledge,
            job_runtime=job_runtime,
            dataset_service=dataset_service,
        )

    def pipeline(self) -> SourceIngestionPipeline:
        return SourceIngestionPipeline(
            research_store=self.research,
            ingestion_store=self.ingestion,
            settings=self.settings,
            knowledge=self.knowledge,
            snapshots_root=self.snapshots_root,
            staging_root=self.staging_root,
            dataset_service=self.dataset_service,
            emit=self._emit_research_event,
            enqueue_ocr=self.enqueue_ocr,
        )

    def _emit_research_event(self, name: str, message: str, payload: dict[str, Any]) -> None:
        project_id = payload.get("project_id") or ""
        source_id = payload.get("source_id")
        if not project_id and source_id:
            src = self.research.get_source(str(source_id))
            if src:
                project_id = src.project_id
        if not project_id:
            return
        try:
            self.research.add_event(project_id, name, message, payload)
        except Exception:  # noqa: BLE001
            pass

    def accept_upload(
        self,
        project_id: str,
        *,
        filename: str,
        stream: BinaryIO,
        content_type: str | None = None,
    ) -> dict[str, Any]:
        if not self.settings.enabled:
            raise ResearchError(
                "SOURCE_INGESTION_DISABLED",
                "Source ingestion is disabled",
                http_status=503,
            )

        safe_name = sanitize_filename(filename)
        # Peek first chunk for detection without loading whole file into memory.
        peek = stream.read(8192) or b""
        if hasattr(stream, "seek"):
            try:
                stream.seek(0)
            except Exception:  # noqa: BLE001
                stream = _PeekReplayStream(peek, stream)
        else:
            stream = _PeekReplayStream(peek, stream)

        detection = detect_source_type(
            filename=safe_name,
            sample=peek,
            content_type_hint=content_type,
            allow_unknown_text=self.settings.allow_unknown_text,
        )

        # Reject clearly unsupported archives early
        if detection.extension in {".rar"} and not self.settings.allow_rar:
            raise ResearchError(
                "UNSUPPORTED_SOURCE_TYPE",
                "RAR archives are not supported",
                http_status=422,
                details={"filename": safe_name},
            )
        if detection.extension == ".7z" and not self.settings.allow_7z:
            raise ResearchError(
                "UNSUPPORTED_SOURCE_TYPE",
                "7z archives are not enabled",
                http_status=422,
                details={"filename": safe_name},
            )

        source_id = str(uuid.uuid4())
        dest_dir = ensure_dir(self.sources_root / project_id)
        raw_path = dest_dir / f"{source_id}__{safe_name}"
        content_hash, size = stream_hash_and_write(
            stream, raw_path, max_bytes=self.settings.max_upload_bytes
        )

        source = ResearchSource(
            source_id=source_id,
            project_id=project_id,
            source_type=SourceType.LOCAL_FILE,
            original_uri=f"upload://{safe_name}",
            canonical_uri=f"upload://{project_id}/{content_hash}",
            title=safe_name,
            fetched_at=utc_now(),
            content_hash=content_hash,
            mime_type=detection.mime_type or content_type or MIME_BY_EXT.get(detection.extension),
            snapshot_path=None,
            parse_status=ParseStatus.PENDING,
            parser=None,
            brain_status=BrainStatus.PENDING,
            provenance={
                "filename": safe_name,
                "size_bytes": size,
                "raw_path": str(raw_path),
                "content_hash": content_hash,
                "detection": detection.public_dict(),
                "project_id": project_id,
                "research_source_id": source_id,
                "is_archive": detection.is_archive,
            },
            metadata={
                "upload": True,
                "is_container": detection.is_archive,
                "ingestion_phase": IngestionPhase.STORED.value,
            },
            created_at=utc_now(),
        )
        # Dedupe identical full-file re-upload
        stored = self.research.upsert_source(source)
        if stored.source_id != source.source_id:
            # Existing identical upload — return its status / requeue if needed
            progress = self.get_status(stored.source_id)
            return {
                "source_id": stored.source_id,
                "job_id": progress.job_id,
                "status": progress.status.value,
                "source_type": "archive" if detection.is_archive else "file",
                "filename": safe_name,
                "source": stored.public_dict(),
                "idempotent": True,
                "progress": progress.public_dict(),
            }

        self.ingestion.upsert_container(
            container_source_id=source_id,
            project_id=project_id,
            filename=safe_name,
            archive_type=detection.handler_hint if detection.is_archive else None,
            phase=IngestionPhase.STORED,
            compressed_bytes=size,
        )
        self.research.add_event(
            project_id,
            "source_upload_stored",
            safe_name,
            {"source_id": source_id, "size_bytes": size, "is_archive": detection.is_archive},
        )

        job_id = self._enqueue_process(source_id, project_id)
        self.ingestion.upsert_container(
            container_source_id=source_id,
            project_id=project_id,
            job_id=job_id,
            phase=IngestionPhase.QUEUED,
            compressed_bytes=size,
        )
        self.research.add_event(
            project_id,
            "ingestion_queued",
            safe_name,
            {"source_id": source_id, "job_id": job_id},
        )
        self._wake.set()

        # In-process runner: process promptly for small UX / tests without blocking forever.
        # Upload request itself never parses large archives.
        return {
            "source_id": source_id,
            "job_id": job_id,
            "status": IngestionPhase.QUEUED.value,
            "source_type": "archive" if detection.is_archive else "file",
            "filename": safe_name,
            "source": stored.public_dict(),
            "extracted_chars": 0,
            "page_count": None,
            "progress": self.get_status(source_id).public_dict(),
        }

    def _enqueue_process(self, source_id: str, project_id: str) -> str | None:
        if self.jobs is None:
            if allow_inprocess_execution(self.settings):
                return None
            raise ResearchError(
                "SOURCE_INGESTION_UNAVAILABLE",
                "JobRuntime not bound; source_ingestion worker path required",
                http_status=503,
                details={"source_id": source_id, "project_id": project_id},
            )
        try:
            job = self.jobs.enqueue(
                capability_id=CAPABILITY_PROCESS,
                arguments={"source_id": source_id, "project_id": project_id},
                requested_by="source_ingestion",
                idempotency_key=f"source_ingestion:process:{source_id}",
                metadata={"source_id": source_id, "project_id": project_id},
                latency_class="background",
                domain="source_ingestion",
                domain_entity_type="source",
                domain_entity_id=source_id,
                worker_pool="source_ingestion",
                resource_class="IO_HEAVY",
            )
            return job.job_id
        except ResearchError:
            raise
        except Exception as exc:  # noqa: BLE001
            if allow_inprocess_execution(self.settings):
                return None
            raise ResearchError(
                "SOURCE_INGESTION_UNAVAILABLE",
                f"Failed to enqueue source_ingestion.process: {exc}"[:400],
                http_status=503,
                details={"source_id": source_id},
            ) from exc

    def enqueue_ocr(
        self,
        *,
        source_id: str,
        project_id: str,
        path: str,
        relative_path: str | None = None,
        parent_job_id: str | None = None,
        root_job_id: str | None = None,
        mime_type: str | None = None,
        reason: str = "ocr_required",
    ) -> dict[str, Any]:
        """Enqueue durable OCR/document-AI child job (never runs OCR inline).

        When no OCR backend exists the document_ai worker fails closed with
        OCR_UNAVAILABLE — this method only establishes lineage + contract.
        """
        if self.jobs is None:
            return {
                "queued": False,
                "job_id": None,
                "status": ERROR_OCR_UNAVAILABLE,
                "error_code": ERROR_OCR_UNAVAILABLE,
                "reason": "JobRuntime not bound",
                "truth": {"ocr_backend": "missing", "executed_inline": False},
            }
        arguments = {
            "source_id": source_id,
            "project_id": project_id,
            "path": path,
            "relative_path": relative_path or path,
            "mime_type": mime_type,
            "reason": reason,
        }
        idem = f"document_ai:ocr:{source_id}:{relative_path or path}"
        try:
            job = self.jobs.enqueue(
                capability_id=CAPABILITY_OCR_EXTRACT,
                arguments=arguments,
                requested_by="source_ingestion.ocr_delegate",
                idempotency_key=idem[:200],
                metadata={
                    "source_id": source_id,
                    "project_id": project_id,
                    "relative_path": relative_path or path,
                    "human_title": relative_path or source_id,
                    "delegated_from": CAPABILITY_PROCESS,
                    "capability_alias": CAPABILITY_DOCUMENT_AI_OCR,
                },
                latency_class="background",
                domain="document_ai",
                domain_entity_type="source",
                domain_entity_id=source_id,
                worker_pool="document_ai",
                resource_class="CPU_HEAVY",
                parent_job_id=parent_job_id,
                root_job_id=root_job_id or parent_job_id,
            )
            return {
                "queued": True,
                "job_id": job.job_id,
                "job": job.public_dict(),
                "status": "QUEUED",
                "capability_id": CAPABILITY_OCR_EXTRACT,
                "worker_pool": "document_ai",
                "truth": {
                    "ocr_backend": "delegated",
                    "executed_inline": False,
                    "parent_job_id": parent_job_id,
                },
            }
        except Exception as exc:  # noqa: BLE001
            return {
                "queued": False,
                "job_id": None,
                "status": ERROR_DOCUMENT_AI_UNAVAILABLE
                if "DOCUMENT_AI" in str(exc).upper()
                else ERROR_OCR_UNAVAILABLE,
                "error_code": ERROR_OCR_UNAVAILABLE,
                "reason": str(exc)[:300],
                "truth": {"ocr_backend": "missing", "executed_inline": False},
            }

    def get_status(self, source_id: str) -> Any:
        return self.pipeline().get_progress(source_id)

    def list_children(
        self,
        source_id: str,
        *,
        offset: int = 0,
        limit: int = 100,
        outcome: str | None = None,
    ) -> dict[str, Any]:
        members = self.ingestion.list_members(
            source_id, offset=offset, limit=limit, outcome=outcome
        )
        counts = self.ingestion.count_members(source_id)
        return {
            "source_id": source_id,
            "offset": offset,
            "limit": limit,
            "total": int(counts.get("total") or 0),
            "members": [m.public_dict() for m in members],
            "counts": {k: v for k, v in counts.items() if k not in {"by_outcome", "by_brain"}},
        }

    def cancel(self, source_id: str) -> dict[str, Any]:
        self.ingestion.request_cancel(source_id)
        container = self.ingestion.get_container(source_id)
        job_id = (container or {}).get("job_id")
        if job_id and self.jobs is not None:
            try:
                job = self.jobs.get(job_id)
                if job and job.state not in {JobState.COMPLETED, JobState.FAILED, JobState.CANCELLED}:
                    self.jobs.cancel(job_id)
            except Exception:  # noqa: BLE001
                pass
        self.research.add_event(
            str((container or {}).get("project_id") or ""),
            "ingestion_cancelled",
            "cancel requested",
            {"source_id": source_id, "job_id": job_id},
        )
        return self.get_status(source_id).public_dict()

    def retry(self, source_id: str, *, failed_only: bool = True) -> dict[str, Any]:
        from .store import utc_now
        from .types import MemberOutcome

        if failed_only:
            members = self.ingestion.list_members(source_id, limit=2000)
            for m in members:
                if m.outcome == MemberOutcome.FAILED:
                    m.outcome = MemberOutcome.PENDING
                    m.error_code = None
                    m.skip_reason = None
                    m.parse_status = "pending"
                    self.ingestion.upsert_member(m)
        container = self.ingestion.get_container(source_id)
        project_id = str((container or {}).get("project_id") or "")
        with self.ingestion.connect() as conn:
            conn.execute(
                "UPDATE source_ingestion_containers SET cancel_requested=0, updated_at=? "
                "WHERE container_source_id=?",
                (utc_now(), source_id),
            )
        self.ingestion.upsert_container(
            container_source_id=source_id,
            project_id=project_id,
            phase=IngestionPhase.QUEUED,
        )
        job_id = self._enqueue_process(source_id, project_id)
        self.ingestion.upsert_container(
            container_source_id=source_id,
            project_id=project_id,
            job_id=job_id,
            phase=IngestionPhase.QUEUED,
        )
        self._wake.set()
        return {
            "source_id": source_id,
            "job_id": job_id,
            "status": IngestionPhase.QUEUED.value,
            "progress": self.get_status(source_id).public_dict(),
        }

    def enqueue_brain_retry(self, source_id: str) -> dict[str, Any]:
        """Enqueue durable brain retry — never sync upsert from API."""
        container = self.ingestion.get_container(source_id)
        project_id = str((container or {}).get("project_id") or "")
        if not project_id:
            source = self.research.get_source(source_id)
            if source is None:
                raise ResearchError("SOURCE_NOT_FOUND", source_id, http_status=404)
            project_id = source.project_id
        if self.jobs is None:
            raise ResearchError(
                "SOURCE_INGESTION_UNAVAILABLE",
                "JobRuntime not bound for brain retry",
                http_status=503,
            )
        job = self.jobs.enqueue(
            capability_id=CAPABILITY_BRAIN_RETRY,
            arguments={"source_id": source_id, "project_id": project_id},
            requested_by="source_ingestion.brain_retry",
            idempotency_key=f"source_ingestion:brain_retry:{source_id}",
            metadata={
                "source_id": source_id,
                "project_id": project_id,
                "human_title": ((self.research.get_source(source_id) or type("X", (), {"title": source_id})).title),
                "filename": ((self.research.get_source(source_id) or type("X", (), {"title": source_id})).title),
            },
            latency_class="background",
            domain="source_ingestion",
            domain_entity_type="source",
            domain_entity_id=source_id,
            worker_pool="source_ingestion",
            resource_class="CPU_HEAVY",
        )
        self._wake.set()
        return {
            "queued": True,
            "job_id": job.job_id,
            "job": job.public_dict(),
            "source_id": source_id,
            "status": "QUEUED",
            "truth": {"executed_via": "source_ingestion_worker"},
        }

    def retry_brain(self, source_id: str) -> dict[str, Any]:
        """Worker-owned brain retry. Callers in the API/control plane must enqueue.

        Production ResearchService must use :meth:`enqueue_brain_retry`. This method
        remains for the source_ingestion worker (and explicitly allowed inprocess_test).
        """
        if not allow_inprocess_execution(self.settings):
            # Soft fence for accidental API callers — prefer enqueue when jobs bound.
            if self.jobs is not None:
                return self.enqueue_brain_retry(source_id)
            raise ResearchError(
                "SOURCE_INGESTION_UNAVAILABLE",
                "Brain retry must execute on the source_ingestion worker",
                http_status=503,
                details={"source_id": source_id},
            )
        container = self.ingestion.get_container(source_id)
        if container and container.get("archive_type"):
            progress = self.pipeline().retry_brain_only(source_id)
            return {"source_id": source_id, "progress": progress.public_dict()}
        # Single-file brain retry via research brain sync path
        source = self.research.get_source(source_id)
        if source is None:
            raise ResearchError("SOURCE_NOT_FOUND", source_id, http_status=404)
        if not source.snapshot_path:
            raise ResearchError("NO_SNAPSHOT", "No snapshot to sync", http_status=422)
        text = Path(source.snapshot_path).read_text(encoding="utf-8")
        synced = self.pipeline()._brain_sync(source, text)
        return {"source": synced.public_dict()}

    def process_next(self) -> str | None:
        """Claim and run one source_ingestion job (in-process or external worker)."""
        if self.jobs is None:
            return None
        from Data.modules.jobs.store import JobStore

        store: JobStore = self.jobs.store
        worker_id = f"source-ingestion-{uuid.uuid4().hex[:10]}"
        job = store.claim_next_queued(
            worker_id=worker_id,
            lease_ttl_seconds=float(getattr(self.settings, "lease_ttl_seconds", 30.0) or 30.0),
            capability_ids={CAPABILITY_PROCESS, CAPABILITY_BRAIN_RETRY},
            worker_pool="source_ingestion",
        )
        if job is None:
            # Also claim jobs enqueued without worker_pool set (legacy/API)
            job = store.claim_next_queued(
                worker_id=worker_id,
                lease_ttl_seconds=float(getattr(self.settings, "lease_ttl_seconds", 30.0) or 30.0),
                capability_ids={CAPABILITY_PROCESS, CAPABILITY_BRAIN_RETRY},
            )
        if job is None:
            return None
        return self.process_job(job.job_id, worker_id=worker_id, already_claimed=True, job=job)

    def process_job(
        self,
        job_id: str,
        *,
        worker_id: str = "",
        already_claimed: bool = False,
        job: Any | None = None,
    ) -> str | None:
        """Execute a specific source_ingestion job (fabric or standalone).

        When ``already_claimed`` is True the JobStore lease is owned by the caller
        (Worker Fabric claim). Do not re-claim.
        """
        if self.jobs is None:
            return None
        from Data.modules.jobs.leases import fenced_transition
        from Data.modules.jobs.store import JobStore

        store: JobStore = self.jobs.store
        wid = worker_id or f"source-ingestion-{uuid.uuid4().hex[:10]}"
        current = job
        if current is None:
            current = store.get(job_id)
        if current is None:
            return None
        if not already_claimed:
            # Standalone path may receive an id that still needs claiming — refuse
            # to steal another worker's lease; only process if we can own it.
            if current.state != JobState.QUEUED:
                # Already ours / running elsewhere — execute only if lease matches.
                if current.lease_owner and current.lease_owner != wid:
                    raise RuntimeError(
                        f"SOURCE_INGESTION_LEASE_MISMATCH: job={job_id} owner={current.lease_owner}"
                    )
            else:
                claimed = store.claim_next_queued(
                    worker_id=wid,
                    lease_ttl_seconds=float(
                        getattr(self.settings, "lease_ttl_seconds", 30.0) or 30.0
                    ),
                    capability_ids={CAPABILITY_PROCESS, CAPABILITY_BRAIN_RETRY},
                    worker_pool="source_ingestion",
                )
                if claimed is None or claimed.job_id != job_id:
                    return None
                current = claimed
        try:
            source_id = str(current.arguments.get("source_id") or "")
            pipe = SourceIngestionPipeline(
                research_store=self.research,
                ingestion_store=self.ingestion,
                settings=self.settings,
                knowledge=self.knowledge,
                snapshots_root=self.snapshots_root,
                staging_root=self.staging_root,
                dataset_service=self.dataset_service,
                emit=self._emit_research_event,
                enqueue_ocr=self.enqueue_ocr,
                parent_job_id=current.job_id,
                root_job_id=getattr(current, "root_job_id", None) or current.job_id,
            )
            if current.capability_id == CAPABILITY_BRAIN_RETRY:
                pipe.retry_brain_only(source_id)
            else:
                pipe.process_source(source_id)
            fenced_transition(
                store,
                current.job_id,
                JobState.COMPLETED,
                worker_id=wid,
                result={
                    "source_id": source_id,
                    "progress": self.get_status(source_id).public_dict(),
                },
            )
            return current.job_id
        except Exception as exc:  # noqa: BLE001
            try:
                fenced_transition(
                    store,
                    current.job_id,
                    JobState.FAILED,
                    worker_id=wid,
                    error=str(exc)[:500],
                )
            except Exception:  # noqa: BLE001
                pass
            return current.job_id
        finally:
            if not already_claimed:
                try:
                    store.release_lease(current.job_id, worker_id=wid)
                except Exception:  # noqa: BLE001
                    pass

    def start_background(self, *, poll_interval_s: float | None = None) -> None:
        # Hard fence: never spawn API-thread ingestion unless inprocess_test allow gate.
        if not allow_inprocess_execution(self.settings):
            return
        if self.settings.runner not in {"inprocess", "inprocess_test"}:
            return
        interval = float(poll_interval_s if poll_interval_s is not None else self.settings.worker_poll_interval)
        with self._lock:
            if self._bg_thread and self._bg_thread.is_alive():
                return
            self._bg_stop.clear()
            self._bg_thread = threading.Thread(
                target=self._bg_loop,
                args=(interval,),
                name="leviathan-source-ingestion",
                daemon=True,
            )
            self._bg_thread.start()

    def stop_background(self, *, timeout: float = 2.0) -> None:
        self._bg_stop.set()
        self._wake.set()
        thread = self._bg_thread
        if thread and thread.is_alive():
            thread.join(timeout=timeout)

    def _bg_loop(self, poll_interval_s: float) -> None:
        while not self._bg_stop.is_set():
            job_id = self.process_next()
            if job_id is None:
                self._wake.wait(timeout=poll_interval_s)
                self._wake.clear()
