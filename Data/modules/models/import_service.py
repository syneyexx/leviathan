"""Safe local model import — path confinement + streaming verification.

Heavy import (hashing / format inspection) executes in the ``model_download``
worker when externalization is on. Control Plane may only perform lightweight
path syntax validation and enqueue.
"""

from __future__ import annotations

import hashlib
import os
import struct
import uuid
from pathlib import Path
from typing import Any

from Data.modules.models.contracts import (
    CapabilityState,
    ModelCapabilities,
    ModelDescriptor,
    ModelHealthState,
    ModelLifecycleState,
    ModelSource,
)
from Data.modules.models.errors import (
    MODEL_INVALID,
    UNSAFE_PATH,
    VALIDATION_ERROR,
    ModelControlError,
)
from Data.modules.models.registry import ModelRegistry
from Data.modules.models.store import ModelStore, utc_now


SUPPORTED_EXTENSIONS = {".gguf", ".safetensors"}
# Chunk size for streaming fingerprint — never load whole model into RAM.
_HASH_CHUNK = 1024 * 1024
# GGUF magic + version + tensor/kv counts (bounded header probe).
_GGUF_HEADER_BYTES = 24
# Safetensors: 8-byte little-endian header length + bounded JSON header.
_SAFETENSORS_MAX_HEADER = 64 * 1024 * 1024


