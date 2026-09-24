"""Control-plane facade — submit/await/cancel model downloads without owning transfer."""

from __future__ import annotations

import os
import threading
import time
from typing import Any

from Data.modules.jobs.states import JobState, TERMINAL_JOB_STATES
from Data.modules.model_download.errors import ModelDownloadError, ModelDownloadErrorCode
from Data.modules.model_download.readiness import model_download_workers_ready
from Data.modules.workers.pools import pool_for_capability


_CLIENT_LOCK = threading.Lock()
_CLIENT: ModelDownloadClient | None = None


class ModelDownloadClient:
    """Thin control-plane client that enqueues model_download jobs."""

    def __init__(self, job_runtime: Any) -> None:
        self.job_runtime = job_runtime

    def _db_path(self) -> Any:
        return getattr(getattr(self.job_runtime, "store", None), "path", None)

    def require_workers_ready(self) -> None:
        if not model_download_workers_ready(self._db_path()):
            raise ModelDownloadError(
                ModelDownloadErrorCode.MODEL_DOWNLOAD_EXECUTION_UNAVAILABLE,
                "Model download workers are unavailable; Control Plane will not perform bulk transfers.",
                retryable=True,
                http_status=503,
            )

    def submit(
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
        requested_by: str = "api",
        timeout_seconds: float | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> Any:
        self.require_workers_ready()
        arguments: dict[str, Any] = {
            "download_id": download_id,
            "source": source,
            "repository_id": repository_id,
            "revision": revision or "main",
            "destination": destination,
            "credential_ref": credential_ref or ("huggingface" if source == "huggingface" else "none"),
        }
        if filename:
            arguments["filename"] = filename
        if endpoint:
            arguments["endpoint"] = endpoint

        cap_id = "model_download.start"
        worker_pool = pool_for_capability(cap_id)
        # Heavy downloads: long timeout (hours), not provider 120s.
        timeout = float(
            timeout_seconds
            if timeout_seconds is not None
            else float(os.environ.get("LEVIATHAN_MODEL_DOWNLOAD_JOB_TIMEOUT") or 0)
            or (6 * 3600.0)
        )
        return self.job_runtime.enqueue(
            capability_id=cap_id,
            arguments=arguments,
            requested_by=requested_by,
            metadata=metadata,
            idempotency_key=f"model_download:{source}:{repository_id}:{revision or 'main'}:{download_id}",
            latency_class="background",
            worker_pool=worker_pool or "model_download",
            resource_class="IO_HEAVY",
            priority=80,
            timeout_seconds=timeout,
            domain="model_download",
            consumer="model_download",
        )

    def cancel(self, job_id: str, *, reason: str | None = None) -> Any:
        return self.job_runtime.cancel(job_id, reason=reason or "model_download_cancel")

    def await_terminal(
        self,
        job_id: str,
        *,
        poll_seconds: float = 0.1,
        timeout_seconds: float | None = None,
    ) -> Any:
        timeout = float(timeout_seconds if timeout_seconds is not None else 30.0)
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            job = self.job_runtime.get(job_id)
            if job is None:
                raise KeyError(f"Unknown job: {job_id}")
            if job.state in TERMINAL_JOB_STATES:
                return job
            time.sleep(poll_seconds)
        raise ModelDownloadError(
            ModelDownloadErrorCode.MODEL_DOWNLOAD_FAILED,
            f"Timed out waiting for model download job {job_id}",
            retryable=False,
            http_status=504,
        )


def get_model_download_client(job_runtime: Any | None = None) -> ModelDownloadClient:
    global _CLIENT
    with _CLIENT_LOCK:
        if _CLIENT is not None and (
            job_runtime is None or _CLIENT.job_runtime is job_runtime
        ):
            return _CLIENT
        if job_runtime is None:
            raise RuntimeError("ModelDownloadClient requires job_runtime on first use")
        _CLIENT = ModelDownloadClient(job_runtime)
        return _CLIENT
