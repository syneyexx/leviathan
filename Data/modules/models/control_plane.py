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
    ModelHealthState,
    ModelLifecycleState,
    ModelRequest,
    ProviderHealth,
    ProviderRecord,
    ResidencyPolicyKind,
    ResolvedModelTarget,
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
from Data.modules.models.inference_session import open_inference_session
from Data.modules.models.profiles import ProfileService
from Data.modules.models.providers import build_adapter
from Data.modules.models.providers.openai_compatible import normalize_openai_base
from Data.modules.models.measured_routing import MeasuredRouter
from Data.modules.models.registry import ModelRegistry
from Data.modules.models.residency import ModelResidencyManager
from Data.modules.models.resource_manager import ResourceManager
from Data.modules.models.router import ModelRouter
from Data.modules.models.runtime_binding import (
    binding_from_row,
    binding_to_row,
    build_runtime_binding,
)
from Data.modules.models.runtime_manager import RuntimeManager
from Data.modules.models.store import ModelStore, utc_now
from Data.modules.model_runtime.serving import (
    InferenceJobClass,
    get_serving_supervisor,
)
from Data.modules.observability import ObservabilityHub


class ModelControlPlane:
    """Owns providers, registry, routing, gateway, lifecycle, acquisition, residency."""

    def __init__(
        self,
        settings: Settings,
        *,
        observability: ObservabilityHub | None = None,
        telemetry_provider: Any | None = None,
    ) -> None:
        self.settings = settings
        self.observability = observability
        self.store = ModelStore(settings.database_path)
        self.registry = ModelRegistry(self.store)
        self.profiles = ProfileService(self.store)
        self.gateway = ModelGateway(global_limit=settings.resources.max_model_concurrency)
        managed = getattr(settings, "managed_serving", None)
        self.resources = ResourceManager(
            telemetry_provider=telemetry_provider,
            min_ram_reserve_bytes=getattr(managed, "min_ram_reserve_bytes", 1_073_741_824),
            min_vram_reserve_bytes=getattr(managed, "min_vram_reserve_bytes", 536_870_912),
        )
        self.router = ModelRouter(
            self.store,
            self.gateway,
            get_models=self.registry.list_descriptors,
        )
        self.measured_router = MeasuredRouter(self.store, self.router.resolve)
        self.runtime = RuntimeManager(
            self.registry,
            self.resources,
            get_adapter=self.get_adapter,
        )
        self.serving = get_serving_supervisor()
        default_policy = ResidencyPolicyKind.IDLE_UNLOAD
        if managed is not None:
            try:
                default_policy = ResidencyPolicyKind(str(managed.default_residency_policy))
            except ValueError:
                default_policy = ResidencyPolicyKind.IDLE_UNLOAD
        self.residency = ModelResidencyManager(
            runtime_manager=self.runtime,
            resource_manager=self.resources,
            store=self.store,
            registry=self.registry,
            serving=self.serving,
            observability=observability,
            default_policy=default_policy,
            default_idle_unload_seconds=float(
                getattr(managed, "default_idle_unload_seconds", 300.0)
            ),
            allow_warm_then_unload=False,
            max_managed_resident=int(getattr(managed, "max_managed_resident_models", 4)),
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
        self._llm: Any | None = None

    def bind_llm(self, llm: Any) -> None:
        """Attach shared OpenAICompatibleLLM transport for inference sessions."""
        self._llm = llm

    def set_telemetry_provider(self, provider: Any) -> None:
        self.resources.set_telemetry_provider(provider)

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
        # Live leases never survive restart.
        self.residency.clear_live_leases_on_startup()
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
        # Round 6: stale READY rows in SQLite must become DEAD — never resurrect from disk.
        stale = self.reconcile_persisted_serving_workers()
        bindings = self.reconcile_runtime_bindings()
        self._emit("model.discovery.completed", {"summary": summary, "activeModelId": active})
        return {
            "summary": summary,
            "activeModelId": active,
            "staleServingWorkers": stale,
            "runtimeBindings": bindings,
        }

    def reconcile_runtime_bindings(self) -> list[dict[str, Any]]:
        """Recompute runtime bindings without wiping richer registry metadata."""
        managed = getattr(self.settings, "managed_serving", None)
        out: list[dict[str, Any]] = []
        for model in self.registry.list_descriptors():
            provider = self.store.get_provider(model.provider_id)
            provider_type = provider["provider_type"] if provider else model.provider_id
            endpoint = model.endpoint or (provider["endpoint"] if provider else None)
            binding = build_runtime_binding(
                model,
                provider_type=provider_type,
                provider_endpoint=endpoint,
                managed_serving_enabled=bool(getattr(managed, "enabled", False)),
                llama_cpp_executable=getattr(managed, "llama_cpp_executable", None),
                vllm_executable=getattr(managed, "vllm_executable", None),
            )
            # Preserve existing metadata keys that are richer than rebuild.
            existing = self.store.get_runtime_binding(model.id)
            if existing and isinstance(existing.get("metadata"), dict):
                merged = dict(existing["metadata"])
                merged.update(binding.metadata)
                binding.metadata = merged
            self.store.upsert_runtime_binding(binding_to_row(binding))
            out.append(binding.public_dict())
        return out

    def get_runtime_binding(self, model_id: str) -> Any:
        row = self.store.get_runtime_binding(model_id)
        if row:
            return binding_from_row(row)
        model = self.registry.get(model_id)
        provider = self.store.get_provider(model.provider_id)
        managed = getattr(self.settings, "managed_serving", None)
        binding = build_runtime_binding(
            model,
            provider_type=provider["provider_type"] if provider else model.provider_id,
            provider_endpoint=model.endpoint or (provider["endpoint"] if provider else None),
            managed_serving_enabled=bool(getattr(managed, "enabled", False)),
            llama_cpp_executable=getattr(managed, "llama_cpp_executable", None),
            vllm_executable=getattr(managed, "vllm_executable", None),
        )
        self.store.upsert_runtime_binding(binding_to_row(binding))
        return binding

    def reconcile_persisted_serving_workers(self) -> list[dict[str, Any]]:
        """On restart: persisted READY/STARTING with dead/missing pid → DEAD (honest)."""
        from Data.modules.common.process import pid_is_alive

        changed: list[dict[str, Any]] = []
        for row in self.store.list_serving_workers():
            state = str(row.get("state") or "")
            if state not in {"READY", "STARTING", "DRAINING", "UNHEALTHY"}:
                continue
            pid = row.get("pid")
            alive = isinstance(pid, int) and pid_is_alive(pid)
            if alive:
                # Do not auto-reattach into in-memory supervisor from SQLite alone.
                continue
            updated = {
                "worker_id": row["worker_id"],
                "provider_id": row["provider_id"],
                "model_id": row["model_id"],
                "backend_kind": row.get("backend_kind") or "unknown",
                "endpoint": row.get("endpoint"),
                "state": "DEAD",
                "pid": None,
                "health_score": 0.0,
                "revision_id": row.get("revision_id"),
                "last_error": row.get("last_error")
                or "stale serving worker after application restart",
                "started_at": row.get("started_at"),
                "last_health_at": row.get("last_health_at"),
                "metadata": {
                    **(row.get("metadata") or {}),
                    "reconcile_note": "process restart — prior READY is not current truth",
                },
            }
            self.store.upsert_serving_worker(updated)
            try:
                self.registry.set_lifecycle(
                    row["model_id"],
                    ModelLifecycleState.OFFLINE,
                    health=ModelHealthState.OFFLINE,
                    loaded=False,
                    error=updated["last_error"],
                )
            except Exception:  # noqa: BLE001
                pass
            changed.append(updated)
        return changed

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
        job_class: str = "INTERACTIVE",
        idempotency_key: str | None = None,
        timeout_seconds: float = 30.0,
    ) -> dict[str, Any]:
        """Run a real inference through gateway capacity + provider adapter."""
        from Data.modules.model_runtime.durable_requests import get_durable_request_ledger
        from Data.modules.model_runtime.latency import LatencyTimer
        from Data.modules.model_runtime.serving import InferenceJobClass

        try:
            jc = InferenceJobClass(job_class)
        except ValueError:
            jc = InferenceJobClass.INTERACTIVE

        model = self.registry.get(model_id)
        ledger = get_durable_request_ledger()
        durable = None
        replay = False
        if idempotency_key:
            durable, replay = ledger.begin(
                idempotency_key=idempotency_key,
                model_id=model.id,
                provider_id=model.provider_id,
                job_class=jc,
                metadata={"stream": bool(stream)},
            )
            if replay and durable.result is not None:
                out = dict(durable.result)
                out["idempotent_reuse"] = True
                out["side_effect_duplicated"] = False
                out["requestId"] = durable.request_id
                return out

        timer = LatencyTimer()
        timer.begin_queue()
        call_id = self.gateway.acquire(
            model_id=model.id,
            provider_id=model.provider_id,
            timeout_seconds=timeout_seconds,
            job_class=jc,
        )
        timer.end_queue()
        error_msg: str | None = None
        try:
            adapter = self.get_adapter(model.provider_id)
            _ = stream
            result = await adapter.test_inference(model.id, prompt=prompt, max_tokens=max_tokens)
            # Prefer provider-reported first-token if present; else admit→done as total.
            if result.get("latency") and isinstance(result["latency"], dict):
                lat = dict(result["latency"])
                if timer.queue_ms is not None:
                    lat["queue_ms"] = timer.queue_ms
                lat.setdefault(
                    "truth",
                    {
                        "stages_are_separated": True,
                        "unmeasured_is_not_zero": True,
                        "single_latency_is_not_enough": True,
                    },
                )
                latency_payload = lat
                total_ms = lat.get("total_ms")
                if total_ms is None:
                    timer.mark_first_token()
                    total_ms = timer.finish(source="control_plane").total_ms
                ttft = lat.get("ttft_ms")
            else:
                # Mark synthetic first-token at completion for non-streaming fixture path.
                timer.mark_first_token()
                breakdown = timer.finish(source="control_plane")
                latency_payload = breakdown.public_dict()
                total_ms = breakdown.total_ms
                ttft = breakdown.ttft_ms
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
                    "jobClass": jc.value,
                },
            )
            payload = {
                "ok": True,
                "modelId": model.id,
                "providerId": model.provider_id,
                "callId": call_id,
                "traceId": call_id,
                "totalLatencyMs": total_ms,
                "ttftMs": ttft if ttft is not None else result.get("latencyMs"),
                "latency": latency_payload,
                "finishReason": result.get("finishReason"),
                "preview": result.get("preview") or result.get("content") or result.get("output") or "",
                "raw": {k: v for k, v in result.items() if k != "preview"},
                "streamRequested": bool(stream),
                "streamImplemented": False,
                "jobClass": jc.value,
                "idempotent_reuse": False,
                "side_effect_duplicated": False,
                "note": (
                    "Streaming token transport is not exposed on this test endpoint yet; "
                    "non-stream completion used the real provider path."
                    if stream
                    else None
                ),
            }
            if durable is not None:
                fingerprint = f"{model.id}:{prompt}:{max_tokens}"
                ledger.complete(
                    durable.request_id,
                    result=payload,
                    side_effect_fingerprint=fingerprint,
                )
                payload["requestId"] = durable.request_id
            return payload
        except ModelControlError:
            error_msg = "model_control_error"
            if durable is not None:
                ledger.fail(durable.request_id, error_msg)
            raise
        except Exception as exc:
            error_msg = str(exc)
            if durable is not None:
                ledger.fail(durable.request_id, error_msg)
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
                job_class=jc,
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
        agent_model_id: str | None = None,
    ) -> dict[str, Any]:
        target = self.resolve_target(
            explicit_model_id=explicit_model_id,
            preferred_role=preferred_role,
            required_capabilities=required_capabilities,
            agent_model_id=agent_model_id,
        )
        return {
            "decision": target.route,
            "model": target.model,
            "profile": target.profile,
            "endpoint": target.endpoint,
            "api_key": target.api_key,
            "provider_model_id": target.backend_model_id,
            "provider_id": target.provider_id,
            "resolved": target,
        }

    def resolve_target(
        self,
        *,
        explicit_model_id: str | None = None,
        preferred_role: str | None = None,
        required_capabilities: list[str] | None = None,
        agent_model_id: str | None = None,
        job_class: str = "INTERACTIVE",
    ) -> ResolvedModelTarget:
        """Stage A — logical resolution. Does NOT load model weights."""
        # Normalize role aliases: general → chat
        role = preferred_role
        if role in {"general", "General"}:
            role = "chat"
        decision = self.router.resolve(
            ModelRequest(
                explicit_model_id=explicit_model_id,
                preferred_role=role,
                agent_model_id=agent_model_id,
                required_capabilities=tuple(required_capabilities or ()),
                job_class=job_class,
            )
        )
        model = self.registry.get(decision.model_id)
        profile = self.profiles.get_or_default(model.id)
        provider = self.store.get_provider(model.provider_id)
        endpoint = model.endpoint or (provider["endpoint"] if provider else self.settings.llm_base_url)
        api_key = (provider.get("api_key_ciphertext") if provider else None) or self.settings.llm_api_key
        provider_model_id = str(model.metadata.get("provider_model_id") or model.display_name)
        binding = self.get_runtime_binding(model.id)
        self._emit("model.router.selected", decision.public_dict())
        if decision.fallback_used:
            self._emit("model.router.fallback", decision.public_dict())
        return ResolvedModelTarget(
            model=model,
            route=decision,
            profile=profile,
            provider_id=model.provider_id,
            runtime_binding=binding,
            backend_model_id=provider_model_id,
            endpoint=endpoint,
            api_key=api_key,
            context_window=model.context_window,
            managed=bool(binding.managed) if binding else False,
            explicit_selection=bool(explicit_model_id),
            required_capabilities=tuple(required_capabilities or ()),
            preferred_role=role,
        )

    def inference_session(
        self,
        target: ResolvedModelTarget | None = None,
        *,
        llm: Any | None = None,
        consumer: str = "chat",
        domain: str | None = None,
        model_role: str | None = None,
        run_id: str | None = None,
        trace_id: str | None = None,
        job_class: str = "INTERACTIVE",
        explicit_model_id: str | None = None,
        preferred_role: str | None = None,
        required_capabilities: list[str] | None = None,
        agent_model_id: str | None = None,
        gateway_timeout_seconds: float | None = None,
    ):
        """Stage B — physical inference session context manager."""
        resolved = target or self.resolve_target(
            explicit_model_id=explicit_model_id,
            preferred_role=preferred_role or model_role,
            required_capabilities=required_capabilities,
            agent_model_id=agent_model_id,
            job_class=job_class,
        )
        transport = llm if llm is not None else self._llm
        if transport is None:
            raise ModelControlError(
                code=VALIDATION_ERROR,
                message="ModelControlPlane has no LLM transport bound",
                http_status=500,
            )
        return open_inference_session(
            self,
            resolved,
            llm=transport,
            consumer=consumer,
            domain=domain,
            model_role=model_role or resolved.preferred_role,
            run_id=run_id,
            trace_id=trace_id,
            job_class=job_class,
            gateway_timeout_seconds=gateway_timeout_seconds,
        )

    async def load_model(
        self,
        model_id: str,
        options: LoadOptions | None = None,
        *,
        confirm_oom: bool = False,
    ) -> dict[str, Any]:
        binding = self.get_runtime_binding(model_id)
        return await self.residency.manual_load(
            model_id,
            options=options,
            managed=bool(binding.managed),
            runtime_kind=binding.runtime_kind,
            confirm_oom=confirm_oom,
        )

    async def unload_model(self, model_id: str) -> dict[str, Any]:
        return await self.residency.manual_unload(model_id)

    def resolve_measured(
        self,
        *,
        explicit_model_id: str | None = None,
        preferred_role: str | None = None,
        required_capabilities: list[str] | None = None,
        job_class: str = "INTERACTIVE",
        persist: bool = True,
    ) -> dict[str, Any]:
        try:
            jc = InferenceJobClass(job_class)
        except ValueError:
            jc = InferenceJobClass.INTERACTIVE
        models = self.registry.list_descriptors()
        health_by_model: dict[str, float | None] = {}
        for worker in self.serving.list_workers():
            if worker.model_id not in health_by_model or worker.health_score is not None:
                health_by_model[worker.model_id] = worker.health_score
        measured = self.measured_router.resolve_measured(
            ModelRequest(
                explicit_model_id=explicit_model_id,
                preferred_role=preferred_role,
                required_capabilities=tuple(required_capabilities or ()),
                job_class=jc.value,
            ),
            models=models,
            job_class=jc,
            health_by_model=health_by_model,
            persist=persist,
        )
        self._emit("model.router.measured", measured.public_dict())
        return measured.public_dict()

    def list_serving_workers(self) -> list[dict[str, Any]]:
        workers = [w.public_dict() for w in self.serving.list_workers()]
        for worker in workers:
            self.store.upsert_serving_worker(
                {
                    "worker_id": worker["worker_id"],
                    "provider_id": worker["provider_id"],
                    "model_id": worker["model_id"],
                    "backend_kind": worker["backend_kind"],
                    "endpoint": worker.get("endpoint"),
                    "state": worker["state"],
                    "pid": worker.get("pid"),
                    "health_score": worker.get("health_score"),
                    "revision_id": worker.get("revision_id"),
                    "last_error": worker.get("last_error"),
                    "started_at": worker.get("started_at"),
                    "last_health_at": worker.get("last_health_at"),
                    "metadata": worker.get("metadata") or {},
                }
            )
        return workers

    def reconcile_serving_workers(self) -> dict[str, Any]:
        """Honest recovery: killed workers → DEAD; registry loaded flags cleared."""
        changed = self.serving.reconcile()
        adapter_changes: list[dict[str, Any]] = []
        for provider in self.list_providers():
            adapter = self.get_adapter(provider.provider_id)
            if hasattr(adapter, "reconcile_workers"):
                adapter_changes.extend(adapter.reconcile_workers())
        for worker in changed:
            self.store.upsert_serving_worker(
                {
                    "worker_id": worker.worker_id,
                    "provider_id": worker.provider_id,
                    "model_id": worker.model_id,
                    "backend_kind": worker.backend_kind,
                    "endpoint": worker.endpoint,
                    "state": worker.state.value,
                    "pid": worker.pid,
                    "health_score": worker.health_score,
                    "revision_id": worker.revision_id,
                    "last_error": worker.last_error,
                    "started_at": worker.started_at,
                    "last_health_at": worker.last_health_at,
                    "metadata": worker.metadata,
                }
            )
            if worker.state.value == "DEAD":
                try:
                    self.registry.set_lifecycle(
                        worker.model_id,
                        ModelLifecycleState.OFFLINE,
                        health=ModelHealthState.OFFLINE,
                        loaded=False,
                        error=worker.last_error or "serving worker dead",
                    )
                except Exception:  # noqa: BLE001
                    pass
        return {
            "changed": [w.public_dict() for w in changed],
            "adapter_changes": adapter_changes,
            "workers": self.list_serving_workers(),
            "truth": {
                "dead_is_not_ready": True,
                "killed_worker_recovery_is_honest": True,
            },
        }

    def list_route_decisions(self, *, limit: int = 50) -> list[dict[str, Any]]:
        return self.store.list_route_decisions(limit=limit)

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
