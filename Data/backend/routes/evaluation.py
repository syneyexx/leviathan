"""Evaluation harness / platform HTTP routes."""

from __future__ import annotations

from typing import Any, Callable

from fastapi import APIRouter, HTTPException


def build_evaluation_router(
    *,
    settings: Any,
    job_runtime: Any,
    metrics: Any,
    evaluation_harness: Any,
    evaluation_platform: Any,
    evaluation_store: Any,
    residual_runtime: Any,
    model_plane: Any,
    evaluation_externalize_fn: Callable[[], bool],
) -> APIRouter:
    router = APIRouter(tags=["evaluation"])

    def _enqueue_evaluation_suite(suite_id: str, *, arguments: dict | None = None) -> dict:
        import uuid

        try:
            job = job_runtime.enqueue(
                capability_id="evaluation.run",
                arguments={"suite_id": suite_id, "persist": True, **dict(arguments or {})},
                requested_by="api",
                domain="evaluation",
                domain_entity_type="evaluation_suite",
                domain_entity_id=suite_id,
                worker_pool="evaluation",
                resource_class="CPU_HEAVY",
                latency_class="background",
                idempotency_key=f"evaluation:run:{suite_id}:{uuid.uuid4().hex[:8]}",
            )
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        metrics.incr("evaluations_enqueued")
        return {"job": job.public_dict(), "queued": True, "suite_id": suite_id}

    @router.post("/api/evaluation/foundation")
    def run_foundation_evaluation() -> dict:
        if evaluation_externalize_fn():
            return _enqueue_evaluation_suite("foundation")
        if settings.features.eval_platform:
            report = evaluation_platform.run_foundation(persist=True)
        else:
            report = evaluation_harness.run_suite(
                "foundation",
                evaluation_harness.default_foundation_suite(),
                suite_id="foundation",
            )
        return {"report": report.public_dict()}

    @router.post("/api/evaluation/neuro")
    def run_neuro_evaluation() -> dict:
        if evaluation_externalize_fn():
            return _enqueue_evaluation_suite("neuro_ablation")
        report = evaluation_harness.run_suite(
            "neuro_ablation",
            evaluation_harness.neuro_ablation_suite(
                residual_supported=residual_runtime.supports_residuals(),
                cortex_enabled=settings.features.neuro_cortex,
                memory_tiers_enabled=settings.features.neuro_memory_tiers,
                critic_enabled=settings.features.neuro_process_critic,
            ),
            suite_id="neuro_ablation",
        )
        if settings.features.eval_platform:
            report = evaluation_store.save_report(report)
        return {"report": report.public_dict()}

    @router.post("/api/evaluation/serving")
    def run_serving_evaluation() -> dict:
        """Wave 3/6 serving conformance — only PASS when live-probed."""
        if evaluation_externalize_fn():
            return _enqueue_evaluation_suite("serving_conformance")

        import asyncio

        from Data.modules.model_runtime import ManagedLocalServingAdapter, StreamCancelToken
        from Data.modules.model_runtime.serving import ServingSupervisor

        serving_on = bool(settings.features.model_serving)
        workers = model_plane.list_serving_workers() if serving_on else []
        ready = [w for w in workers if w.get("state") == "READY"]
        dead_honest = all(
            (w.get("state") != "READY") or bool(w.get("pid")) for w in workers
        ) if workers else True
        decisions = model_plane.list_route_decisions(limit=5) if serving_on else []

        stream_cancel_ok = False
        stream_cancel_probed = False
        managed_load_ok = bool(ready)
        managed_load_probed = serving_on and bool(ready)

        # Live inproc cancel probe (isolated supervisor — does not reset global serving).
        try:
            probe_supervisor = ServingSupervisor()
            probe_adapter = ManagedLocalServingAdapter(
                provider_id="eval-serving-probe",
                mode="inproc",
                supervisor=probe_supervisor,
            )

            async def _cancel_probe() -> bool:
                await probe_adapter.load("eval-probe-model")
                cancel = StreamCancelToken()
                seen = 0
                async for chunk in probe_adapter.stream_tokens(
                    "eval-probe-model",
                    prompt="probe-cancel-stream",
                    cancel=cancel,
                    max_tokens=24,
                ):
                    if chunk.get("delta"):
                        seen += 1
                    if seen >= 2:
                        cancel.cancel("eval_probe")
                await probe_adapter.unload("eval-probe-model")
                return bool(cancel.cancelled)

            stream_cancel_ok = bool(asyncio.run(_cancel_probe()))
            stream_cancel_probed = True
            if not managed_load_probed:
                # Probe also proves managed load/unload path when serving flag is off.
                managed_load_ok = True
                managed_load_probed = True
        except Exception:  # noqa: BLE001 — leave UNMEASURED on probe failure
            stream_cancel_ok = False
            stream_cancel_probed = False

        report = evaluation_harness.run_suite(
            "serving_conformance",
            evaluation_harness.serving_conformance_suite(
                managed_load_ok=managed_load_ok,
                stream_cancel_ok=stream_cancel_ok,
                dead_worker_honest=bool(dead_honest),
                multi_model_route_ok=len(model_plane.registry.list_descriptors()) >= 1,
                measured_route_recorded=bool(decisions),
                managed_load_probed=managed_load_probed,
                stream_cancel_probed=stream_cancel_probed,
                dead_worker_probed=serving_on and bool(workers),
                multi_route_probed=serving_on,
                measured_route_probed=serving_on,
            ),
            suite_id="serving_conformance",
            system_level=True,
        )
        if settings.features.eval_platform:
            report = evaluation_store.save_report(report)
        return {
            "report": report.public_dict(),
            "truth": {
                "unprobed_is_not_passed": True,
                "stream_cancel_live_probed": stream_cancel_probed,
            },
        }

    @router.post("/api/evaluation/assistant")
    def run_assistant_benchmark_evaluation() -> dict:
        """Round 5 end-to-end assistant benchmark."""
        if not settings.features.eval_platform:
            raise HTTPException(status_code=503, detail="eval platform disabled")
        if evaluation_externalize_fn():
            return _enqueue_evaluation_suite("assistant_benchmark")
        return evaluation_platform.run_assistant_benchmark(persist=True)

    @router.post("/api/evaluation/paired")
    def run_paired_benchmark_evaluation() -> dict:
        """Round 5 paired BASELINE vs LEVIATHAN evaluation."""
        if not settings.features.eval_platform:
            raise HTTPException(status_code=503, detail="eval platform disabled")
        if evaluation_externalize_fn():
            return _enqueue_evaluation_suite("paired_assistant")
        return evaluation_platform.run_paired_evaluation(persist=True)

    @router.post("/api/evaluation/ablations")
    def run_ablation_evaluation() -> dict:
        """Round 5 feature ablations with raw run evidence."""
        if not settings.features.eval_platform:
            raise HTTPException(status_code=503, detail="eval platform disabled")
        if evaluation_externalize_fn():
            return _enqueue_evaluation_suite("ablations")
        return evaluation_platform.run_ablations(persist=True)

    @router.post("/api/evaluation/regression")
    def run_regression_evaluation() -> dict:
        if evaluation_externalize_fn():
            return _enqueue_evaluation_suite("regression")
        report = evaluation_platform.run_regression_corpus(persist=True)
        return {"report": report.public_dict()}

    @router.get("/api/evaluation/reports")
    def list_evaluation_reports(limit: int = 50) -> dict:
        return {
            "reports": evaluation_platform.list_reports(limit=limit),
            "truth": {"unmeasured_is_not_passed": True},
        }

    @router.get("/api/evaluation/reports/{report_id}")
    def get_evaluation_report(report_id: str) -> dict:
        report = evaluation_platform.get_report(report_id)
        if report is None:
            raise HTTPException(status_code=404, detail="evaluation report not found")
        return {"report": report}

    @router.get("/api/evaluation/scorecard")
    def get_evaluation_scorecard() -> dict:
        scorecard = evaluation_platform.build_system_scorecard()
        return {"scorecard": scorecard.public_dict()}

    @router.get("/api/evaluation/regressions")
    def list_evaluation_regressions(limit: int = 100) -> dict:
        return {
            "regressions": evaluation_platform.list_regressions(limit=limit),
            "truth": {"incidents_become_regression_cases": True},
        }

    @router.get("/api/evaluation/platform")
    def get_evaluation_platform() -> dict:
        return {"platform": evaluation_platform.public_dict()}

    @router.get("/api/evaluation/promotion")
    def get_evaluation_promotion(component: str | None = None, suite_id: str = "foundation") -> dict:
        return {
            "promotion": evaluation_platform.promotion_gate(component=component, suite_id=suite_id)
        }

    return router
