"""Inference Efficiency Plane HTTP surfaces — typed operator contracts only."""

from __future__ import annotations

from typing import Annotated, Any, Literal

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from Data.modules.context.efficiency import InferenceEfficiencyPlane, get_efficiency_plane
from Data.modules.models.efficiency_capabilities import (
    external_provider_efficiency,
    probe_llama_cpp_efficiency,
    probe_vllm_efficiency,
)


class CacheClearBody(BaseModel):
    cacheType: (
        Literal[
            "tokenization",
            "context_compile",
            "retrieval",
            "embedding",
            "rerank",
            "exact_result",
            "semantic",
            "compaction_segments",
            "runtime_affinity",
        ]
        | None
    ) = None
    projectScope: str | None = Field(default=None, max_length=200)


class EfficiencyProbeBody(BaseModel):
    runtimeKind: Literal["llama_cpp", "vllm_class", "openai_compatible_external"]
    helpText: str | None = Field(default=None, max_length=200_000)
    backendVersion: str | None = Field(default=None, max_length=128)
    binaryPath: str | None = Field(default=None, max_length=1024)


def build_efficiency_router(plane: InferenceEfficiencyPlane | None = None) -> APIRouter:
    router = APIRouter(tags=["inference-efficiency"])

    def _plane() -> InferenceEfficiencyPlane:
        return plane or get_efficiency_plane()

    @router.get("/api/inference/efficiency")
    def efficiency_snapshot() -> dict[str, Any]:
        snap = _plane().snapshot()
        return {
            **snap,
            "truth": {
                **snap.get("truth", {}),
                "no_mock_production_data": True,
                "unknown_rendered_as_unknown": True,
            },
        }

    @router.get("/api/inference/efficiency/metrics")
    def efficiency_metrics() -> dict[str, Any]:
        return {"metrics": _plane().metrics.public_dict()}

    @router.get("/api/inference/tokenization/status")
    def tokenization_status(
        model_id: Annotated[str | None, Query()] = None,
    ) -> dict[str, Any]:
        svc = _plane().tokenization
        tok_id = None
        if model_id:
            tok_id = svc._model_tokenizer.get(model_id)
        return {
            "mode": svc.mode,
            "boundTokenizerId": tok_id,
            "cache": svc.cache_snapshot(),
            "modelId": model_id,
            "truth": {
                "exact_requires_real_tokenizer": True,
                "heuristic_fallback_is_honest": True,
                "no_silent_tokenizer_download": True,
            },
        }

    @router.post("/api/inference/efficiency/cache/clear")
    def clear_caches(body: CacheClearBody) -> dict[str, Any]:
        cleared = _plane().clear_caches(
            cache_type=body.cacheType,
            project_scope=body.projectScope,
        )
        return {
            "cleared": cleared,
            "truth": {
                "canonical_brain_untouched": True,
                "canonical_history_untouched": True,
                "domain_state_untouched": True,
            },
        }

    @router.post("/api/inference/efficiency/probe")
    def probe_runtime(body: EfficiencyProbeBody) -> dict[str, Any]:
        if body.runtimeKind == "llama_cpp":
            caps = probe_llama_cpp_efficiency(
                binary_path=body.binaryPath,
                help_text=body.helpText,
                backend_version=body.backendVersion,
            )
        elif body.runtimeKind == "vllm_class":
            caps = probe_vllm_efficiency(
                help_text=body.helpText,
                backend_version=body.backendVersion,
            )
        elif body.runtimeKind == "openai_compatible_external":
            caps = external_provider_efficiency()
        else:
            raise HTTPException(status_code=422, detail="unknown runtimeKind")
        return {
            "runtimeKind": body.runtimeKind,
            "capabilities": caps.public_dict(),
            "truth": {"not_inferred_from_name_alone": True},
        }

    @router.get("/api/inference/efficiency/affinity/{model_id}")
    def affinity(model_id: str) -> dict[str, Any]:
        aff = _plane().get_affinity(model_id)
        if aff is None:
            return {
                "modelId": model_id,
                "affinity": None,
                "runtimeGeneration": _plane().runtime_generation(model_id),
                "truth": {"no_assumed_live_kv_without_ready_worker": True},
            }
        return {"affinity": aff.public_dict()}

    return router
