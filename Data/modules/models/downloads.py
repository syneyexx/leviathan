"""Model download / acquisition manager — Control Plane orchestration only.

Bulk transfer executes in the ``model_download`` worker pool. This class
validates requests, creates durable domain rows, enqueues fabric jobs,
deduplicates active downloads, and propagates cancellation.
"""

from __future__ import annotations

import json
import re
import uuid
from pathlib import Path
from typing import Any, Callable

from Data.modules.model_download.errors import ModelDownloadError, ModelDownloadErrorCode
from Data.modules.model_download.facade import ModelDownloadClient
from Data.modules.models.contracts import DownloadJob, DownloadState
from Data.modules.models.errors import (
    NETWORK_BLOCKED,
    UNSAFE_PATH,
    VALIDATION_ERROR,
    ModelControlError,
)
from Data.modules.models.registry import ModelRegistry
from Data.modules.models.store import ModelStore, utc_now


_HF_REPO_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._/-]*$")
_ACTIVE = {
    DownloadState.QUEUED,
    DownloadState.DOWNLOADING,
    DownloadState.VERIFYING,
    DownloadState.PAUSED,
}


class DownloadManager:
    def __init__(
        self,
        store: ModelStore,
        registry: ModelRegistry,
        *,
        download_root: Path,
        allow_outbound: bool,
        get_adapter: Callable[[str], Any] | None = None,
        job_runtime: Any | None = None,
    ) -> None:
        self.store = store
        self.registry = registry
        self.download_root = download_root
        self.allow_outbound = allow_outbound
        self._get_adapter = get_adapter
        self.job_runtime = job_runtime
        self.download_root.mkdir(parents=True, exist_ok=True)

    def bind_job_runtime(self, job_runtime: Any | None) -> None:
        self.job_runtime = job_runtime

    def list_jobs(self) -> list[DownloadJob]:
        return [self._row_to_job(row) for row in self.store.list_downloads()]

    def get_job(self, download_id: str) -> DownloadJob:
        row = self.store.get_download(download_id)
        if not row:
            raise ModelControlError(
                code="MODEL_NOT_FOUND",
                message=f"Download not found: {download_id}",
                http_status=404,
            )
        return self._row_to_job(row)

    def find_active(
        self,
        *,
        source: str,
        repository_id: str,
        revision: str | None = None,
    ) -> DownloadJob | None:
        rev = revision or "main"
        for job in self.list_jobs():
            if job.state not in _ACTIVE:
                continue
            if (
                job.source == source
                and job.repository_id == repository_id
                and (job.revision or "main") == rev
            ):
                return job
        return None

    async def start_huggingface(
        self,
        *,
        repository_id: str,
        revision: str | None = None,
        filename: str | None = None,
    ) -> DownloadJob:
        if not self.allow_outbound:
            raise ModelControlError(
                code=NETWORK_BLOCKED,
                message="Outbound network is disabled; enable LEVIATHAN_NETWORK_ALLOW_OUTBOUND for Hugging Face downloads",
                http_status=403,
            )
        repo = (repository_id or "").strip()
        if not repo or not _HF_REPO_RE.match(repo) or ".." in repo:
            raise ModelControlError(
                code=VALIDATION_ERROR,
                message="Invalid Hugging Face repository id",
                http_status=422,
            )
        rev = revision or "main"
        existing = self.find_active(source="huggingface", repository_id=repo, revision=rev)
        if existing is not None:
            return existing

        download_id = str(uuid.uuid4())
        dest_dir = self._safe_dest(repo, rev)
        dest_dir.mkdir(parents=True, exist_ok=True)
        job = DownloadJob(
            download_id=download_id,
            state=DownloadState.QUEUED,
            source="huggingface",
            repository_id=repo,
            revision=rev,
            destination=str(dest_dir),
            created_at=utc_now(),
            updated_at=utc_now(),
        )
        self._persist(job, metadata={"stage": "queued"})
        fabric_job_id = self._enqueue(
            download_id=download_id,
            source="huggingface",
            repository_id=repo,
            revision=rev,
            destination=str(dest_dir),
            filename=filename,
            credential_ref="huggingface",
        )
        self._persist(job, metadata={"stage": "queued", "fabric_job_id": fabric_job_id})
        return job

    async def start_ollama_pull(
        self, *, provider_id: str, repository_id: str, revision: str | None = None
    ) -> DownloadJob:
        existing = self.find_active(
            source="ollama", repository_id=repository_id, revision=revision
        )
        if existing is not None:
            return existing

        endpoint = None
        if self._get_adapter:
            try:
                adapter = self._get_adapter(provider_id)
                endpoint = getattr(adapter, "endpoint", None) or getattr(adapter, "base_url", None)
            except Exception:  # noqa: BLE001
                endpoint = None

        download_id = str(uuid.uuid4())
        job = DownloadJob(
            download_id=download_id,
            state=DownloadState.QUEUED,
            source="ollama",
            repository_id=repository_id,
            revision=revision,
            destination=None,
            created_at=utc_now(),
            updated_at=utc_now(),
        )
        self._persist(job, metadata={"stage": "queued", "provider_id": provider_id})
        fabric_job_id = self._enqueue(
            download_id=download_id,
            source="ollama",
            repository_id=repository_id,
            revision=revision,
            endpoint=str(endpoint) if endpoint else None,
            credential_ref="none",
        )
        self._persist(
            job,
            metadata={"stage": "queued", "fabric_job_id": fabric_job_id, "provider_id": provider_id},
        )
        return job

    def cancel(self, download_id: str) -> DownloadJob:
        job = self.get_job(download_id)
        meta = self._metadata_for(download_id)
        fabric_job_id = meta.get("fabric_job_id")
        if fabric_job_id and self.job_runtime is not None:
            try:
                ModelDownloadClient(self.job_runtime).cancel(
                    str(fabric_job_id), reason="model_download_user_cancel"
                )
            except Exception:  # noqa: BLE001
                pass
        if job.state not in {
            DownloadState.COMPLETED,
            DownloadState.FAILED,
            DownloadState.CANCELLED,
        }:
            job.state = DownloadState.CANCELLED
            job.updated_at = utc_now()
            job.error = job.error or "cancelled"
            self._persist(job, metadata={**meta, "stage": "cancelled"})
        return job

    def _enqueue(
        self,
        *,
        download_id: str,
        source: str,
        repository_id: str,
        revision: str | None = None,
        destination: str | None = None,
        filename: str | None = None,
        credential_ref: str | None = None,
        endpoint: str | None = None,
    ) -> str:
        if self.job_runtime is None:
            raise ModelControlError(
                code=ModelDownloadErrorCode.MODEL_DOWNLOAD_EXECUTION_UNAVAILABLE.value,
                message=(
                    "Model download execution unavailable: job runtime not bound. "
                    "Control Plane does not perform bulk model transfers."
                ),
                http_status=503,
                retryable=True,
            )
        client = ModelDownloadClient(self.job_runtime)
        try:
            fabric_job = client.submit(
                download_id=download_id,
                source=source,
                repository_id=repository_id,
                revision=revision,
                destination=destination,
                filename=filename,
                credential_ref=credential_ref,
                endpoint=endpoint,
                requested_by="model_control_plane",
            )
        except ModelDownloadError as exc:
            # Mark domain row failed so UI does not show stuck QUEUED.
            row = self.store.get_download(download_id)
            if row:
                failed = self._row_to_job(row)
                failed.state = DownloadState.FAILED
                failed.error = exc.message
                self._persist(failed, metadata={"stage": "failed", "error_code": exc.code.value})
            raise ModelControlError(
                code=exc.code.value,
                message=exc.message,
                http_status=exc.http_status,
                retryable=exc.retryable,
                details=dict(exc.details),
            ) from exc
        return str(fabric_job.job_id)

    def _safe_dest(self, repo: str, revision: str) -> Path:
        safe_repo = repo.replace("/", "__")
        safe_rev = re.sub(r"[^A-Za-z0-9._-]", "_", revision)
        path = (self.download_root / safe_repo / safe_rev).resolve()
        return self._ensure_under_root(path)

    def _ensure_under_root(self, path: Path) -> Path:
        root = self.download_root.resolve()
        resolved = path.resolve()
        try:
            resolved.relative_to(root)
        except ValueError as exc:
            raise ModelControlError(
                code=UNSAFE_PATH,
                message="Destination escapes download root",
                http_status=400,
            ) from exc
        return resolved

    def _metadata_for(self, download_id: str) -> dict[str, Any]:
        row = self.store.get_download(download_id) or {}
        raw = row.get("metadata_json")
        if isinstance(raw, str) and raw:
            try:
                data = json.loads(raw)
                return data if isinstance(data, dict) else {}
            except json.JSONDecodeError:
                return {}
        meta = row.get("metadata")
        return dict(meta) if isinstance(meta, dict) else {}

    def _persist(self, job: DownloadJob, *, metadata: dict[str, Any] | None = None) -> None:
        meta = metadata if metadata is not None else self._metadata_for(job.download_id)
        self.store.upsert_download(
            {
                "download_id": job.download_id,
                "state": job.state.value,
                "source": job.source,
                "repository_id": job.repository_id,
                "revision": job.revision,
                "destination": job.destination,
                "bytes_downloaded": job.bytes_downloaded,
                "total_bytes": job.total_bytes,
                "speed_bps": job.speed_bps,
                "eta_seconds": job.eta_seconds,
                "error": job.error,
                "model_id": job.model_id,
                "created_at": job.created_at,
                "metadata": meta,
            }
        )

    def _row_to_job(self, row: dict[str, Any]) -> DownloadJob:
        return DownloadJob(
            download_id=row["download_id"],
            state=DownloadState(row["state"]),
            source=row["source"],
            repository_id=row.get("repository_id"),
            revision=row.get("revision"),
            destination=row.get("destination"),
            bytes_downloaded=row.get("bytes_downloaded"),
            total_bytes=row.get("total_bytes"),
            speed_bps=row.get("speed_bps"),
            eta_seconds=row.get("eta_seconds"),
            error=row.get("error"),
            created_at=row.get("created_at"),
            updated_at=row.get("updated_at"),
            model_id=row.get("model_id"),
        )


# Re-export legacy names used by older tests/imports.
__all__ = ["DownloadManager", "MODEL_DOWNLOAD_FAILED", "DOWNLOAD_CANCELLED"]