class ImportService:
    def __init__(
        self,
        store: ModelStore,
        registry: ModelRegistry,
        *,
        allowed_roots: list[Path],
        job_runtime: Any | None = None,
    ) -> None:
        self.store = store
        self.registry = registry
        self.allowed_roots = [root.resolve() for root in allowed_roots]
        self.job_runtime = job_runtime

    def bind_job_runtime(self, job_runtime: Any | None) -> None:
        self.job_runtime = job_runtime

    def validate_import_path(self, raw_path: str) -> Path:
        """Lightweight path/syntax validation suitable for Control Plane."""
        if not raw_path or not isinstance(raw_path, str):
            raise ModelControlError(
                code=VALIDATION_ERROR,
                message="path is required",
                http_status=422,
            )
        path = Path(raw_path).expanduser()
        if not path.is_absolute():
            raise ModelControlError(
                code=UNSAFE_PATH,
                message="Import path must be absolute",
                http_status=400,
            )
        # Reject obvious traversal tokens before resolve.
        if ".." in path.parts:
            raise ModelControlError(
                code=UNSAFE_PATH,
                message="Import path must not contain '..' segments",
                http_status=400,
            )
        try:
            resolved = path.resolve(strict=True)
        except FileNotFoundError as exc:
            raise ModelControlError(
                code=MODEL_INVALID,
                message=f"Path does not exist: {raw_path}",
                http_status=404,
            ) from exc

        if not resolved.is_file():
            raise ModelControlError(
                code=MODEL_INVALID,
                message="Import path must be a regular file",
                http_status=400,
            )
        if not self._is_under_allowed_roots(resolved):
            raise ModelControlError(
                code=UNSAFE_PATH,
                message="Import path is outside allowed roots",
                http_status=400,
                details={"allowedRoots": [str(r) for r in self.allowed_roots]},
            )
        mode = resolved.stat().st_mode
        if not (mode & 0o170000 == 0o100000):  # S_IFREG
            raise ModelControlError(
                code=UNSAFE_PATH,
                message="Refusing to import non-regular file",
                http_status=400,
            )
        if os.path.islink(path) and not self._is_under_allowed_roots(resolved):
            raise ModelControlError(
                code=UNSAFE_PATH,
                message="Refusing symlink that escapes allowed roots",
                http_status=400,
            )
        suffix = resolved.suffix.lower()
        if suffix not in SUPPORTED_EXTENSIONS:
            raise ModelControlError(
                code=MODEL_INVALID,
                message=f"Unsupported format {suffix}; supported: {sorted(SUPPORTED_EXTENSIONS)}",
                http_status=400,
            )
        return resolved

    def import_local_path(
        self,
        raw_path: str,
        *,
        display_name: str | None = None,
        measure_hash: bool = True,
    ) -> ModelDescriptor:
        """Execute local import (worker path or non-externalized Control Plane)."""
        resolved = self.validate_import_path(raw_path)
        return self._register_verified(
            resolved,
            display_name=display_name,
            measure_hash=measure_hash,
        )

    def enqueue_local_import(
        self,
        raw_path: str,
        *,
        display_name: str | None = None,
        requested_by: str = "api",
    ) -> dict[str, Any]:
        """Validate lightly and enqueue ``model_import.local`` to model_download."""
        from Data.modules.execution.workload import externalize_api_enabled
        from Data.modules.model_download.errors import ModelDownloadError, ModelDownloadErrorCode
        from Data.modules.model_download.facade import ModelDownloadClient
        from Data.modules.model_download.readiness import model_download_workers_ready

        # Always validate path syntax / confinement on Control Plane.
        resolved = self.validate_import_path(raw_path)

        if not externalize_api_enabled():
            model = self._register_verified(resolved, display_name=display_name)
            return {"model": model.public_dict(), "executed_via": "inline_dev"}

        if self.job_runtime is None:
            raise ModelControlError(
                code=ModelDownloadErrorCode.MODEL_DOWNLOAD_EXECUTION_UNAVAILABLE.value,
                message=(
                    "Model import execution unavailable: job runtime not bound. "
                    "Control Plane does not perform heavy local model imports."
                ),
                http_status=503,
                retryable=True,
            )
        db_path = getattr(getattr(self.job_runtime, "store", None), "path", None)
        if not model_download_workers_ready(db_path):
            raise ModelControlError(
                code=ModelDownloadErrorCode.MODEL_DOWNLOAD_EXECUTION_UNAVAILABLE.value,
                message=(
                    "Model download workers unavailable; refusing Control Plane "
                    "heavy local model import."
                ),
                http_status=503,
                retryable=True,
            )

        import_id = str(uuid.uuid4())
        client = ModelDownloadClient(self.job_runtime)
        try:
            fabric_job = client.submit_local_import(
                import_id=import_id,
                path=str(resolved),
                display_name=display_name,
                allowed_roots=[str(r) for r in self.allowed_roots],
                requested_by=requested_by,
            )
        except ModelDownloadError as exc:
            raise ModelControlError(
                code=exc.code.value,
                message=exc.message,
                http_status=exc.http_status,
                retryable=exc.retryable,
                details=dict(exc.details),
            ) from exc
        return {
            "importId": import_id,
            "jobId": fabric_job.job_id,
            "path": str(resolved),
            "state": "queued",
            "executed_via": "model_download",
        }

    def _register_verified(
        self,
        resolved: Path,
        *,
        display_name: str | None = None,
        measure_hash: bool = True,
        cancel_check: Any | None = None,
    ) -> ModelDescriptor:
        before = resolved.stat()
        fingerprint = self.fingerprint_file(
            resolved,
            measure_hash=measure_hash,
            cancel_check=cancel_check,
        )
        after = resolved.stat()
        if before.st_size != after.st_size or before.st_mtime_ns != after.st_mtime_ns:
            raise ModelControlError(
                code="MODEL_CHANGED_DURING_IMPORT",
                message="Model file changed during import verification",
                http_status=409,
                details={
                    "path": str(resolved),
                    "sizeBefore": before.st_size,
                    "sizeAfter": after.st_size,
                },
            )

        validation = self.validate_format_header(resolved, fingerprint["format"])
        model_id = f"imported:{resolved.name}"
        # Idempotent: same path + hash reuses the row rather than uncontrolled duplicates.
        existing = None
        try:
            existing = self.registry.get(model_id)
        except Exception:  # noqa: BLE001
            existing = None
        meta = {
            "importedFrom": str(resolved),
            "sha256": fingerprint.get("sha256"),
            "hashStatus": fingerprint.get("hash_status"),
            "mtimeNs": after.st_mtime_ns,
            "validation": validation,
            "importManifest": {
                "originalPath": str(resolved),
                "resolvedPath": str(resolved),
                "size": after.st_size,
                "mtime": after.st_mtime,
                "hash": fingerprint.get("sha256"),
                "hashStatus": fingerprint.get("hash_status"),
                "format": fingerprint["format"],
                "validationLevel": validation.get("level"),
                "importedAt": utc_now(),
            },
        }
        if existing is not None and existing.metadata.get("sha256") == fingerprint.get("sha256"):
            return existing

        descriptor = ModelDescriptor(
            id=model_id,
            display_name=display_name or resolved.name,
            provider_id="local_import",
            runtime_id="file",
            source=ModelSource.IMPORTED,
            format=fingerprint["format"],
            disk_size_bytes=after.st_size,
            local_path=str(resolved),
            capabilities=ModelCapabilities(chat=CapabilityState.UNKNOWN),
            lifecycle_state=ModelLifecycleState.AVAILABLE,
            health=ModelHealthState.UNKNOWN,
            last_discovered_at=utc_now(),
            metadata=meta,
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
                "last_discovered_at": descriptor.last_discovered_at,
            }
        )
        self.store.append_audit(
            "model_imported",
            detail={
                "modelId": model_id,
                "path": str(resolved),
                "sha256": fingerprint.get("sha256"),
                "hashStatus": fingerprint.get("hash_status"),
            },
        )
        return self.registry.get(model_id)

    @staticmethod
    def fingerprint_file(
        path: Path,
        *,
        measure_hash: bool = True,
        cancel_check: Any | None = None,
        chunk_size: int = _HASH_CHUNK,
    ) -> dict[str, Any]:
        """Streaming SHA-256 — never ``path.read_bytes()`` on whole model."""
        suffix = path.suffix.lower().lstrip(".")
        if not measure_hash:
            return {
                "format": suffix,
                "sha256": None,
                "hash_status": "UNMEASURED",
                "size": path.stat().st_size,
            }
        digest = hashlib.sha256()
        total = 0
        with path.open("rb") as handle:
            while True:
                if cancel_check is not None and cancel_check():
                    from Data.modules.model_download.errors import (
                        ModelDownloadError,
                        ModelDownloadErrorCode,
                    )

                    raise ModelDownloadError(
                        ModelDownloadErrorCode.MODEL_DOWNLOAD_CANCELLED,
                        "Local model import cancelled during fingerprint",
                        http_status=409,
                    )
                chunk = handle.read(chunk_size)
                if not chunk:
                    break
                digest.update(chunk)
                total += len(chunk)
        return {
            "format": suffix,
            "sha256": digest.hexdigest(),
            "hash_status": "MEASURED",
            "size": total,
        }

    @staticmethod
    def validate_format_header(path: Path, fmt: str) -> dict[str, Any]:
        """Bounded structural validation — does not load tensors."""
        fmt_l = (fmt or "").lower().lstrip(".")
        if fmt_l == "gguf":
            with path.open("rb") as handle:
                header = handle.read(_GGUF_HEADER_BYTES)
            if len(header) < 8 or header[:4] != b"GGUF":
                raise ModelControlError(
                    code=MODEL_INVALID,
                    message="Invalid GGUF magic/header",
                    http_status=400,
                )
            version = struct.unpack_from("<I", header, 4)[0] if len(header) >= 8 else 0
            return {"level": "header", "format": "gguf", "version": version, "ok": True}
        if fmt_l == "safetensors":
            with path.open("rb") as handle:
                size_bytes = handle.read(8)
                if len(size_bytes) < 8:
                    raise ModelControlError(
                        code=MODEL_INVALID,
                        message="Invalid safetensors header",
                        http_status=400,
                    )
                header_len = struct.unpack("<Q", size_bytes)[0]
                if header_len <= 0 or header_len > _SAFETENSORS_MAX_HEADER:
                    raise ModelControlError(
                        code=MODEL_INVALID,
                        message="Safetensors header length out of bounds",
                        http_status=400,
                    )
                file_size = path.stat().st_size
                if 8 + header_len > file_size:
                    raise ModelControlError(
                        code=MODEL_INVALID,
                        message="Safetensors header exceeds file size",
                        http_status=400,
                    )
                # Read header JSON for sanity only — bounded.
                raw_header = handle.read(min(header_len, 1024 * 1024))
            if not raw_header:
                raise ModelControlError(
                    code=MODEL_INVALID,
                    message="Empty safetensors header",
                    http_status=400,
                )
            return {
                "level": "header",
                "format": "safetensors",
                "headerBytes": header_len,
                "ok": True,
            }
        return {"level": "extension", "format": fmt_l, "ok": True}

    def _is_under_allowed_roots(self, path: Path) -> bool:
        for root in self.allowed_roots:
            try:
                path.relative_to(root)
                return True
            except ValueError:
                continue
        return False
