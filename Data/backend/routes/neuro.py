"""Neuro residual / cortex / absorb / soak HTTP routes."""

from __future__ import annotations

from typing import Annotated, Any, Callable

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from Data.modules.model_runtime import chat_truth
from Data.modules.schedules import ScheduleTargetKind


class NeuroAssessRequest(BaseModel):
    text: str = Field(min_length=1, max_length=30_000)


class NeuroOrchestrateRequest(BaseModel):
    text: str = Field(min_length=1, max_length=30_000)
    complexity: str = Field(default="medium", max_length=32)
    run_forward: bool = False
    mode: str | None = Field(default=None, max_length=32)


class NeuroCortexRunRequest(BaseModel):
    text: str = Field(min_length=1, max_length=30_000)
    depth: int = Field(default=1, ge=0, le=4)
    critic_rounds: int = Field(default=1, ge=0, le=4)


class NeuroSnapshotRequest(BaseModel):
    tier: int = Field(ge=0, le=1)
    label: str = Field(default="snapshot", min_length=1, max_length=120)


class NeuroAbsorbRequest(BaseModel):
    limit: int = Field(default=50, ge=1, le=5000)


class NeuroAbsorbScheduleRequest(BaseModel):
    interval_seconds: int = Field(default=3600, ge=60, le=86400)
    limit: int = Field(default=50, ge=1, le=5000)
    approval_id: str = Field(min_length=1, max_length=120)
    name: str = Field(default="neuro-modeldata-absorb", min_length=1, max_length=120)


class NeuroSoakRequest(BaseModel):
    iterations: int = Field(default=3, ge=1, le=200)
    mode: str = Field(default="mini", max_length=16)


