"""Thin platform misc HTTP routes (architecture/metrics/telemetry/isolation/…)."""

from __future__ import annotations

from typing import Annotated, Any, Callable

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel, Field

from Data.modules.backup import BackupError
from Data.modules.chaos import ChaosPlan
from Data.modules.common import ownership_public_dict
from Data.modules.context import ContextBuilder
from Data.modules.execution import build_frontier_manifest
from Data.modules.isolation import IsolationMode, IsolationRequest
from Data.modules.jobs import JobState
from Data.modules.approvals import DEFAULT_AUTHORITY_PROFILE
from Data.modules.settings import DEFAULT_BEHAVIOR_PROFILE


class IsolationEvaluateRequest(BaseModel):
    requested: list[str] = Field(default_factory=list)
    reason: str = ""


class SecretLeaseRequest(BaseModel):
    secret_ref: str = Field(min_length=1, max_length=240)
    scope: str = Field(min_length=1, max_length=120)
    issued_to: str = Field(min_length=1, max_length=120)
    ttl_seconds: int | None = Field(default=None, ge=30, le=3600)
    run_id: str | None = None
    job_id: str | None = None


class TradingOrderRequest(BaseModel):
    symbol: str = Field(min_length=1, max_length=32)
    side: str = Field(min_length=1, max_length=16)
    quantity: float = Field(gt=0)


class BackupCreateRequest(BaseModel):
    note: str | None = Field(default=None, max_length=500)


class BackupRestoreRequest(BaseModel):
    backup_id: str = Field(min_length=1, max_length=120)
    confirm: bool = False


class ChaosConfigureRequest(BaseModel):
    enabled: bool = False
    latency_ms: int = Field(default=0, ge=0, le=60_000)
    error_rate: float = Field(default=0.0, ge=0.0, le=1.0)
    error_message: str = Field(default="chaos_injected_failure", max_length=200)


