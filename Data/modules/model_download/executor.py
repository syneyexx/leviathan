"""Model download worker executor — owns bulk HF/Ollama acquisition I/O."""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import time
from pathlib import Path
from typing import Any, Callable

import httpx

from Data.modules.jobs.states import JobState
from Data.modules.model_download.errors import ModelDownloadError, ModelDownloadErrorCode
from Data.modules.models.contracts import (
    CapabilityState,
    DownloadState,
    ModelCapabilities,
    ModelDescriptor,
    ModelHealthState,
    ModelLifecycleState,
    ModelSource,
)
from Data.modules.models.registry import ModelRegistry
from Data.modules.models.store import ModelStore, utc_now
from Data.modules.provider_io.credentials import resolve_credential


CancelCheck = Callable[[], bool]
_HF_REPO_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._/-]*$")
_ACTIVE_STATES = {
    DownloadState.QUEUED.value,
    DownloadState.DOWNLOADING.value,
    DownloadState.VERIFYING.value,
}


def _env_float(name: str, default: float) -> float:
    raw = (os.environ.get(name) or "").strip()
    if not raw:
        return default
    try:
        return float(raw)
    except ValueError:
        return default


def _disk_free_bytes(path: Path) -> int | None:
    try:
        usage = shutil.disk_usage(path if path.exists() else path.parent)
        return int(usage.free)
    except OSError:
        return None


def disk_preflight(*, target_dir: Path, bytes_total: int | None, bytes_already: int = 0) -> dict[str, Any]:
    """Fail early when free disk is insufficient for a known-size download."""
    target_dir.mkdir(parents=True, exist_ok=True)
    free = _disk_free_bytes(target_dir)
    if bytes_total is None:
        return {"ok": True, "skipped": True, "diskFreeBytes": free}
    remaining = max(0, int(bytes_total) - max(0, bytes_already))
    overhead = int(remaining * 0.15)
    reserve = 512 * 1024 * 1024
    required = remaining + overhead + reserve
    ok = free is None or free >= required
    result = {
        "ok": ok,
        "requiredBytes": required,
        "availableBytes": free,
        "missingBytes": None if free is None else max(0, required - free),
        "targetPath": str(target_dir),
    }
    if not ok:
        raise ModelDownloadError(
            ModelDownloadErrorCode.MODEL_DOWNLOAD_STORAGE_FULL,
            (
                f"Insufficient disk space for model download: "
                f"required={required} available={free}"
            ),
            http_status=507,
            details=result,
        )
    return result


