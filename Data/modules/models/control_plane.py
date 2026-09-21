"""Model Control Plane facade — public entry for API / chat integration."""

from __future__ import annotations

import json
import time
import uuid
from pathlib import Path
from typing import Any

from Data.backend.config import Settings
from Data.modules.models.benchmarks import BenchmarkService
from Data.modules.models.capability_probe import CapabilityProbeService
from Data.modules.models.contracts import (
    LoadOptions,
    ModelRequest,
    ProviderHealth,
    ProviderRecord,
    RuntimeCapabilities,
)
from Data.modules.models.downloads import DownloadManager
from Data.modules.models.errors import (
    PROVIDER_NOT_FOUND,
    VALIDATION_ERROR,
    ModelControlError,
)
from Data.modules.models.gateway import ModelGateway
from Data.modules.models.import_service import ImportService
from Data.modules.models.profiles import ProfileService
from Data.modules.models.providers import build_adapter
from Data.modules.models.providers.openai_compatible import normalize_openai_base
from Data.modules.models.registry import ModelRegistry
from Data.modules.models.resource_manager import ResourceManager
from Data.modules.models.router import ModelRouter
from Data.modules.models.runtime_manager import RuntimeManager
from Data.modules.models.store import ModelStore, utc_now
from Data.modules.observability import ObservabilityHub


