"""Model download / acquisition manager."""

from __future__ import annotations

import asyncio
import hashlib
import re
import threading
import uuid
from pathlib import Path
from typing import Any, Callable
from urllib.parse import urlparse

import httpx

from Data.modules.models.contracts import (
    CapabilityState,
    DownloadJob,
    DownloadState,
    ModelCapabilities,
    ModelDescriptor,
    ModelHealthState,
    ModelLifecycleState,
    ModelSource,
)
from Data.modules.models.errors import (
    DOWNLOAD_CANCELLED,
    MODEL_DOWNLOAD_FAILED,
    NETWORK_BLOCKED,
    UNSAFE_PATH,
    VALIDATION_ERROR,
    ModelControlError,
)
from Data.modules.models.registry import ModelRegistry
from Data.modules.models.store import ModelStore, utc_now


_HF_REPO_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._/-]*$")


class DownloadManager:
    def __init__(
        self,
        store: ModelStore,
        registry: ModelRegistry,
        *,
        download_root: Path,
        allow_outbound: bool,
        get_adapter: Callable[[str], Any] | None = None,
    ) -> None:
        self.store = store
        self.registry = registry
        self.download_root = download_root
        self.allow_outbound = allow_outbound
        self._get_adapter = get_adapter
        self.download_root.mkdir(parents=True, exist_ok=True)
        self._cancel: dict[str, threading.Event] = {}
        self._tasks: dict[str, asyncio.Task[None]] = {}

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
        download_id = str(uuid.uuid4())
        dest_dir = self._safe_dest(repo, revision or "main")
        dest_dir.mkdir(parents=True, exist_ok=True)
        job = DownloadJob(
            download_id=download_id,
            state=DownloadState.QUEUED,
            source="huggingface",
            repository_id=repo,
            revision=revision or "main",
            destination=str(dest_dir),
            created_at=utc_now(),
            updated_at=utc_now(),
        )
        self._persist(job)
        self._cancel[download_id] = threading.Event()
        task = asyncio.create_task(
            self._run_hf_download(job, filename=filename),
            name=f"hf-download-{download_id}",
        )
        self._tasks[download_id] = task
        return job

    async def start_ollama_pull(
        self, *, provider_id: str, repository_id: str, revision: str | None = None
    ) -> DownloadJob:
        if not self._get_adapter:
            raise ModelControlError(
                code=MODEL_DOWNLOAD_FAILED,
                message="No adapter factory configured for Ollama pull",
                http_status=500,
            )
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
        self._persist(job)
        self._cancel[download_id] = threading.Event()

        async def _run() -> None:
            job.state = DownloadState.DOWNLOADING
            self._persist(job)
            try:
                adapter = self._get_adapter(provider_id)
                if not hasattr(adapter, "pull"):
                    raise ModelControlError(
                        code=MODEL_DOWNLOAD_FAILED,
                        message="Provider does not support pull",
                        provider_id=provider_id,
                        http_status=409,
                    )
                if self._cancel[download_id].is_set():
                    raise ModelControlError(
                        code=DOWNLOAD_CANCELLED,
                        message="Download cancelled",
                        http_status=409,
                    )
                await adapter.pull(repository_id, revision=revision)
                job.state = DownloadState.COMPLETED
                job.updated_at = utc_now()
                self._persist(job)
            except ModelControlError as exc:
                job.state = (
                    DownloadState.CANCELLED
                    if exc.code == DOWNLOAD_CANCELLED
                    else DownloadState.FAILED
                )
                job.error = exc.message
                self._persist(job)
            except Exception as exc:  # noqa: BLE001
                job.state = DownloadState.FAILED
                job.error = str(exc)
                self._persist(job)

        self._tasks[download_id] = asyncio.create_task(_run())
        return job

    def cancel(self, download_id: str) -> DownloadJob:
        job = self.get_job(download_id)
        event = self._cancel.get(download_id)
        if event:
            event.set()
        task = self._tasks.get(download_id)
        if task and not task.done():
            task.cancel()
        if job.state not in {DownloadState.COMPLETED, DownloadState.FAILED, DownloadState.CANCELLED}:
            job.state = DownloadState.CANCELLED
            job.updated_at = utc_now()
            self._persist(job)
        return job

    async def _run_hf_download(self, job: DownloadJob, *, filename: str | None) -> None:
        cancel = self._cancel[job.download_id]
        try:
            job.state = DownloadState.DOWNLOADING
            self._persist(job)
            # Resolve a concrete file via Hugging Face resolve URL.
            # Prefer an explicit filename; otherwise attempt to download README as a probe is wrong —
            # require filename for safety when listing isn't available without outbound API complexity.
            if not filename:
                # Try common GGUF listing via API (tree). If blocked/fails, fail honestly.
                tree_url = (
                    f"https://huggingface.co/api/models/{job.repository_id}/tree/{job.revision}"
                )
                async with httpx.AsyncClient(timeout=60.0, follow_redirects=True) as client:
                    response = await client.get(tree_url)
                    response.raise_for_status()
                    tree = response.json()
                candidates = [
                    item["path"]
                    for item in tree
                    if isinstance(item, dict)
                    and str(item.get("path", "")).lower().endswith((".gguf", ".safetensors"))
                ]
                if not candidates:
                    raise ModelControlError(
                        code=MODEL_DOWNLOAD_FAILED,
                        message="No .gguf or .safetensors files found in repository",
                        http_status=404,
                    )
                filename = candidates[0]

            safe_name = Path(filename).name
            if safe_name != filename.replace("\\", "/").split("/")[-1] or ".." in filename:
                raise ModelControlError(code=UNSAFE_PATH, message="Unsafe filename", http_status=400)
            dest = Path(job.destination or self.download_root) / safe_name
            dest = self._ensure_under_root(dest)
            url = (
                f"https://huggingface.co/{job.repository_id}/resolve/{job.revision}/{filename}"
            )
            sha = hashlib.sha256()
            downloaded = 0
            total = None
            started = utc_now()
            async with httpx.AsyncClient(timeout=None, follow_redirects=True) as client:
                async with client.stream("GET", url) as response:
                    response.raise_for_status()
                    total_header = response.headers.get("content-length")
                    if total_header and total_header.isdigit():
                        total = int(total_header)
                        job.total_bytes = total
                    with dest.open("wb") as handle:
                        async for chunk in response.aiter_bytes(chunk_size=1024 * 1024):
                            if cancel.is_set():
                                raise ModelControlError(
                                    code=DOWNLOAD_CANCELLED,
                                    message="Download cancelled",
                                    http_status=409,
                                )
                            handle.write(chunk)
                            sha.update(chunk)
                            downloaded += len(chunk)
                            job.bytes_downloaded = downloaded
                            job.state = DownloadState.DOWNLOADING
                            self._persist(job)

            job.state = DownloadState.VERIFYING
            self._persist(job)
            checksum = sha.hexdigest()
            job.state = DownloadState.COMPLETED
            job.bytes_downloaded = downloaded
            job.total_bytes = total or downloaded
            job.updated_at = utc_now()
            self._persist(job)

            # Register imported model metadata (file on disk; not auto-loaded).
            model_id = f"imported:{safe_name}"
            descriptor = ModelDescriptor(
                id=model_id,
                display_name=safe_name,
                provider_id="local_import",
                runtime_id="file",
                source=ModelSource.DOWNLOADED,
                format="gguf" if safe_name.lower().endswith(".gguf") else (
                    "safetensors" if safe_name.lower().endswith(".safetensors") else None
                ),
                disk_size_bytes=downloaded,
                local_path=str(dest),
                capabilities=ModelCapabilities(
                    chat=CapabilityState.UNKNOWN,
                ),
                lifecycle_state=ModelLifecycleState.AVAILABLE,
                health=ModelHealthState.UNKNOWN,
                metadata={
                    "sha256": checksum,
                    "repositoryId": job.repository_id,
                    "revision": job.revision,
                    "downloadedAt": started,
                },
            )
            self.registry.store.upsert_model(
                {
                    "model_id": descriptor.id,
                    "display_name": descriptor.display_name,
                    "provider_id": descriptor.provider_id,
                    "runtime_id": descriptor.runtime_id,
                    "source": descriptor.source.value,
                    "format": descriptor.format,
                    "disk_size_bytes": descriptor.disk_size_bytes,
                    "local_path": descriptor.local_path,
                    "capabilities": descriptor.capabilities.public_dict(),
                    "lifecycle_state": descriptor.lifecycle_state.value,
                    "health": descriptor.health.value,
                    "metadata": descriptor.metadata,
                }
            )
            job.model_id = model_id
            self._persist(job)
            self.store.append_audit(
                "model_downloaded",
                detail={"downloadId": job.download_id, "modelId": model_id, "sha256": checksum},
            )
        except asyncio.CancelledError:
            job.state = DownloadState.CANCELLED
            job.error = "cancelled"
            self._persist(job)
        except ModelControlError as exc:
            job.state = (
                DownloadState.CANCELLED if exc.code == DOWNLOAD_CANCELLED else DownloadState.FAILED
            )
            job.error = exc.message
            self._persist(job)
        except Exception as exc:  # noqa: BLE001
            job.state = DownloadState.FAILED
            job.error = str(exc)
            self._persist(job)
        finally:
            self._tasks.pop(job.download_id, None)

    def _safe_dest(self, repo: str, revision: str) -> Path:
        safe_repo = repo.replace("/", "__")
        safe_rev = re.sub(r"[^A-Za-z0-9._-]", "_", revision)
        path = (self.download_root / safe_repo / safe_rev).resolve()
        return self._ensure_under_root(path)

    def _ensure_under_root(self, path: Path) -> Path:
        root = self.download_root.resolve()
        resolved = path.resolve()
        if root not in resolved.parents and resolved != root:
            # also allow exact file under root
            try:
                resolved.relative_to(root)
            except ValueError as exc:
                raise ModelControlError(
                    code=UNSAFE_PATH,
                    message="Destination escapes download root",
                    http_status=400,
                ) from exc
        return resolved

    def _persist(self, job: DownloadJob) -> None:
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