class ModelDownloadExecutor:
    """Process-local executor owned by one model_download worker."""

    def __init__(self, *, db_path: str | Path | None = None) -> None:
        path = Path(
            db_path
            or os.environ.get("LEVIATHAN_DB_PATH")
            or "Data/state/leviathan.db"
        )
        self.db_path = path
        self.store = ModelStore(path)
        self.registry = ModelRegistry(self.store)
        self.download_root = path.parent / "model_downloads"
        self.download_root.mkdir(parents=True, exist_ok=True)
        self.connect_timeout = _env_float("LEVIATHAN_MODEL_DOWNLOAD_CONNECT_TIMEOUT", 30.0)
        self.stall_timeout = _env_float("LEVIATHAN_MODEL_DOWNLOAD_STALL_TIMEOUT", 120.0)
        self._client: httpx.Client | None = None

    def close(self) -> None:
        if self._client is not None:
            self._client.close()
            self._client = None

    def _http(self) -> httpx.Client:
        if self._client is None:
            self._client = httpx.Client(
                timeout=httpx.Timeout(
                    connect=self.connect_timeout,
                    read=self.stall_timeout,
                    write=self.stall_timeout,
                    pool=self.connect_timeout,
                ),
                follow_redirects=True,
            )
        return self._client

    def execute_job(self, ctx: dict[str, Any], job: Any) -> dict[str, Any]:
        store = ctx["job_store"]
        args = dict(job.arguments or {})
        download_id = str(args.get("download_id") or "").strip()
        if not download_id:
            raise ModelDownloadError(
                ModelDownloadErrorCode.VALIDATION_ERROR,
                "model_download.start requires download_id",
                http_status=422,
            )
        worker_id = str(ctx.get("worker_id") or f"model_download-{os.getpid()}")
        source = str(args.get("source") or "huggingface").strip().lower()

        def cancel_check() -> bool:
            try:
                current = store.get(job.job_id)
            except Exception:  # noqa: BLE001
                return False
            if current is None:
                return True
            if current.state == JobState.CANCEL_REQUESTED:
                return True
            row = self.store.get_download(download_id)
            return bool(row and row.get("state") == DownloadState.CANCELLED.value)

        def heartbeat() -> None:
            try:
                if hasattr(store, "heartbeat_lease"):
                    store.heartbeat_lease(
                        job.job_id,
                        worker_id=worker_id,
                        ttl_seconds=float(ctx.get("lease_ttl_seconds") or 60.0),
                    )
            except Exception:  # noqa: BLE001
                pass

        def progress(
            *,
            phase: str,
            bytes_downloaded: int | None = None,
            total_bytes: int | None = None,
            speed_bps: float | None = None,
            eta_seconds: float | None = None,
            message: str | None = None,
            current_file: str | None = None,
            state: str | None = None,
            error: str | None = None,
            model_id: str | None = None,
        ) -> None:
            row = self.store.get_download(download_id) or {}
            meta = {}
            raw_meta = row.get("metadata_json")
            if isinstance(raw_meta, str) and raw_meta:
                try:
                    meta = json.loads(raw_meta)
                except json.JSONDecodeError:
                    meta = {}
            elif isinstance(row.get("metadata"), dict):
                meta = dict(row["metadata"])
            meta["fabric_job_id"] = job.job_id
            meta["worker_id"] = worker_id
            meta["worker_pid"] = os.getpid()
            meta["stage"] = phase
            if current_file:
                meta["current_file"] = current_file
            if bytes_downloaded is not None and total_bytes and total_bytes > 0:
                meta["progress_percent"] = round(100.0 * bytes_downloaded / total_bytes, 2)
            elif bytes_downloaded is not None:
                meta["progress_percent"] = None  # indeterminate
            payload = {
                "download_id": download_id,
                "state": state or row.get("state") or DownloadState.DOWNLOADING.value,
                "source": row.get("source") or source,
                "repository_id": row.get("repository_id") or args.get("repository_id"),
                "revision": row.get("revision") or args.get("revision"),
                "destination": row.get("destination") or args.get("destination"),
                "bytes_downloaded": bytes_downloaded
                if bytes_downloaded is not None
                else row.get("bytes_downloaded"),
                "total_bytes": total_bytes if total_bytes is not None else row.get("total_bytes"),
                "speed_bps": speed_bps,
                "eta_seconds": eta_seconds,
                "error": error if error is not None else row.get("error"),
                "model_id": model_id if model_id is not None else row.get("model_id"),
                "created_at": row.get("created_at"),
                "metadata": meta,
            }
            self.store.upsert_download(payload)
            pct = None
            if bytes_downloaded is not None and total_bytes and total_bytes > 0:
                pct = max(0.0, min(1.0, bytes_downloaded / total_bytes))
            try:
                store.update_progress(
                    job.job_id,
                    progress=pct,
                    phase=phase,
                    message=message or current_file or phase,
                )
            except Exception:  # noqa: BLE001
                pass

        try:
            if source == "ollama":
                result = self._run_ollama(args, cancel_check=cancel_check, progress=progress, heartbeat=heartbeat)
            else:
                result = self._run_hf(args, cancel_check=cancel_check, progress=progress, heartbeat=heartbeat)
            result["worker_pid"] = os.getpid()
            result["download_id"] = download_id
            store.transition(job.job_id, JobState.COMPLETED, result=result)
            return result
        except ModelDownloadError as exc:
            cancelled = exc.code == ModelDownloadErrorCode.MODEL_DOWNLOAD_CANCELLED
            progress(
                phase="cancelled" if cancelled else "failed",
                state=DownloadState.CANCELLED.value if cancelled else DownloadState.FAILED.value,
                error=exc.message,
            )
            payload = {
                "status": "cancelled" if cancelled else "failed",
                "error": exc.public_dict(),
                "worker_pid": os.getpid(),
                "download_id": download_id,
            }
            store.transition(
                job.job_id,
                JobState.CANCELLED if cancelled else JobState.FAILED,
                error=exc.code.value,
                result=payload,
            )
            return payload
        except Exception as exc:  # noqa: BLE001
            progress(
                phase="failed",
                state=DownloadState.FAILED.value,
                error=str(exc),
            )
            payload = {
                "status": "failed",
                "error": {
                    "code": ModelDownloadErrorCode.MODEL_DOWNLOAD_FAILED.value,
                    "message": str(exc),
                },
                "worker_pid": os.getpid(),
                "download_id": download_id,
            }
            store.transition(job.job_id, JobState.FAILED, error=str(exc), result=payload)
            return payload

    def _auth_headers(self, credential_ref: str | None) -> dict[str, str]:
        cred = resolve_credential(credential_ref or "huggingface")
        if cred.api_key:
            return {"Authorization": f"Bearer {cred.api_key}"}
        return {}

    def _ensure_under_root(self, path: Path) -> Path:
        root = self.download_root.resolve()
        resolved = path.resolve()
        try:
            resolved.relative_to(root)
        except ValueError as exc:
            raise ModelDownloadError(
                ModelDownloadErrorCode.UNSAFE_PATH,
                "Destination escapes download root",
                http_status=400,
            ) from exc
        return resolved

    def _run_hf(
        self,
        args: dict[str, Any],
        *,
        cancel_check: CancelCheck,
        progress: Callable[..., None],
        heartbeat: Callable[[], None],
    ) -> dict[str, Any]:
        download_id = str(args["download_id"])
        repo = str(args.get("repository_id") or "").strip()
        revision = str(args.get("revision") or "main").strip() or "main"
        filename = (str(args["filename"]).strip() if args.get("filename") else None)
        destination = Path(str(args.get("destination") or ""))
        if not repo or not _HF_REPO_RE.match(repo) or ".." in repo:
            raise ModelDownloadError(
                ModelDownloadErrorCode.VALIDATION_ERROR,
                "Invalid Hugging Face repository id",
                http_status=422,
            )
        dest_dir = self._ensure_under_root(destination if destination.parts else self._safe_dest(repo, revision))
        dest_dir.mkdir(parents=True, exist_ok=True)
        headers = self._auth_headers(args.get("credential_ref"))

        if cancel_check():
            raise ModelDownloadError(
                ModelDownloadErrorCode.MODEL_DOWNLOAD_CANCELLED,
                "Download cancelled",
                http_status=409,
            )

        progress(phase="resolving", state=DownloadState.DOWNLOADING.value)
        heartbeat()
        client = self._http()
        files_to_fetch: list[str]
        if not filename:
            tree_url = f"https://huggingface.co/api/models/{repo}/tree/{revision}"
            try:
                response = client.get(tree_url, headers=headers)
            except httpx.HTTPError as exc:
                raise ModelDownloadError(
                    ModelDownloadErrorCode.MODEL_DOWNLOAD_SOURCE_UNAVAILABLE,
                    f"Failed to list Hugging Face repository: {exc}",
                    retryable=True,
                    http_status=502,
                ) from exc
            if response.status_code in (401, 403):
                raise ModelDownloadError(
                    ModelDownloadErrorCode.MODEL_DOWNLOAD_SOURCE_UNAVAILABLE,
                    f"Hugging Face auth failed (HTTP {response.status_code})",
                    http_status=response.status_code,
                )
            if response.status_code == 404:
                raise ModelDownloadError(
                    ModelDownloadErrorCode.MODEL_DOWNLOAD_SOURCE_UNAVAILABLE,
                    "Hugging Face repository not found",
                    http_status=404,
                )
            if response.status_code >= 400:
                raise ModelDownloadError(
                    ModelDownloadErrorCode.MODEL_DOWNLOAD_SOURCE_UNAVAILABLE,
                    f"Hugging Face tree listing failed (HTTP {response.status_code})",
                    retryable=response.status_code >= 500 or response.status_code == 429,
                    http_status=response.status_code,
                )
            tree = response.json()
            paths = [
                item["path"]
                for item in tree
                if isinstance(item, dict) and isinstance(item.get("path"), str)
            ]
            gguf = [p for p in paths if p.lower().endswith(".gguf")]
            safetensors = [p for p in paths if p.lower().endswith(".safetensors")]
            if gguf:
                filename = sorted(gguf)[0]
                files_to_fetch = [filename]
            elif safetensors:
                files_to_fetch = list(safetensors)
                for required in (
                    "config.json",
                    "tokenizer.json",
                    "tokenizer_config.json",
                    "vocab.json",
                    "merges.txt",
                    "special_tokens_map.json",
                    "model.safetensors.index.json",
                ):
                    if required in paths and required not in files_to_fetch:
                        files_to_fetch.append(required)
                filename = None
            else:
                raise ModelDownloadError(
                    ModelDownloadErrorCode.MODEL_DOWNLOAD_FAILED,
                    "No .gguf or .safetensors files found in repository",
                    http_status=404,
                )
        else:
            files_to_fetch = [filename]

        sha = hashlib.sha256()
        downloaded = 0
        total: int | None = None
        started = time.monotonic()
        started_iso = utc_now()
        primary_path: Path | None = None
        last_persist = 0.0

        # Probe content-lengths for disk preflight when possible.
        probed_total = 0
        known_all = True
        for rel_path in files_to_fetch:
            clean = rel_path.replace("\\", "/").lstrip("/")
            url = f"https://huggingface.co/{repo}/resolve/{revision}/{clean}"
            try:
                head = client.head(url, headers=headers)
                cl = head.headers.get("content-length")
                if cl and cl.isdigit():
                    probed_total += int(cl)
                else:
                    known_all = False
            except httpx.HTTPError:
                known_all = False
        if known_all and probed_total > 0:
            total = probed_total
            disk_preflight(target_dir=dest_dir, bytes_total=total, bytes_already=0)

        for rel_path in files_to_fetch:
            if cancel_check():
                raise ModelDownloadError(
                    ModelDownloadErrorCode.MODEL_DOWNLOAD_CANCELLED,
                    "Download cancelled",
                    http_status=409,
                )
            clean = rel_path.replace("\\", "/").lstrip("/")
            if ".." in clean.split("/"):
                raise ModelDownloadError(
                    ModelDownloadErrorCode.UNSAFE_PATH,
                    "Unsafe filename",
                    http_status=400,
                )
            final_target = dest_dir / clean
            final_target.parent.mkdir(parents=True, exist_ok=True)
            part_target = Path(str(final_target) + ".part")
            url = f"https://huggingface.co/{repo}/resolve/{revision}/{clean}"

            # Resume: reuse partial .part when present.
            resume_from = part_target.stat().st_size if part_target.is_file() else 0
            req_headers = dict(headers)
            if resume_from > 0:
                req_headers["Range"] = f"bytes={resume_from}-"

            try:
                with client.stream("GET", url, headers=req_headers) as response:
                    if response.status_code == 416:
                        # Already complete per server — treat as done.
                        if part_target.is_file():
                            part_target.replace(final_target)
                        continue
                    if response.status_code in (401, 403):
                        raise ModelDownloadError(
                            ModelDownloadErrorCode.MODEL_DOWNLOAD_SOURCE_UNAVAILABLE,
                            f"Hugging Face auth failed (HTTP {response.status_code})",
                            http_status=response.status_code,
                        )
                    if response.status_code == 404:
                        raise ModelDownloadError(
                            ModelDownloadErrorCode.MODEL_DOWNLOAD_SOURCE_UNAVAILABLE,
                            f"File not found: {clean}",
                            http_status=404,
                        )
                    if response.status_code == 429:
                        raise ModelDownloadError(
                            ModelDownloadErrorCode.MODEL_DOWNLOAD_SOURCE_UNAVAILABLE,
                            "Hugging Face rate limited",
                            retryable=True,
                            http_status=429,
                        )
                    if response.status_code >= 500:
                        raise ModelDownloadError(
                            ModelDownloadErrorCode.MODEL_DOWNLOAD_SOURCE_UNAVAILABLE,
                            f"Hugging Face upstream error (HTTP {response.status_code})",
                            retryable=True,
                            http_status=response.status_code,
                        )
                    if response.status_code not in (200, 206):
                        response.raise_for_status()

                    content_range = response.headers.get("content-range") or ""
                    cl = response.headers.get("content-length")
                    file_total: int | None = None
                    if content_range and "/" in content_range:
                        try:
                            file_total = int(content_range.rsplit("/", 1)[-1])
                        except ValueError:
                            file_total = None
                    elif cl and cl.isdigit():
                        file_total = int(cl) + (resume_from if response.status_code == 206 else 0)
                    if file_total is not None and total is None:
                        # Best-effort remaining estimate across multi-file downloads.
                        total = downloaded + max(0, file_total - resume_from)
                        disk_preflight(
                            target_dir=dest_dir,
                            bytes_total=total,
                            bytes_already=downloaded,
                        )
                        progress(
                            phase="downloading",
                            bytes_downloaded=downloaded,
                            total_bytes=total,
                            current_file=clean,
                            state=DownloadState.DOWNLOADING.value,
                        )

                    mode = "ab" if response.status_code == 206 and resume_from > 0 else "wb"
                    if mode == "wb" and resume_from > 0:
                        # Server ignored Range — restart file.
                        resume_from = 0
                    if mode == "wb":
                        # Hash restarts for this file; keep prior files' contribution via running sha.
                        pass
                    else:
                        # Include already-written bytes in hash for this partial file.
                        with part_target.open("rb") as existing:
                            while True:
                                chunk = existing.read(1024 * 1024)
                                if not chunk:
                                    break
                                sha.update(chunk)
                        downloaded += resume_from

                    with part_target.open(mode) as handle:
                        for chunk in response.iter_bytes(chunk_size=1024 * 1024):
                            if cancel_check():
                                raise ModelDownloadError(
                                    ModelDownloadErrorCode.MODEL_DOWNLOAD_CANCELLED,
                                    "Download cancelled",
                                    http_status=409,
                                )
                            handle.write(chunk)
                            sha.update(chunk)
                            downloaded += len(chunk)
                            now = time.monotonic()
                            elapsed = max(1e-6, now - started)
                            speed = downloaded / elapsed
                            eta = None
                            if total and speed > 0:
                                eta = max(0.0, (total - downloaded) / speed)
                            if now - last_persist >= 0.25:
                                last_persist = now
                                heartbeat()
                                progress(
                                    phase="downloading",
                                    bytes_downloaded=downloaded,
                                    total_bytes=total,
                                    speed_bps=speed,
                                    eta_seconds=eta,
                                    current_file=clean,
                                    state=DownloadState.DOWNLOADING.value,
                                )
            except httpx.TimeoutException as exc:
                raise ModelDownloadError(
                    ModelDownloadErrorCode.MODEL_DOWNLOAD_SOURCE_UNAVAILABLE,
                    f"Download stalled or timed out: {exc}",
                    retryable=True,
                    http_status=504,
                ) from exc
            except httpx.HTTPError as exc:
                raise ModelDownloadError(
                    ModelDownloadErrorCode.MODEL_DOWNLOAD_SOURCE_UNAVAILABLE,
                    f"Download connection error: {exc}",
                    retryable=True,
                    http_status=502,
                ) from exc

            # Atomic finalize for this file.
            if not part_target.is_file():
                raise ModelDownloadError(
                    ModelDownloadErrorCode.MODEL_DOWNLOAD_FAILED,
                    f"Partial file missing after download: {clean}",
                    http_status=500,
                )
            os.replace(part_target, final_target)
            if primary_path is None:
                primary_path = final_target
            if clean.lower().endswith((".gguf", ".safetensors")) and (
                primary_path is None or primary_path.suffix.lower() == ".json"
            ):
                primary_path = final_target

        if primary_path is None:
            raise ModelDownloadError(
                ModelDownloadErrorCode.MODEL_DOWNLOAD_FAILED,
                "Download produced no model files",
                http_status=500,
            )

        progress(
            phase="verifying",
            bytes_downloaded=downloaded,
            total_bytes=total or downloaded,
            state=DownloadState.VERIFYING.value,
        )
        heartbeat()
        checksum = sha.hexdigest()
        if downloaded <= 0:
            raise ModelDownloadError(
                ModelDownloadErrorCode.MODEL_DOWNLOAD_VERIFICATION_FAILED,
                "Downloaded zero bytes",
                http_status=500,
            )

        is_multi = len(files_to_fetch) > 1
        local_path = str(dest_dir if is_multi else primary_path)
        fmt = None
        if primary_path.suffix.lower() == ".gguf":
            fmt = "gguf"
        elif any(p.lower().endswith(".safetensors") for p in files_to_fetch):
            fmt = "safetensors"

        display = Path(repo).name
        model_id = f"imported:{display}"
        descriptor = ModelDescriptor(
            id=model_id,
            display_name=display,
            provider_id="local_import",
            runtime_id="file",
            source=ModelSource.DOWNLOADED,
            format=fmt,
            disk_size_bytes=downloaded,
            local_path=local_path,
            capabilities=ModelCapabilities(chat=CapabilityState.UNKNOWN),
            lifecycle_state=ModelLifecycleState.AVAILABLE,
            health=ModelHealthState.UNKNOWN,
            metadata={
                "sha256": checksum,
                "repositoryId": repo,
                "revision": revision,
                "downloadedAt": started_iso,
                "files": files_to_fetch,
                "snapshotComplete": is_multi or fmt == "gguf",
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
        self.store.append_audit(
            "model_downloaded",
            detail={"downloadId": download_id, "modelId": model_id, "sha256": checksum},
        )
        elapsed = max(1e-6, time.monotonic() - started)
        progress(
            phase="completed",
            bytes_downloaded=downloaded,
            total_bytes=total or downloaded,
            speed_bps=downloaded / elapsed,
            eta_seconds=0.0,
            state=DownloadState.COMPLETED.value,
            model_id=model_id,
        )
        return {
            "status": "succeeded",
            "model_id": model_id,
            "sha256": checksum,
            "bytes_downloaded": downloaded,
            "total_bytes": total or downloaded,
            "local_path": local_path,
            "files": files_to_fetch,
        }

    def _run_ollama(
        self,
        args: dict[str, Any],
        *,
        cancel_check: CancelCheck,
        progress: Callable[..., None],
        heartbeat: Callable[[], None],
    ) -> dict[str, Any]:
        """Orchestrate an Ollama pull via local HTTP — still worker-owned."""
        repository_id = str(args.get("repository_id") or "").strip()
        revision = args.get("revision")
        endpoint = str(args.get("endpoint") or os.environ.get("LEVIATHAN_OLLAMA_ENDPOINT") or "http://127.0.0.1:11434")
        if not repository_id:
            raise ModelDownloadError(
                ModelDownloadErrorCode.VALIDATION_ERROR,
                "Ollama pull requires repository_id",
                http_status=422,
            )
        if cancel_check():
            raise ModelDownloadError(
                ModelDownloadErrorCode.MODEL_DOWNLOAD_CANCELLED,
                "Download cancelled",
                http_status=409,
            )
        progress(phase="pulling", state=DownloadState.DOWNLOADING.value)
        heartbeat()
        model_name = repository_id if not revision else f"{repository_id}:{revision}"
        client = self._http()
        try:
            with client.stream(
                "POST",
                f"{endpoint.rstrip('/')}/api/pull",
                json={"name": model_name, "stream": True},
                timeout=httpx.Timeout(
                    connect=self.connect_timeout,
                    read=None,  # long pull; stall handled by inactivity via cancel/heartbeat
                    write=self.stall_timeout,
                    pool=self.connect_timeout,
                ),
            ) as response:
                if response.status_code >= 400:
                    raise ModelDownloadError(
                        ModelDownloadErrorCode.MODEL_DOWNLOAD_SOURCE_UNAVAILABLE,
                        f"Ollama pull failed (HTTP {response.status_code})",
                        http_status=response.status_code,
                        retryable=response.status_code >= 500,
                    )
                last = time.monotonic()
                for line in response.iter_lines():
                    if cancel_check():
                        raise ModelDownloadError(
                            ModelDownloadErrorCode.MODEL_DOWNLOAD_CANCELLED,
                            "Download cancelled",
                            http_status=409,
                        )
                    now = time.monotonic()
                    if now - last >= 1.0:
                        last = now
                        heartbeat()
                        progress(
                            phase="pulling",
                            state=DownloadState.DOWNLOADING.value,
                            message=line[:200] if line else "pulling",
                        )
        except httpx.HTTPError as exc:
            raise ModelDownloadError(
                ModelDownloadErrorCode.MODEL_DOWNLOAD_SOURCE_UNAVAILABLE,
                f"Ollama pull connection error: {exc}",
                retryable=True,
                http_status=502,
            ) from exc

        progress(phase="completed", state=DownloadState.COMPLETED.value)
        return {"status": "succeeded", "repository_id": repository_id, "source": "ollama"}

    def _safe_dest(self, repo: str, revision: str) -> Path:
        safe_repo = repo.replace("/", "__")
        safe_rev = re.sub(r"[^A-Za-z0-9._-]", "_", revision)
        return self._ensure_under_root(self.download_root / safe_repo / safe_rev)