class ModelControlPlane:
    """Owns providers, registry, routing, gateway, lifecycle, acquisition."""

    def __init__(
        self,
        settings: Settings,
        *,
        observability: ObservabilityHub | None = None,
    ) -> None:
        self.settings = settings
        self.observability = observability
        self.store = ModelStore(settings.database_path)
        self.registry = ModelRegistry(self.store)
        self.profiles = ProfileService(self.store)
        self.gateway = ModelGateway(global_limit=settings.resources.max_model_concurrency)
        self.resources = ResourceManager()
        self.router = ModelRouter(
            self.store,
            self.gateway,
            get_models=self.registry.list_descriptors,
        )
        self.runtime = RuntimeManager(
            self.registry,
            self.resources,
            get_adapter=self.get_adapter,
        )
        self.probes = CapabilityProbeService(
            self.store,
            self.registry,
            get_adapter=self.get_adapter,
        )
        self.benchmarks = BenchmarkService(self.registry, get_adapter=self.get_adapter)
        download_root = settings.database_path.parent / "model_downloads"
        allowed_roots = [
            download_root,
            settings.knowledge.data_root,
            settings.artifacts.root,
            Path.home(),
        ]
        # On Windows-style data roots that don't exist on POSIX, still keep download_root.
        self.imports = ImportService(self.store, self.registry, allowed_roots=allowed_roots)
        self.downloads = DownloadManager(
            self.store,
            self.registry,
            download_root=download_root,
            allow_outbound=settings.network.allow_outbound,
            get_adapter=self.get_adapter,
        )
        self._adapters: dict[str, Any] = {}

    def bootstrap(self) -> None:
        """Ensure default LM Studio provider exists from settings; do not erase config."""
        existing = self.store.list_providers()
        if not existing:
            self.store.upsert_provider(
                {
                    "provider_id": "lm_studio",
                    "name": "LM Studio",
                    "provider_type": "lm_studio",
                    "endpoint": self.settings.llm_base_url,
                    "enabled": True,
                    "api_key_ciphertext": self.settings.llm_api_key
                    if self.settings.llm_api_key and self.settings.llm_api_key != "not-needed"
                    else None,
                    "auto_connect": True,
                    "timeout_seconds": self.settings.llm_timeout_seconds,
                    "refresh_interval_seconds": 60.0,
                    "health": ProviderHealth.UNKNOWN.value,
                    "capabilities": LMStudioCaps().public_dict(),
                    "metadata": {"seededFrom": "settings"},
                }
            )
            self.store.append_audit("provider_seeded", detail={"providerId": "lm_studio"})
        # Seed active model from settings if configured and nothing active yet
        if self.settings.llm_model and not self.store.get_active_model_id():
            # Will reconcile after discovery; store preference in control state
            self.store.set_active_model(None)
            self.store.save_router_config(
                {
                    **self.store.get_router_config(),
                    "preferred_settings_model": self.settings.llm_model,
                }
            )

    async def reconcile_startup(self) -> dict[str, Any]:
        self.bootstrap()
        self._emit("model.discovery.started", {})
        summary = await self.refresh_all()
        # Never trust persisted loaded=true blindly — rediscovery already reconciled.
        active = self.store.get_active_model_id()
        if active:
            try:
                self.registry.get(active)
            except ModelControlError:
                self.store.set_active_model(None)
                active = None
        # If settings pin a model name, try to activate matching discovered model once.
        router_raw = self.store.get_router_config()
        preferred = router_raw.get("preferred_settings_model")
        if preferred and not active:
            for model in self.registry.list_descriptors():
                if (
                    model.display_name == preferred
                    or model.metadata.get("provider_model_id") == preferred
                    or model.id.endswith(f":{preferred}")
                ):
                    self.registry.activate(model.id)
                    active = model.id
                    break
        self._emit("model.discovery.completed", {"summary": summary, "activeModelId": active})
        return {"summary": summary, "activeModelId": active}

    def get_adapter(self, provider_id: str) -> Any:
        if provider_id in self._adapters:
            return self._adapters[provider_id]
        row = self.store.get_provider(provider_id)
        if not row:
            # Synthetic local_import has no remote adapter
            if provider_id == "local_import":
                from Data.modules.models.providers.llama_cpp import LlamaCppAdapter

                adapter = LlamaCppAdapter(provider_id=provider_id, managed=False)
                self._adapters[provider_id] = adapter
                return adapter
            raise ModelControlError(
                code=PROVIDER_NOT_FOUND,
                message=f"Provider not found: {provider_id}",
                provider_id=provider_id,
                http_status=404,
            )
        api_key = row.get("api_key_ciphertext")
        meta = json.loads(row.get("metadata_json") or "{}")
        adapter = build_adapter(
            provider_id=provider_id,
            provider_type=row["provider_type"],
            endpoint=row["endpoint"],
            api_key=api_key,
            timeout_seconds=float(row.get("timeout_seconds") or 30.0),
            metadata=meta if isinstance(meta, dict) else {},
        )
        self._adapters[provider_id] = adapter
        return adapter

    def invalidate_adapter(self, provider_id: str) -> None:
        self._adapters.pop(provider_id, None)

    def list_providers(self) -> list[ProviderRecord]:
        return [self._row_to_provider(row) for row in self.store.list_providers()]

    def get_provider(self, provider_id: str) -> ProviderRecord:
        row = self.store.get_provider(provider_id)
        if not row:
            raise ModelControlError(
                code=PROVIDER_NOT_FOUND,
                message=f"Provider not found: {provider_id}",
                provider_id=provider_id,
                http_status=404,
            )
        return self._row_to_provider(row)

    def create_provider(self, payload: dict[str, Any]) -> ProviderRecord:
        provider_type = str(payload.get("type") or payload.get("provider_type") or "").strip()
        name = str(payload.get("name") or "").strip()
        endpoint = str(payload.get("endpoint") or "").strip()
        if not provider_type or not name or not endpoint:
            raise ModelControlError(
                code=VALIDATION_ERROR,
                message="type, name, and endpoint are required",
                http_status=422,
            )
        provider_id = str(payload.get("id") or payload.get("provider_id") or uuid.uuid4())
        # Validate endpoint early for openai-like types
        if provider_type.lower() in {"lm_studio", "lmstudio", "openai_compatible", "openai"}:
            endpoint = normalize_openai_base(endpoint)
        api_key = payload.get("apiKey") or payload.get("api_key")
        self.store.upsert_provider(
            {
                "provider_id": provider_id,
                "name": name,
                "provider_type": provider_type,
                "endpoint": endpoint,
                "enabled": bool(payload.get("enabled", True)),
                "api_key_ciphertext": api_key if api_key else None,
                "auto_connect": bool(payload.get("autoConnect", payload.get("auto_connect", True))),
                "timeout_seconds": float(payload.get("timeoutSeconds", payload.get("timeout_seconds", 30))),
                "refresh_interval_seconds": float(
                    payload.get("refreshIntervalSeconds", payload.get("refresh_interval_seconds", 60))
                ),
                "health": ProviderHealth.UNKNOWN.value,
                "capabilities": {},
                "metadata": payload.get("metadata") or {},
            }
        )
        self.store.append_audit("provider_created", detail={"providerId": provider_id, "type": provider_type})
        self.invalidate_adapter(provider_id)
        return self.get_provider(provider_id)

    def update_provider(self, provider_id: str, payload: dict[str, Any]) -> ProviderRecord:
        self.get_provider(provider_id)
        fields: dict[str, Any] = {}
        if "name" in payload:
            fields["name"] = str(payload["name"]).strip()
        if "endpoint" in payload:
            fields["endpoint"] = str(payload["endpoint"]).strip()
        if "enabled" in payload:
            fields["enabled"] = bool(payload["enabled"])
        if "autoConnect" in payload or "auto_connect" in payload:
            fields["auto_connect"] = bool(payload.get("autoConnect", payload.get("auto_connect")))
        if "timeoutSeconds" in payload or "timeout_seconds" in payload:
            fields["timeout_seconds"] = float(payload.get("timeoutSeconds", payload.get("timeout_seconds")))
        if "refreshIntervalSeconds" in payload or "refresh_interval_seconds" in payload:
            fields["refresh_interval_seconds"] = float(
                payload.get("refreshIntervalSeconds", payload.get("refresh_interval_seconds"))
            )
        if "apiKey" in payload or "api_key" in payload:
            key = payload.get("apiKey", payload.get("api_key"))
            # Empty string clears key; None means leave unchanged (omit)
            if key is not None:
                fields["api_key_ciphertext"] = key if key != "" else None
        self.store.update_provider_fields(provider_id, **fields)
        self.store.append_audit("provider_updated", detail={"providerId": provider_id, "fields": list(fields)})
        self.invalidate_adapter(provider_id)
        return self.get_provider(provider_id)

    def delete_provider(self, provider_id: str) -> None:
        if not self.store.delete_provider(provider_id):
            raise ModelControlError(
                code=PROVIDER_NOT_FOUND,
                message=f"Provider not found: {provider_id}",
                provider_id=provider_id,
                http_status=404,
            )
        self.invalidate_adapter(provider_id)
        self.store.mark_provider_models_offline(provider_id)
        self.store.append_audit("provider_deleted", detail={"providerId": provider_id})

    async def test_provider(self, provider_id: str) -> dict[str, Any]:
        provider = self.get_provider(provider_id)
        adapter = self.get_adapter(provider_id)
        started = time.perf_counter()
        health, latency, error = await adapter.health()
        models_found = 0
        if health == ProviderHealth.HEALTHY:
            try:
                models = await adapter.discover()
                models_found = len(models)
                self.registry.upsert_discovered(models, provider_id=provider_id)
                self.registry.record_discovery_latency((time.perf_counter() - started) * 1000.0)
            except ModelControlError as exc:
                error = exc.message
                health = ProviderHealth.DEGRADED
        self.store.update_provider_fields(
            provider_id,
            health=health.value,
            last_latency_ms=latency,
            last_check_at=utc_now(),
            last_error=error,
            last_successful_at=utc_now() if health == ProviderHealth.HEALTHY else provider.last_successful_at,
            capabilities_json=adapter.capabilities().public_dict(),
        )
        self._emit(
            "model.health.changed",
            {"providerId": provider_id, "health": health.value, "latencyMs": latency},
        )
        return {
            "connected": health == ProviderHealth.HEALTHY,
            "providerId": provider_id,
            "provider": provider.name,
            "modelsFound": models_found,
            "latencyMs": latency,
            "health": health.value,
            "error": error,
        }

    async def test_inference(
        self,
        model_id: str,
        *,
        prompt: str = "ping",
        max_tokens: int = 64,
        stream: bool = False,
    ) -> dict[str, Any]:
        """Run a real inference through gateway capacity + provider adapter."""
        model = self.registry.get(model_id)
        call_id = self.gateway.acquire(
            model_id=model.id,
            provider_id=model.provider_id,
            timeout_seconds=30.0,
        )
        started = time.perf_counter()
        error_msg: str | None = None
        try:
            adapter = self.get_adapter(model.provider_id)
            _ = stream
            result = await adapter.test_inference(model.id, prompt=prompt, max_tokens=max_tokens)
            total_ms = (time.perf_counter() - started) * 1000.0
            self.registry.touch_used(model.id)
            self.gateway.record_selection(model.id, trace_id=call_id)
            self._emit(
                "model.inference.tested",
                {
                    "modelId": model.id,
                    "providerId": model.provider_id,
                    "latencyMs": total_ms,
                    "callId": call_id,
                    "streamRequested": bool(stream),
                },
            )
            return {
                "ok": True,
                "modelId": model.id,
                "providerId": model.provider_id,
                "callId": call_id,
                "traceId": call_id,
                "totalLatencyMs": total_ms,
                "ttftMs": result.get("latencyMs"),
                "finishReason": result.get("finishReason"),
                "preview": result.get("preview") or result.get("content") or "",
                "raw": {k: v for k, v in result.items() if k != "preview"},
                "streamRequested": bool(stream),
                "streamImplemented": False,
                "note": (
                    "Streaming token transport is not exposed on this test endpoint yet; "
                    "non-stream completion used the real provider path."
                    if stream
                    else None
                ),
            }
        except ModelControlError:
            error_msg = "model_control_error"
            raise
        except Exception as exc:
            error_msg = str(exc)
            raise ModelControlError(
                code="INFERENCE_FAILED",
                message=error_msg,
                model_id=model.id,
                provider_id=model.provider_id,
                http_status=503,
            ) from exc
        finally:
            self.gateway.release(
                model_id=model.id,
                provider_id=model.provider_id,
                error=error_msg,
            )

    async def refresh_all(self) -> dict[str, Any]:
        started = time.perf_counter()
        results: list[dict[str, Any]] = []
        for provider in self.list_providers():
            if not provider.enabled:
                results.append({"providerId": provider.provider_id, "skipped": True, "reason": "disabled"})
                continue
            try:
                adapter = self.get_adapter(provider.provider_id)
                health, latency, error = await adapter.health()
                models: list[Any] = []
                if health in {ProviderHealth.HEALTHY, ProviderHealth.DEGRADED}:
                    try:
                        models = await adapter.discover()
                        self.registry.upsert_discovered(models, provider_id=provider.provider_id)
                    except ModelControlError as exc:
                        error = exc.message
                        health = ProviderHealth.DEGRADED
                        self.store.mark_provider_models_offline(provider.provider_id)
                else:
                    self.store.mark_provider_models_offline(provider.provider_id)
                self.store.update_provider_fields(
                    provider.provider_id,
                    health=health.value,
                    last_latency_ms=latency,
                    last_check_at=utc_now(),
                    last_error=error,
                    last_successful_at=utc_now() if health == ProviderHealth.HEALTHY else provider.last_successful_at,
                    capabilities_json=adapter.capabilities().public_dict(),
                )
                results.append(
                    {
                        "providerId": provider.provider_id,
                        "health": health.value,
                        "models": len(models),
                        "latencyMs": latency,
                        "error": error,
                    }
                )
            except ModelControlError as exc:
                self.store.mark_provider_models_offline(provider.provider_id)
                self.store.update_provider_fields(
                    provider.provider_id,
                    health=ProviderHealth.OFFLINE.value,
                    last_error=exc.message,
                    last_check_at=utc_now(),
                )
                results.append({"providerId": provider.provider_id, "health": "offline", "error": exc.message})
                self._emit("model.discovery.failed", {"providerId": provider.provider_id, "error": exc.message})
        latency_ms = (time.perf_counter() - started) * 1000.0
        self.registry.record_discovery_latency(latency_ms)
        return {"providers": results, "discoveryLatencyMs": latency_ms}

    def status_cards(self) -> dict[str, Any]:
        providers = self.list_providers()
        models = self.registry.list_descriptors()
        active = self.store.get_active_model_id()
        loaded = [m.id for m in models if m.loaded]
        healthy_providers = [p for p in providers if p.health == ProviderHealth.HEALTHY and p.enabled]
        runtime_label = "—"
        if healthy_providers:
            runtime_label = ", ".join(p.name for p in healthy_providers)
        elif providers:
            runtime_label = providers[0].health.value
        gateway = self.gateway.snapshot()
        return {
            "runtime": runtime_label,
            "availableModels": len(models),
            "activeModel": active,
            "loadedModels": len(loaded),
            "discoveryLatencyMs": self.registry.last_discovery_latency_ms,
            "gatewayHealth": (
                "healthy"
                if gateway.last_error is None and healthy_providers
                else ("degraded" if providers else "unknown")
            ),
            "lastRefreshAt": self.registry.last_refresh_at,
            "lastRefreshError": self.registry.last_refresh_error,
            "providerCount": len(providers),
            "offlineProviders": [
                p.public_dict() for p in providers if p.health in {ProviderHealth.OFFLINE, ProviderHealth.TIMEOUT}
            ],
        }

    def resolve_for_chat(
        self,
        *,
        explicit_model_id: str | None = None,
        preferred_role: str | None = None,
        required_capabilities: list[str] | None = None,
    ) -> dict[str, Any]:
        decision = self.router.resolve(
            ModelRequest(
                explicit_model_id=explicit_model_id,
                preferred_role=preferred_role,
                required_capabilities=tuple(required_capabilities or ()),
            )
        )
        model = self.registry.get(decision.model_id)
        profile = self.profiles.get_or_default(model.id)
        provider = self.store.get_provider(model.provider_id)
        endpoint = model.endpoint or (provider["endpoint"] if provider else self.settings.llm_base_url)
        api_key = (provider.get("api_key_ciphertext") if provider else None) or self.settings.llm_api_key
        provider_model_id = str(model.metadata.get("provider_model_id") or model.display_name)
        self._emit(
            "model.router.selected",
            decision.public_dict(),
        )
        if decision.fallback_used:
            self._emit("model.router.fallback", decision.public_dict())
        return {
            "decision": decision,
            "model": model,
            "profile": profile,
            "endpoint": endpoint,
            "api_key": api_key,
            "provider_model_id": provider_model_id,
            "provider_id": model.provider_id,
        }

    def _row_to_provider(self, row: dict[str, Any]) -> ProviderRecord:
        caps_raw = row.get("capabilities_json") or "{}"
        try:
            caps_data = json.loads(caps_raw) if isinstance(caps_raw, str) else (caps_raw or {})
        except json.JSONDecodeError:
            caps_data = {}
        caps = RuntimeCapabilities(
            discover_models=bool(caps_data.get("discoverModels", True)),
            import_model=bool(caps_data.get("importModel", False)),
            download_model=bool(caps_data.get("downloadModel", False)),
            load_model=bool(caps_data.get("loadModel", False)),
            unload_model=bool(caps_data.get("unloadModel", False)),
            delete_model=bool(caps_data.get("deleteModel", False)),
            list_loaded_models=bool(caps_data.get("listLoadedModels", False)),
            inference=bool(caps_data.get("inference", True)),
            streaming=bool(caps_data.get("streaming", True)),
            embeddings=bool(caps_data.get("embeddings", False)),
            tool_calling=bool(caps_data.get("toolCalling", False)),
            structured_output=bool(caps_data.get("structuredOutput", False)),
            vision=bool(caps_data.get("vision", False)),
            runtime_metrics=bool(caps_data.get("runtimeMetrics", False)),
            load_options=tuple(caps_data.get("loadOptions") or ()),
        )
        meta_raw = row.get("metadata_json") or "{}"
        try:
            meta = json.loads(meta_raw) if isinstance(meta_raw, str) else (meta_raw or {})
        except json.JSONDecodeError:
            meta = {}
        return ProviderRecord(
            provider_id=row["provider_id"],
            name=row["name"],
            provider_type=row["provider_type"],
            endpoint=row["endpoint"],
            enabled=bool(row["enabled"]),
            health=ProviderHealth(row.get("health") or "unknown"),
            api_key_configured=bool(row.get("api_key_ciphertext")),
            auto_connect=bool(row.get("auto_connect", True)),
            timeout_seconds=float(row.get("timeout_seconds") or 30),
            refresh_interval_seconds=float(row.get("refresh_interval_seconds") or 60),
            last_successful_at=row.get("last_successful_at"),
            last_error=row.get("last_error"),
            last_latency_ms=row.get("last_latency_ms"),
            last_check_at=row.get("last_check_at"),
            capabilities=caps,
            metadata=meta if isinstance(meta, dict) else {},
        )

    def _emit(self, name: str, payload: dict[str, Any]) -> None:
        if self.observability:
            self.observability.emit("models", name, payload=payload)


def LMStudioCaps() -> RuntimeCapabilities:
    return RuntimeCapabilities(
        discover_models=True,
        import_model=False,
        download_model=False,
        load_model=False,
        unload_model=False,
        delete_model=False,
        list_loaded_models=False,
        inference=True,
        streaming=True,
    )


def parse_load_options(payload: dict[str, Any] | None) -> LoadOptions | None:
    if not payload:
        return None
    return LoadOptions(
        context_length=payload.get("contextLength"),
        gpu_offload_layers=payload.get("gpuOffloadLayers"),
        gpu_memory_limit_bytes=payload.get("gpuMemoryLimitBytes"),
        cpu_threads=payload.get("cpuThreads"),
        batch_size=payload.get("batchSize"),
        flash_attention=payload.get("flashAttention"),
    )
