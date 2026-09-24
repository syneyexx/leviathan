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
from .pipeline import SourceIngestionPipeline
from .settings import SourceIngestionSettings, load_source_ingestion_settings
from .store import IngestionStore
from .types import (
    CAPABILITY_BRAIN_RETRY,
    CAPABILITY_PROCESS,
    IngestionError,
    IngestionPhase,
)


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
        # Peek first chunk for detection without loading whole file
        peek = stream.read(8192)
        if hasattr(stream, "seek"):
            try:
                stream.seek(0)
            except Exception:  # noqa: BLE001
                # Rebuild a combined stream from peek + rest
                import io

                rest = stream.read()
                stream = io.BytesIO(peek + rest)
        else:
            import io

            rest = stream.read()
            stream = io.BytesIO(peek + rest)

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
            return None
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
        except Exception:  # noqa: BLE001
            return None

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

    def retry_brain(self, source_id: str) -> dict[str, Any]:
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
        try:
            source_id = str(job.arguments.get("source_id") or "")
            if job.capability_id == CAPABILITY_BRAIN_RETRY:
                self.pipeline().retry_brain_only(source_id)
            else:
                self.pipeline().process_source(source_id)
            store.transition(
                job.job_id,
                JobState.COMPLETED,
                result={"source_id": source_id, "progress": self.get_status(source_id).public_dict()},
            )
            return job.job_id
        except Exception as exc:  # noqa: BLE001
            try:
                store.transition(job.job_id, JobState.FAILED, error=str(exc)[:500])
            except Exception:  # noqa: BLE001
                pass
            return job.job_id
        finally:
            try:
                store.release_lease(job.job_id, worker_id=worker_id)
            except Exception:  # noqa: BLE001
                pass

    def start_background(self, *, poll_interval_s: float | None = None) -> None:
        if self.settings.runner != "inprocess":
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
