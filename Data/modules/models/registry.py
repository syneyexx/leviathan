"""Model registry — single source of truth for known models."""

from __future__ import annotations

import json
import threading
from typing import Any

from Data.modules.models.contracts import (
    ModelCapabilities,
    ModelDescriptor,
    ModelHealthState,
    ModelLifecycleState,
    ModelSource,
)
from Data.modules.models.errors import MODEL_NOT_FOUND, ModelControlError
from Data.modules.models.store import ModelStore, utc_now


class ModelRegistry:
    def __init__(self, store: ModelStore) -> None:
        self.store = store
        self._lock = threading.RLock()
        self._last_discovery_latency_ms: float | None = None
        self._last_refresh_at: str | None = None
        self._last_refresh_error: str | None = None

    @property
    def last_discovery_latency_ms(self) -> float | None:
        return self._last_discovery_latency_ms

    @property
    def last_refresh_at(self) -> str | None:
        return self._last_refresh_at

    @property
    def last_refresh_error(self) -> str | None:
        return self._last_refresh_error

    def record_discovery_latency(self, latency_ms: float | None) -> None:
        self._last_discovery_latency_ms = latency_ms

    def list_descriptors(self) -> list[ModelDescriptor]:
        with self._lock:
            return [self._row_to_descriptor(row) for row in self.store.list_models()]

    def get(self, model_id: str) -> ModelDescriptor:
        row = self.store.get_model(model_id)
        if not row:
            # Allow lookup by display name / provider model id
            for candidate in self.store.list_models():
                meta = json.loads(candidate.get("metadata_json") or "{}")
                if candidate["display_name"] == model_id or meta.get("provider_model_id") == model_id:
                    return self._row_to_descriptor(candidate)
            raise ModelControlError(
                code=MODEL_NOT_FOUND,
                message=f"Model not found: {model_id}",
                model_id=model_id,
                http_status=404,
            )
        return self._row_to_descriptor(row)

    def upsert_discovered(self, models: list[ModelDescriptor], *, provider_id: str) -> None:
        with self._lock:
            active_id = self.store.get_active_model_id()
            seen_ids = {m.id for m in models}
            for model in models:
                model.active = model.id == active_id
                if model.active and model.lifecycle_state == ModelLifecycleState.LOADED:
                    model.lifecycle_state = ModelLifecycleState.ACTIVE
                self.store.upsert_model(self._descriptor_to_row(model))
            # Models previously known for this provider but missing now → offline
            for row in self.store.list_models():
                if row["provider_id"] != provider_id:
                    continue
                if row["model_id"] not in seen_ids:
                    self.store.upsert_model(
                        {
                            **dict(row),
                            "lifecycle_state": ModelLifecycleState.OFFLINE.value,
                            "health": ModelHealthState.OFFLINE.value,
                            "loaded": 0,
                            "active": 1 if row["model_id"] == active_id else 0,
                            "capabilities": json.loads(row.get("capabilities_json") or "{}"),
                            "tags": json.loads(row.get("tags_json") or "[]"),
                            "metadata": json.loads(row.get("metadata_json") or "{}"),
                        }
                    )
            self._last_refresh_at = utc_now()
            self._last_refresh_error = None

    def mark_refresh_error(self, error: str) -> None:
        self._last_refresh_error = error
        self._last_refresh_at = utc_now()

    def set_lifecycle(
        self,
        model_id: str,
        state: ModelLifecycleState,
        *,
        health: ModelHealthState | None = None,
        loaded: bool | None = None,
        error: str | None = None,
    ) -> ModelDescriptor:
        model = self.get(model_id)
        row = self._descriptor_to_row(model)
        row["lifecycle_state"] = state.value
        if health is not None:
            row["health"] = health.value
        if loaded is not None:
            row["loaded"] = loaded
        if error is not None:
            meta = dict(row.get("metadata") or {})
            meta["lastError"] = error
            row["metadata"] = meta
        self.store.upsert_model(row)
        return self.get(model_id)

    def activate(self, model_id: str) -> ModelDescriptor:
        model = self.get(model_id)
        self.store.set_active_model(model_id)
        self.store.append_audit("model_activated", detail={"modelId": model_id})
        # Reflect active flag
        for row in self.store.list_models():
            descriptor = self._row_to_descriptor(row)
            descriptor.active = descriptor.id == model_id
            if descriptor.active and descriptor.lifecycle_state in {
                ModelLifecycleState.LOADED,
                ModelLifecycleState.AVAILABLE,
                ModelLifecycleState.ACTIVE,
            }:
                descriptor.lifecycle_state = ModelLifecycleState.ACTIVE
            self.store.upsert_model(self._descriptor_to_row(descriptor))
        return self.get(model_id)

    def touch_used(self, model_id: str) -> None:
        try:
            model = self.get(model_id)
        except ModelControlError:
            return
        row = self._descriptor_to_row(model)
        row["last_used_at"] = utc_now()
        self.store.upsert_model(row)

    def remove_registry_entry(self, model_id: str) -> None:
        if not self.store.delete_model(model_id):
            raise ModelControlError(
                code=MODEL_NOT_FOUND,
                message=f"Model not found: {model_id}",
                model_id=model_id,
                http_status=404,
            )
        active = self.store.get_active_model_id()
        if active == model_id:
            self.store.set_active_model(None)
        self.store.append_audit("model_removed", detail={"modelId": model_id})

    def _descriptor_to_row(self, model: ModelDescriptor) -> dict[str, Any]:
        return {
            "model_id": model.id,
            "display_name": model.display_name,
            "provider_id": model.provider_id,
            "runtime_id": model.runtime_id,
            "source": model.source.value,
            "object_type": model.object_type,
            "architecture": model.architecture,
            "family": model.family,
            "parameter_count": model.parameter_count,
            "quantization": model.quantization,
            "format": model.format,
            "disk_size_bytes": model.disk_size_bytes,
            "context_window": model.context_window,
            "max_output_tokens": model.max_output_tokens,
            "capabilities": model.capabilities.public_dict(),
            "lifecycle_state": model.lifecycle_state.value,
            "health": model.health.value,
            "active": model.active,
            "loaded": model.loaded,
            "local_path": model.local_path,
            "endpoint": model.endpoint,
            "last_discovered_at": model.last_discovered_at,
            "last_used_at": model.last_used_at,
            "tags": list(model.tags),
            "metadata": dict(model.metadata),
        }

    def _row_to_descriptor(self, row: dict[str, Any]) -> ModelDescriptor:
        caps_raw = row.get("capabilities_json") or row.get("capabilities") or {}
        if isinstance(caps_raw, str):
            try:
                caps_raw = json.loads(caps_raw)
            except json.JSONDecodeError:
                caps_raw = {}
        tags_raw = row.get("tags_json") or row.get("tags") or []
        if isinstance(tags_raw, str):
            try:
                tags_raw = json.loads(tags_raw)
            except json.JSONDecodeError:
                tags_raw = []
        meta_raw = row.get("metadata_json") or row.get("metadata") or {}
        if isinstance(meta_raw, str):
            try:
                meta_raw = json.loads(meta_raw)
            except json.JSONDecodeError:
                meta_raw = {}
        loaded_raw = row.get("loaded")
        loaded: bool | None
        if loaded_raw is None:
            loaded = None
        else:
            loaded = bool(loaded_raw)
        return ModelDescriptor(
            id=row["model_id"],
            display_name=row["display_name"],
            provider_id=row["provider_id"],
            runtime_id=row.get("runtime_id"),
            source=ModelSource(row.get("source") or "remote"),
            object_type=row.get("object_type"),
            architecture=row.get("architecture"),
            family=row.get("family"),
            parameter_count=row.get("parameter_count"),
            quantization=row.get("quantization"),
            format=row.get("format"),
            disk_size_bytes=row.get("disk_size_bytes"),
            context_window=row.get("context_window"),
            max_output_tokens=row.get("max_output_tokens"),
            capabilities=ModelCapabilities.from_dict(caps_raw if isinstance(caps_raw, dict) else {}),
            lifecycle_state=ModelLifecycleState(row.get("lifecycle_state") or "unknown"),
            health=ModelHealthState(row.get("health") or "unknown"),
            active=bool(row.get("active")),
            loaded=loaded,
            local_path=row.get("local_path"),
            endpoint=row.get("endpoint"),
            last_discovered_at=row.get("last_discovered_at"),
            last_used_at=row.get("last_used_at"),
            tags=tuple(tags_raw) if isinstance(tags_raw, list) else (),
            metadata=meta_raw if isinstance(meta_raw, dict) else {},
        )