def build_platform_router(
    *,
    settings: Any,
    app_version: str,
    capability_catalog: Any,
    live_settings_fn: Callable[[], Any],
    metrics: Any,
    job_runtime: Any,
    observation_store: Any,
    observability: Any,
    intelligence_health: Any,
    product_truth_fn: Callable[[], dict],
    isolation_guard: Any,
    reasoner: Any,
    memory_store: Any,
    secrets_broker: Any,
    assert_loopback_fn: Callable[[Request], None],
    release_gates: Any,
    security_auditor: Any,
    native_runtime: Any,
    trading_stub: Any,
    backup_service: Any,
    chaos: Any,
    master_gates: Any,
) -> APIRouter:
    router = APIRouter(tags=["platform"])

    @router.get("/api/intelligence/health")
    async def intelligence_health_endpoint() -> dict:
        """Truthful intelligence-stack health for Settings banner & diagnostics."""
        return intelligence_health.build()

    @router.get("/api/product/truth")
    def get_product_truth() -> dict:
        """Thin alias for Round 9 Product Truth report (same as health.product_truth)."""
        return {"product_truth": product_truth_fn()}

    @router.get("/api/architecture/ownership")
    def architecture_ownership() -> dict:
        """Canonical ownership matrix (Wave 0 / U001–U020)."""
        return {
            "ownership": ownership_public_dict(),
            "behavior_profile": DEFAULT_BEHAVIOR_PROFILE.public_dict(include_prompt=False),
            "authority_profile": DEFAULT_AUTHORITY_PROFILE.public_dict(),
            "truth": {
                "behavior_is_not_authority": True,
                "extend_over_new": True,
                "external_first_is_not_second_architecture": True,
            },
        }

    @router.get("/api/architecture/capability-manifest")
    def architecture_capability_manifest() -> dict:
        """Frontier Capability Manifest derived from the live CapabilityCatalog (U016)."""
        manifest = build_frontier_manifest(
            capability_catalog,
            metadata={
                "durable_kernel": live_settings_fn().features.durable_kernel,
                "version": app_version,
            },
        )
        return {"manifest": manifest.public_dict()}

    @router.get("/api/metrics")
    def metrics_snapshot() -> dict:
        snap = metrics.snapshot(
            labels={"service": "leviathan", "version": app_version},
            enrich=lambda: {
                "jobs_queued": float(len(job_runtime.list(state=JobState.QUEUED, limit=500))),
                "capabilities": float(len(capability_catalog)),
                "observations": float(len(observation_store.list_observations(limit=500))),
            },
        )
        return {"metrics": snap.public_dict()}

    @router.get("/api/telemetry")
    def get_telemetry(
        limit: Annotated[int, Query(ge=1, le=500)] = 50,
        category: Annotated[str | None, Query()] = None,
    ) -> dict:
        return {
            "snapshot": observability.snapshot(),
            "events": [item.public_dict() for item in observability.recent(limit=limit, category=category)],
            "latest_sequence": observability.latest_sequence(),
            "truth": {
                "in_process_ring_buffer_only": observability.store is None,
                "durable_history": observability.store is not None,
                "not_a_production_apm": True,
                "redacted": True,
            },
        }

    @router.post("/api/context/preview")
    def preview_context(
        message: str = "preview",
        constraints: str | None = None,
        conversation_id: str | None = None,
    ) -> dict:
        """Compile a ContextPack preview — constraints retention + budget ledger visible."""
        plan = reasoner.analyze(message, has_knowledge=False)
        history: list[dict[str, str]] = [{"role": "user", "content": message}]
        if conversation_id:
            memory_hits = [
                item.as_context_item()
                for item in memory_store.search(message, limit=5, conversation_id=conversation_id)
            ]
        else:
            memory_hits = []
        pack = ContextBuilder(
            token_budget=settings.context.token_budget,
            max_knowledge_chars=settings.context.max_knowledge_chars,
            max_history_messages=settings.resources.max_history_messages,
            reserve_response_tokens=settings.context.reserve_response_tokens,
        ).build(
            history=history,
            knowledge=[],
            plan=plan,
            memory=memory_hits,
            constraints=constraints,
        )
        return {"pack": pack.public_dict()}

    @router.get("/api/isolation")
    def get_isolation() -> dict:
        return {"isolation": isolation_guard.evaluate().public_dict()}

    @router.post("/api/isolation/evaluate")
    def evaluate_isolation(payload: IsolationEvaluateRequest) -> dict:
        modes: list[IsolationMode] = []
        for raw in payload.requested:
            try:
                modes.append(IsolationMode(raw.upper()))
            except ValueError as exc:
                raise HTTPException(status_code=422, detail=f"Invalid isolation mode: {raw}") from exc
        report = isolation_guard.evaluate(
            IsolationRequest(requested=tuple(modes), reason=payload.reason)
        )
        return {"isolation": report.public_dict()}

    @router.post("/api/secrets/lease")
    def issue_secret_lease(payload: SecretLeaseRequest, request: Request) -> dict:
        assert_loopback_fn(request)
        try:
            lease = secrets_broker.issue(
                payload.secret_ref,
                scope=payload.scope,
                issued_to=payload.issued_to,
                ttl_seconds=payload.ttl_seconds,
                run_id=payload.run_id,
                job_id=payload.job_id,
            )
        except Exception as exc:  # noqa: BLE001
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        return {"lease": lease.public_dict()}

    @router.get("/api/release/gates")
    def release_gates_status() -> dict:
        from Data.modules.release import is_shipable

        report = release_gates.run()
        payload = report.public_dict()
        payload["shipable"] = is_shipable(report)
        payload["ci_release"] = bool(
            __import__("os").environ.get("LEVIATHAN_CI_RELEASE", "").strip()
        )
        return {"report": payload}

    @router.get("/api/release/ci")
    def release_ci_plan() -> dict:
        """Declarative CI plan — suites not executed here stay UNMEASURED, never PASS."""
        from Data.modules.release import default_leviathan_ci_plan

        return {"ci": default_leviathan_ci_plan().public_dict()}

    @router.get("/api/security/audit")
    def security_audit() -> dict:
        return {"report": security_auditor.run().public_dict()}

    @router.get("/api/native/probe")
    def native_probe() -> dict:
        return {"native": native_runtime.probe().public_dict()}

    @router.post("/api/trading/order")
    def trading_order(payload: TradingOrderRequest) -> dict:
        result = trading_stub.place_order(
            symbol=payload.symbol,
            side=payload.side,
            quantity=payload.quantity,
        )
        raise HTTPException(status_code=501, detail=result.public_dict())

    @router.get("/api/backup")
    def list_backups(limit: Annotated[int, Query(ge=1, le=200)] = 50) -> dict:
        return {"backups": [item.public_dict() for item in backup_service.list(limit=limit)]}

    @router.post("/api/backup")
    def create_backup(payload: BackupCreateRequest | None = None) -> dict:
        from Data.modules.workers.settings import load_worker_settings

        wsettings = load_worker_settings()
        if wsettings.enabled and wsettings.externalize_api_runners:
            try:
                job = job_runtime.enqueue(
                    capability_id="backup.create",
                    arguments={"note": (payload.note if payload else None)},
                    requested_by="api",
                    domain="backup",
                    worker_pool="backup",
                    resource_class="IO_HEAVY",
                    latency_class="maintenance",
                )
            except KeyError as exc:
                raise HTTPException(status_code=404, detail=str(exc)) from exc
            metrics.incr("backups_enqueued")
            return {"job": job.public_dict(), "queued": True}
        try:
            manifest = backup_service.create(note=(payload.note if payload else None))
        except BackupError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        metrics.incr("backups_created")
        return {"backup": manifest.public_dict()}

    @router.post("/api/backup/restore")
    def restore_backup(payload: BackupRestoreRequest) -> dict:
        try:
            manifest = backup_service.restore(payload.backup_id, confirm=payload.confirm)
        except BackupError as exc:
            status = 400 if "confirm" in str(exc).lower() else 404
            if "hash" in str(exc).lower():
                status = 409
            raise HTTPException(status_code=status, detail=str(exc)) from exc
        metrics.incr("backups_restored")
        return {"backup": manifest.public_dict(), "warning": "process should be restarted after restore"}

    @router.get("/api/chaos")
    def chaos_status() -> dict:
        return {"chaos": chaos.public_dict()}

    @router.post("/api/chaos/configure")
    def chaos_configure(payload: ChaosConfigureRequest) -> dict:
        if payload.enabled and not settings.runtime.loopback_only:
            raise HTTPException(status_code=403, detail="Chaos refused when loopback_only is false")
        plan = chaos.configure(
            ChaosPlan(
                enabled=payload.enabled,
                latency_ms=payload.latency_ms,
                error_rate=payload.error_rate,
                error_message=payload.error_message,
            )
        )
        return {"chaos": {"plan": plan.public_dict(), "activations": chaos.activations, "faults": chaos.faults}}

    @router.get("/api/master/gates")
    def master_gates_status() -> dict:
        return {"report": master_gates.run().public_dict()}

    return router
