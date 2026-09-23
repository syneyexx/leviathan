"""FastAPI routes for the Model Control Plane."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from Data.modules.models import ModelControlError, ModelControlPlane, parse_load_options


def raise_model_error(exc: ModelControlError) -> None:
    raise HTTPException(status_code=exc.http_status, detail=exc.public_dict()) from exc


class ProfileUpdate(BaseModel):
    temperature: float | None = None
    topP: float | None = None
    topK: int | None = None
    maxTokens: int | None = None
    repeatPenalty: float | None = None
    seed: int | None = None
    systemPrompt: str | None = None
    activate: bool = False


class ProviderCreate(BaseModel):
    id: str | None = None
    name: str
    type: str
    endpoint: str
    enabled: bool = True
    apiKey: str | None = None
    autoConnect: bool = True
    timeoutSeconds: float = 30.0
    refreshIntervalSeconds: float = 60.0
    metadata: dict[str, Any] | None = None


class ProviderUpdate(BaseModel):
    name: str | None = None
    endpoint: str | None = None
    enabled: bool | None = None
    apiKey: str | None = None
    autoConnect: bool | None = None
    timeoutSeconds: float | None = None
    refreshIntervalSeconds: float | None = None


class RouterUpdate(BaseModel):
    fallbackOrder: list[str] | None = None
    roleModelOverrides: dict[str, str] | None = None
    cloudFallbackAllowed: bool | None = None
    streaming: bool | None = None
    streamProvisionalText: bool | None = None
    progressEventsEnabled: bool | None = None


class LoadRequest(BaseModel):
    contextLength: int | None = None
    gpuOffloadLayers: int | None = None
    gpuMemoryLimitBytes: int | None = None
    cpuThreads: int | None = None
    batchSize: int | None = None
    flashAttention: bool | None = None
    confirmOom: bool = False


class ImportRequest(BaseModel):
    source: str = Field(description="local_file | huggingface | ollama")
    path: str | None = None
    displayName: str | None = None
    repositoryId: str | None = None
    revision: str | None = None
    filename: str | None = None
    providerId: str | None = None


class DownloadRequest(BaseModel):
    source: str = Field(description="huggingface | ollama")
    repositoryId: str
    revision: str | None = None
    filename: str | None = None
    providerId: str | None = None


class ProbeRequest(BaseModel):
    capabilities: list[str] | None = None
    timeoutSeconds: float = 15.0


class InferenceTestRequest(BaseModel):
    prompt: str = Field(default="ping", min_length=1, max_length=8000)
    maxTokens: int = Field(default=64, ge=1, le=2048)
    stream: bool = False


class CompatibleQuery(BaseModel):
    requiredCapabilities: list[str] = Field(default_factory=list)
    locality: str = "any"


def build_models_router(plane: ModelControlPlane) -> APIRouter:
    router = APIRouter(tags=["models"])

    @router.get("/api/models/status")
    def models_status() -> dict:
        return {"status": plane.status_cards(), "telemetry": plane.resources.system_telemetry()}

    @router.get("/api/models")
    def list_models() -> dict:
        models = [m.public_dict() for m in plane.registry.list_descriptors()]
        return {
            "models": models,
            "status": plane.status_cards(),
            "discoveryLatencyMs": plane.registry.last_discovery_latency_ms,
        }

    @router.get("/api/models/gateway")
    def gateway() -> dict:
        return {"gateway": plane.gateway.snapshot().public_dict()}

    @router.get("/api/models/router")
    def get_router() -> dict:
        return {"router": plane.router.get_config().public_dict()}

    @router.put("/api/models/router")
    def put_router(payload: RouterUpdate) -> dict:
        try:
            config = plane.router.save_config(payload.model_dump(exclude_none=True))
        except ModelControlError as exc:
            raise_model_error(exc)
        return {"router": config.public_dict()}

    @router.post("/api/models/router/resolve")
    def resolve_router(
        explicitModelId: str | None = None,
        preferredRole: str | None = None,
        jobClass: str = "INTERACTIVE",
    ) -> dict:
        try:
            measured = plane.resolve_measured(
                explicit_model_id=explicitModelId,
                preferred_role=preferredRole,
                job_class=jobClass,
                persist=True,
            )
        except ModelControlError as exc:
            raise_model_error(exc)
        return {"route": measured}

    @router.get("/api/models/router/decisions")
    def list_route_decisions(limit: int = 50) -> dict:
        return {
            "decisions": plane.list_route_decisions(limit=limit),
            "truth": {"selection_is_not_permission": True},
        }

    @router.get("/api/models/serving/workers")
    def list_serving_workers() -> dict:
        return {
            "workers": plane.list_serving_workers(),
            "truth": {"dead_is_not_ready": True},
        }

    @router.post("/api/models/serving/reconcile")
    def reconcile_serving() -> dict:
        return plane.reconcile_serving_workers()

    @router.post("/api/models/refresh")
    async def refresh_models() -> dict:
        try:
            summary = await plane.refresh_all()
        except ModelControlError as exc:
            raise_model_error(exc)
        return {
            "summary": summary,
            "models": [m.public_dict() for m in plane.registry.list_descriptors()],
            "status": plane.status_cards(),
        }

    @router.post("/api/models/compatible")
    def compatible(payload: CompatibleQuery) -> dict:
        ids = plane.router.find_compatible(
            required_capabilities=payload.requiredCapabilities,
            locality=payload.locality,
        )
        return {"modelIds": ids}

    @router.get("/api/models/audit")
    def audit(limit: int = 50) -> dict:
        rows = plane.store.recent_audit(limit=limit)
        return {
            "events": [
                {
                    "id": row["id"],
                    "createdAt": row["created_at"],
                    "actor": row["actor"],
                    "action": row["action"],
                    "detail": row["detail_json"],
                }
                for row in rows
            ]
        }

    @router.post("/api/models/import")
    async def import_model(payload: ImportRequest) -> dict:
        try:
            source = payload.source.strip().lower()
            if source == "local_file":
                if not payload.path:
                    raise ModelControlError(
                        code="VALIDATION_ERROR",
                        message="path is required for local_file import",
                        http_status=422,
                    )
                model = plane.imports.import_local_path(
                    payload.path, display_name=payload.displayName
                )
                return {"model": model.public_dict()}
            if source == "huggingface":
                if not payload.repositoryId:
                    raise ModelControlError(
                        code="VALIDATION_ERROR",
                        message="repositoryId is required",
                        http_status=422,
                    )
                job = await plane.downloads.start_huggingface(
                    repository_id=payload.repositoryId,
                    revision=payload.revision,
                    filename=payload.filename,
                )
                return {"download": job.public_dict()}
            if source == "ollama":
                if not payload.repositoryId or not payload.providerId:
                    raise ModelControlError(
                        code="VALIDATION_ERROR",
                        message="repositoryId and providerId are required for ollama import",
                        http_status=422,
                    )
                job = await plane.downloads.start_ollama_pull(
                    provider_id=payload.providerId,
                    repository_id=payload.repositoryId,
                    revision=payload.revision,
                )
                return {"download": job.public_dict()}
            raise ModelControlError(
                code="VALIDATION_ERROR",
                message=f"Unsupported import source: {payload.source}",
                http_status=422,
            )
        except ModelControlError as exc:
            raise_model_error(exc)

    @router.post("/api/models/download")
    async def download_model(payload: DownloadRequest) -> dict:
        try:
            source = payload.source.strip().lower()
            if source == "huggingface":
                job = await plane.downloads.start_huggingface(
                    repository_id=payload.repositoryId,
                    revision=payload.revision,
                    filename=payload.filename,
                )
            elif source == "ollama":
                if not payload.providerId:
                    raise ModelControlError(
                        code="VALIDATION_ERROR",
                        message="providerId required for ollama download",
                        http_status=422,
                    )
                job = await plane.downloads.start_ollama_pull(
                    provider_id=payload.providerId,
                    repository_id=payload.repositoryId,
                    revision=payload.revision,
                )
            else:
                raise ModelControlError(
                    code="VALIDATION_ERROR",
                    message=f"Unsupported download source: {payload.source}",
                    http_status=422,
                )
        except ModelControlError as exc:
            raise_model_error(exc)
        return {"download": job.public_dict()}

    @router.get("/api/model-downloads")
    def list_downloads() -> dict:
        return {"downloads": [j.public_dict() for j in plane.downloads.list_jobs()]}

    @router.post("/api/model-downloads/{download_id}/cancel")
    def cancel_download(download_id: str) -> dict:
        try:
            job = plane.downloads.cancel(download_id)
        except ModelControlError as exc:
            raise_model_error(exc)
        return {"download": job.public_dict()}

    @router.get("/api/models/{model_id}")
    def get_model(model_id: str) -> dict:
        try:
            model = plane.registry.get(model_id)
            profile = plane.profiles.get_or_default(model_id)
            caps = [c.public_dict() for c in plane.probes.list_for_model(model_id)]
            provider = None
            try:
                provider = plane.get_provider(model.provider_id).public_dict()
            except ModelControlError:
                provider = None
            preflight = plane.resources.preflight(model).public_dict()
        except ModelControlError as exc:
            raise_model_error(exc)
        return {
            "model": model.public_dict(),
            "profile": profile.public_dict(),
            "capabilities": caps,
            "provider": provider,
            "preflight": preflight,
        }

    @router.get("/api/models/{model_id}/profile")
    def get_profile(model_id: str) -> dict:
        try:
            plane.registry.get(model_id)
            profile = plane.profiles.get_or_default(model_id)
        except ModelControlError as exc:
            raise_model_error(exc)
        return {"profile": profile.public_dict()}

    @router.put("/api/models/{model_id}/profile")
    def put_profile(model_id: str, payload: ProfileUpdate) -> dict:
        try:
            plane.registry.get(model_id)
            data = payload.model_dump(exclude_none=True)
            activate = bool(data.pop("activate", False))
            # Merge with existing so partial updates work
            current = plane.profiles.get_or_default(model_id).public_dict()
            merged = {
                "temperature": data.get("temperature", current["temperature"]),
                "topP": data.get("topP", current["topP"]),
                "topK": data.get("topK", current["topK"]),
                "maxTokens": data.get("maxTokens", current["maxTokens"]),
                "repeatPenalty": data.get("repeatPenalty", current["repeatPenalty"]),
                "seed": data.get("seed", current["seed"]),
                "systemPrompt": data.get("systemPrompt", current["systemPrompt"]),
            }
            profile = plane.profiles.save(model_id, merged, activate=activate)
            if activate:
                plane.registry.activate(model_id)
            plane.store.append_audit(
                "profile_updated",
                detail={"modelId": model_id, "activate": activate},
            )
        except ModelControlError as exc:
            raise_model_error(exc)
        return {"profile": profile.public_dict(), "activeModelId": plane.store.get_active_model_id()}

    @router.post("/api/models/{model_id}/activate")
    def activate_model(model_id: str) -> dict:
        try:
            model = plane.registry.activate(model_id)
            plane.profiles.save(
                model_id,
                plane.profiles.get_or_default(model_id).public_dict(),
                activate=True,
            )
        except ModelControlError as exc:
            raise_model_error(exc)
        return {"model": model.public_dict(), "activeModelId": model.id}

    @router.post("/api/models/{model_id}/load")
    async def load_model(model_id: str, payload: LoadRequest | None = None) -> dict:
        body = payload.model_dump() if payload else {}
        options = parse_load_options(body)
        try:
            result = await plane.runtime.load(
                model_id, options, confirm_oom=bool(body.get("confirmOom"))
            )
        except ModelControlError as exc:
            raise_model_error(exc)
        return result

    @router.post("/api/models/{model_id}/unload")
    async def unload_model(model_id: str) -> dict:
        try:
            result = await plane.runtime.unload(model_id)
        except ModelControlError as exc:
            raise_model_error(exc)
        return result

    @router.delete("/api/models/{model_id}")
    async def delete_model(model_id: str) -> dict:
        try:
            model = plane.registry.get(model_id)
            adapter = plane.get_adapter(model.provider_id)
            caps = adapter.capabilities()
            # Only call provider remove when supported; otherwise registry-only for imported files.
            if caps.delete_model:
                await adapter.remove(model_id)
            elif model.source.value not in {"imported", "downloaded"}:
                raise ModelControlError(
                    code="CAPABILITY_NOT_SUPPORTED",
                    message="Provider does not support model removal",
                    provider_id=model.provider_id,
                    model_id=model_id,
                    http_status=409,
                )
            # For imported/downloaded: refuse deleting arbitrary paths — only registry + files under download root
            if model.local_path and model.source.value in {"imported", "downloaded"}:
                from pathlib import Path

                path = Path(model.local_path)
                download_root = plane.downloads.download_root.resolve()
                try:
                    path.resolve().relative_to(download_root)
                    if path.is_file():
                        path.unlink()
                except ValueError:
                    # Outside download root — registry remove only, do not touch filesystem
                    pass
            plane.registry.remove_registry_entry(model_id)
        except ModelControlError as exc:
            raise_model_error(exc)
        return {"deleted": True, "modelId": model_id}

    @router.get("/api/models/{model_id}/capabilities")
    def get_capabilities(model_id: str) -> dict:
        try:
            caps = [c.public_dict() for c in plane.probes.list_for_model(model_id)]
            model = plane.registry.get(model_id)
        except ModelControlError as exc:
            raise_model_error(exc)
        return {"modelId": model_id, "declared": model.capabilities.public_dict(), "results": caps}

    @router.post("/api/models/{model_id}/probe")
    async def probe_model(model_id: str, payload: ProbeRequest | None = None) -> dict:
        try:
            results = await plane.probes.probe(
                model_id,
                capabilities=payload.capabilities if payload else None,
                timeout_seconds=payload.timeoutSeconds if payload else 15.0,
            )
        except ModelControlError as exc:
            raise_model_error(exc)
        return {"results": [r.public_dict() for r in results]}

    @router.post("/api/models/{model_id}/benchmark")
    async def benchmark_model(model_id: str) -> dict:
        try:
            result = await plane.benchmarks.quick_benchmark(model_id)
        except ModelControlError as exc:
            raise_model_error(exc)
        return {"benchmark": result}

    @router.post("/api/models/{model_id}/test")
    async def test_model_inference(model_id: str, payload: InferenceTestRequest) -> dict:
        """Exercise real gateway + provider inference (no fabricated output)."""
        try:
            result = await plane.test_inference(
                model_id,
                prompt=payload.prompt,
                max_tokens=payload.maxTokens,
                stream=payload.stream,
            )
        except ModelControlError as exc:
            raise_model_error(exc)
        return {"result": result}

    @router.get("/api/model-providers")
    def list_providers() -> dict:
        return {"providers": [p.public_dict() for p in plane.list_providers()]}

    @router.post("/api/model-providers")
    def create_provider(payload: ProviderCreate) -> dict:
        try:
            provider = plane.create_provider(payload.model_dump())
        except ModelControlError as exc:
            raise_model_error(exc)
        return {"provider": provider.public_dict()}

    @router.put("/api/model-providers/{provider_id}")
    def update_provider(provider_id: str, payload: ProviderUpdate) -> dict:
        try:
            provider = plane.update_provider(
                provider_id, payload.model_dump(exclude_none=True)
            )
        except ModelControlError as exc:
            raise_model_error(exc)
        return {"provider": provider.public_dict()}

    @router.delete("/api/model-providers/{provider_id}")
    def delete_provider(provider_id: str) -> dict:
        try:
            plane.delete_provider(provider_id)
        except ModelControlError as exc:
            raise_model_error(exc)
        return {"deleted": True, "providerId": provider_id}

    @router.post("/api/model-providers/{provider_id}/test")
    async def test_provider(provider_id: str) -> dict:
        try:
            result = await plane.test_provider(provider_id)
        except ModelControlError as exc:
            raise_model_error(exc)
        return result

    return router