def build_neuro_router(
    *,
    settings: Any,
    residual_runtime: Any,
    residual_orchestrator: Any,
    residual_receipts: Any,
    neuro_contrastive: Any,
    neuro_advisor: Any,
    reasoner: Any,
    cortex_runtime: Any,
    neuro_memory: Any,
    neuro_snapshots: Any,
    neuro_absorb: Any,
    neuro_soak: Any,
    module_manager: Any,
    approval_service: Any,
    capability_catalog: Any,
    schedule_store: Any,
    observability: Any,
    metrics: Any,
    evaluation_externalize_fn: Callable[[], bool],
    enqueue_ingest_scan_fn: Callable[..., dict],
) -> APIRouter:
    router = APIRouter(tags=["neuro"])

    @router.get("/api/neuro/status")
    def neuro_status() -> dict:
        """Residual + contrastive + streaming posture (supervisor/runtime-backed)."""
        contrastive_ready = bool(
            settings.features.neuro_enabled
            and settings.features.neuro_contrastive_training
            and neuro_contrastive.embeddings_available
        )
        return {
            "enabled": settings.features.neuro_enabled,
            "residual": {
                "supports_residuals": residual_runtime.supports_residuals(),
                "kind": settings.neuro_runtime.residual_kind,
                "production": settings.features.residual_production,
                "orchestrator": settings.features.neuro_residual_orchestrator,
                "applied_count": int(residual_orchestrator.telemetry.get("injects_applied") or 0),
                "degraded_count": int(residual_orchestrator.telemetry.get("degraded") or 0),
                "degrade_reasons": dict(residual_orchestrator.telemetry.get("degrade_reasons") or {}),
                "supports_streaming_forward": bool(
                    getattr(residual_runtime, "supports_streaming_forward", lambda: False)()
                ),
                "runtime": (
                    residual_runtime.runtime_info()
                    if hasattr(residual_runtime, "runtime_info")
                    else {}
                ),
            },
            "contrastive": {
                "flag": settings.features.neuro_contrastive_training,
                "embeddings_available": neuro_contrastive.embeddings_available,
                "ready": contrastive_ready,
                "method": "embedding" if neuro_contrastive.embeddings_available else "lexical",
            },
            "streaming": {
                "chat_streaming": settings.features.chat_streaming,
                "chat_sse": settings.features.chat_sse,
                "posture": "sse_ready" if settings.features.chat_streaming else "disabled",
            },
            "truth": chat_truth(
                streaming_degraded=False,
                residual_implemented=residual_runtime.supports_residuals(),
                residual_applied=bool(residual_orchestrator.telemetry.get("injects_applied")),
            ),
        }

    @router.post("/api/neuro/assess")
    def neuro_assess(payload: NeuroAssessRequest) -> dict:
        plan = reasoner.analyze(payload.text, has_knowledge=False)
        assessment = neuro_advisor.assess(payload.text, plan=plan)
        return {"assessment": assessment.public_dict(), "reasoning": plan.public_summary()}

    @router.get("/api/neuro/residual")
    def neuro_residual_status() -> dict:
        hooks = [item.public_dict() for item in residual_runtime.list_hook_points()]
        info = residual_runtime.runtime_info() if hasattr(residual_runtime, "runtime_info") else {}
        return {
            "supports_residuals": residual_runtime.supports_residuals(),
            "hook_points": hooks,
            "runtime": info,
            "kind": settings.neuro_runtime.residual_kind,
            "residual_production": settings.features.residual_production,
            "residual_orchestrator": settings.features.neuro_residual_orchestrator,
            "load_weights": settings.neuro_runtime.residual_load_weights,
            "hook_layers": list(settings.neuro_runtime.residual_hook_layers),
            "cortex_max_k": settings.neuro_runtime.cortex_max_k,
            "orchestrator_telemetry": dict(residual_orchestrator.telemetry),
            "recent_receipts": residual_receipts.recent(limit=10),
            "truth": {
                "neural_signal_is_not_authority": True,
                "residual_injection_is_not_authority": True,
                "unsupported_is_not_success": True,
                "unapplied_is_not_success": True,
                "discoverable_is_not_authorized": True,
                "model_output_is_not_evidence": True,
                "unsupported_is_not_failure_of_core": True,
            },
        }

    @router.post("/api/neuro/residual/orchestrate")
    def neuro_residual_orchestrate(payload: NeuroOrchestrateRequest) -> dict:
        if not settings.features.neuro_enabled:
            raise HTTPException(status_code=503, detail="Neuro feature flag OFF")
        if not settings.features.neuro_residual_orchestrator:
            raise HTTPException(status_code=503, detail="Neuro residual orchestrator flag OFF")
        report = residual_orchestrator.orchestrate(
            messages=[{"role": "user", "content": payload.text}],
            complexity=payload.complexity,
            token_budget=settings.context.token_budget,
            run_forward=payload.run_forward,
            mode=payload.mode,
        )
        for receipt in report.receipts:
            residual_receipts.record(
                receipt,
                metadata={"source": "residual_orchestrator", "complexity": payload.complexity},
            )
        observability.emit(
            "neuro",
            "residual_orchestrate",
            payload={
                "plans": len(report.plans),
                "applied": sum(1 for r in report.receipts if r.applied),
                "available": report.residual_available,
            },
        )
        metrics.incr("neuro_residual_orchestrations")
        return {"report": report.public_dict()}

    @router.post("/api/neuro/cortex/run")
    def neuro_cortex_run(payload: NeuroCortexRunRequest) -> dict:
        if not settings.features.neuro_enabled or not settings.features.neuro_cortex:
            raise HTTPException(status_code=503, detail="Neuro cortex feature flags OFF")
        report = cortex_runtime.run(
            messages=[{"role": "user", "content": payload.text}],
            depth=payload.depth,
            critic_rounds=payload.critic_rounds,
        )
        observability.emit("neuro", "cortex_run", payload={"engaged": report.engaged, "degraded": report.degraded})
        metrics.incr("neuro_cortex_runs")
        return {"report": report.public_dict()}

    @router.post("/api/neuro/memory/snapshot")
    def neuro_memory_snapshot(payload: NeuroSnapshotRequest) -> dict:
        if not settings.features.neuro_memory_tiers:
            raise HTTPException(status_code=503, detail="Neuro memory tiers feature flag OFF")
        try:
            snap = neuro_memory.snapshot(payload.tier, payload.label)
        except (RuntimeError, ValueError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return {"snapshot": snap.public_dict()}

    @router.get("/api/neuro/memory/snapshots")
    def neuro_memory_snapshots(tier: Annotated[int | None, Query(ge=0, le=1)] = None) -> dict:
        return {"snapshots": [item.public_dict() for item in neuro_snapshots.list(tier=tier)]}

    @router.post("/api/neuro/memory/snapshots/{snapshot_id}/restore")
    def neuro_memory_restore(snapshot_id: str) -> dict:
        if not settings.features.neuro_memory_tiers:
            raise HTTPException(status_code=503, detail="Neuro memory tiers feature flag OFF")
        try:
            snap = neuro_memory.restore(snapshot_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="Snapshot not found") from exc
        except (RuntimeError, ValueError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return {"snapshot": snap.public_dict()}

    @router.post("/api/neuro/absorb")
    def neuro_absorb_scan(payload: NeuroAbsorbRequest) -> dict:
        """Operator-triggered ModelData absorb via Knowledge V2 (not a parallel pipeline)."""
        if evaluation_externalize_fn():
            queued = enqueue_ingest_scan_fn(
                payload.limit, requested_by="api.neuro.absorb", extra_metadata={"neuro_absorb": True}
            )
            observability.emit("neuro", "absorb.enqueued", payload={"job_id": queued["job"]["job_id"]})
            metrics.incr("neuro_absorb_scans")
            return queued
        result = neuro_absorb.scan_once(limit=payload.limit)
        observability.emit("neuro", "absorb", payload={"ingested": result.get("ingested", 0)})
        metrics.incr("neuro_absorb_scans")
        return result

    @router.post("/api/neuro/absorb/schedule")
    def neuro_absorb_schedule(payload: NeuroAbsorbScheduleRequest) -> dict:
        """Create an interval Job schedule for knowledge.ingest_scan (WRITE → approval required)."""
        if not approval_service.is_approved(
            payload.approval_id,
            capability_id="knowledge.ingest_scan",
            side_effects=capability_catalog.require("knowledge.ingest_scan").side_effects,
        ):
            raise HTTPException(status_code=403, detail="approval_id not valid for knowledge.ingest_scan")
        record = schedule_store.create(
            name=payload.name,
            target_kind=ScheduleTargetKind.JOB,
            target_ref="knowledge.ingest_scan",
            interval_seconds=payload.interval_seconds,
            target_payload={
                "arguments": {"limit": payload.limit},
                "approval_id": payload.approval_id,
            },
            metadata={"neuro_absorb": True, "uses_knowledge_v2": True},
        )
        observability.emit(
            "neuro",
            "absorb_schedule",
            payload={"schedule_id": record.schedule_id, "interval_seconds": payload.interval_seconds},
        )
        return {
            "schedule": record.public_dict(),
            "truth": {
                "schedule_is_not_authority": True,
                "write_still_requires_approval": True,
                "no_parallel_ingest_pipeline": True,
            },
        }

    @router.post("/api/neuro/soak")
    def neuro_soak_run(payload: NeuroSoakRequest) -> dict:
        """Local soak for neuro contracts — mini or long; never a multi-hour SLO claim."""

        def _assess() -> str:
            result = neuro_advisor.assess("soak probe delete risk", plan=reasoner.analyze("soak", False))
            return f"signals={len(result.signals)} enabled={result.enabled}"

        def _residual() -> str:
            return f"supports={residual_runtime.supports_residuals()} kind={settings.neuro_runtime.residual_kind}"

        def _modules() -> str:
            return f"enabled={module_manager.enabled} count={len(module_manager.list())}"

        def _orchestrator() -> str:
            return (
                f"enabled={residual_orchestrator.enabled} "
                f"telemetry={residual_orchestrator.telemetry.get('orchestrations', 0)}"
            )

        try:
            report = neuro_soak.run(
                iterations=payload.iterations,
                mode=payload.mode,
                steps=[
                    ("neuro_assess", _assess),
                    ("residual_port", _residual),
                    ("module_manager", _modules),
                    ("residual_orchestrator", _orchestrator),
                ],
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        metrics.incr("neuro_soak_runs")
        return {"report": report.public_dict()}

    @router.post("/api/neuro/contrastive")
    def neuro_contrastive_retrieve(payload: NeuroAssessRequest) -> dict:
        report = neuro_contrastive.retrieve(payload.text)
        return {"report": report.public_dict()}

    return router
