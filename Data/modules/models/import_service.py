"""Safe local model import."""

from __future__ import annotations

import os
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
from Data.modules.models.errors import MODEL_INVALID, UNSAFE_PATH, VALIDATION_ERROR, ModelControlError
from Data.modules.models.registry import ModelRegistry
from Data.modules.models.store import ModelStore, utc_now


SUPPORTED_EXTENSIONS = {".gguf", ".safetensors"}


class ImportService:
    def __init__(
        self,
        store: ModelStore,
        registry: ModelRegistry,
        *,
        allowed_roots: list[Path],
    ) -> None:
        self.store = store
        self.registry = registry
        self.allowed_roots = [root.resolve() for root in allowed_roots]

    def import_local_path(self, raw_path: str, *, display_name: str | None = None) -> ModelDescriptor:
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
        try:
            resolved = path.resolve(strict=True)
        except FileNotFoundError as exc:
            raise ModelControlError(
                code=MODEL_INVALID,
                message=f"Path does not exist: {raw_path}",
                http_status=404,
            ) from exc

        if resolved.is_symlink():
            # resolve(strict=True) already followed; still reject if original was sneaky device
            pass
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
        # Reject device files / odd modes
        mode = resolved.stat().st_mode
        if not os.path.isfile(resolved) or os.path.islink(path):
            # If the provided path was a symlink escaping after resolve check already handled;
            # still refuse non-regular.
            pass
        if not (mode & 0o170000 == 0o100000):  # S_IFREG
            raise ModelControlError(
                code=UNSAFE_PATH,
                message="Refusing to import non-regular file",
                http_status=400,
            )

        suffix = resolved.suffix.lower()
        if suffix not in SUPPORTED_EXTENSIONS:
            raise ModelControlError(
                code=MODEL_INVALID,
                message=f"Unsupported format {suffix}; supported: {sorted(SUPPORTED_EXTENSIONS)}",
                http_status=400,
            )

        model_id = f"imported:{resolved.name}"
        descriptor = ModelDescriptor(
            id=model_id,
            display_name=display_name or resolved.name,
            provider_id="local_import",
            runtime_id="file",
            source=ModelSource.IMPORTED,
            format=suffix.lstrip("."),
            disk_size_bytes=resolved.stat().st_size,
            local_path=str(resolved),
            capabilities=ModelCapabilities(chat=CapabilityState.UNKNOWN),
            lifecycle_state=ModelLifecycleState.AVAILABLE,
            health=ModelHealthState.UNKNOWN,
            last_discovered_at=utc_now(),
            metadata={"importedFrom": str(resolved)},
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
            detail={"modelId": model_id, "path": str(resolved)},
        )
        return self.registry.get(model_id)

    def _is_under_allowed_roots(self, path: Path) -> bool:
        for root in self.allowed_roots:
            try:
                path.relative_to(root)
                return True
            except ValueError:
                continue
        return False
