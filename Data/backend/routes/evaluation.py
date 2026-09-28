"""Evaluation harness / platform HTTP routes.

Production: all heavy suite execution is EXTERNAL_REQUIRED → evaluation worker.
Cheap reads (reports, scorecard from persisted evidence, promotion status) stay inline.
No FastAPI → run_suite / run_foundation / benchmark / ablation / regression fallback.
"""

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

    def _require_external_or_503() -> None:
        # Production composition: evaluation is always external. When the
        # externalize predicate is false (workers disabled), refuse rather than
        # falling back to inline suite execution.
        if not evaluation_externalize_fn():
            raise HTTPException(
                status_code=503,
                detail={
                    "code": "EVALUATION_WORKER_UNAVAILABLE",
                    "message": (
                        "Evaluation execution requires the evaluation worker; "
                        "inline FastAPI fallback is disabled in production"
                    ),
                },
            )

    def _enqueue_evaluation_suite(
        suite_id: str,
        *,
        arguments: dict | None = None,
        capability_id: str = "evaluation.run",
    ) -> dict:
        import uuid

        _require_external_or_503()
        try:
            job = job_runtime.enqueue(
                capability_id=capability_id,
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
        return _enqueue_evaluation_suite("foundation")

    @router.post("/api/evaluation/neuro")
    def run_neuro_evaluation() -> dict:
        return _enqueue_evaluation_suite("neuro_ablation")

    @router.post("/api/evaluation/serving")
    def run_serving_evaluation() -> dict:
        """Enqueue serving conformance — worker uses Model Control Plane evidence.

        Production release evidence must NOT treat an in-process serving fixture
        as production proof. Unprobed checks remain UNMEASURED.
        """
        return _enqueue_evaluation_suite("serving_conformance")

    @router.post("/api/evaluation/assistant")
    def run_assistant_benchmark_evaluation() -> dict:
        if not settings.features.eval_platform:
            raise HTTPException(status_code=503, detail="eval platform disabled")
        return _enqueue_evaluation_suite(
            "assistant_benchmark",
            capability_id="evaluation.benchmark",
        )

    @router.post("/api/evaluation/paired")
    def run_paired_benchmark_evaluation() -> dict:
        if not settings.features.eval_platform:
            raise HTTPException(status_code=503, detail="eval platform disabled")
        return _enqueue_evaluation_suite(
            "paired_assistant",
            capability_id="evaluation.benchmark",
        )

    @router.post("/api/evaluation/ablations")
    def run_ablation_evaluation() -> dict:
        if not settings.features.eval_platform:
            raise HTTPException(status_code=503, detail="eval platform disabled")
        return _enqueue_evaluation_suite(
            "ablations",
            capability_id="evaluation.ablation",
        )

    @router.post("/api/evaluation/regression")
    def run_regression_evaluation() -> dict:
        return _enqueue_evaluation_suite(
            "regression",
            capability_id="evaluation.regression",
        )

    @router.post("/api/evaluation/scorecard")
    def run_large_scorecard() -> dict:
        """Large scorecard aggregation — external. Small GET remains bound reads."""
        return _enqueue_evaluation_suite(
            "scorecard",
            capability_id="evaluation.scorecard",
        )

    @router.post("/api/evaluation/release/validate")
    def run_release_validation(payload: dict | None = None) -> dict:
        """POST executes typed release validation; GET status is a separate read."""
        plan_id = str((payload or {}).get("plan_id") or "default_leviathan_ci")
        return _enqueue_evaluation_suite(
            "release_validate",
            capability_id="evaluation.release.validate",
            arguments={"plan_id": plan_id},
        )

    @router.post("/api/evaluation/statistics")
    def run_statistics(payload: dict | None = None) -> dict:
        body = dict(payload or {})
        return _enqueue_evaluation_suite(
            "statistics",
            capability_id="evaluation.statistics",
            arguments=body,
        )

    @router.post("/api/evaluation/soak")
    def run_soak(payload: dict | None = None) -> dict:
        body = dict(payload or {})
        duration = float(body.get("duration_seconds") or 30.0)
        if duration > 3600:
            raise HTTPException(status_code=400, detail="soak duration exceeds ceiling")
        return _enqueue_evaluation_suite(
            "soak",
            capability_id="evaluation.soak",
            arguments=body,
        )

    @router.post("/api/evaluation/chaos")
    def run_chaos(payload: dict | None = None) -> dict:
        if not settings.runtime.loopback_only:
            raise HTTPException(status_code=403, detail="chaos refused when loopback_only is false")
        body = dict(payload or {})
        return _enqueue_evaluation_suite(
            "chaos",
            capability_id="evaluation.chaos",
            arguments=body,
        )

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
        """Cheap scorecard from already-persisted reports — does not execute suites."""
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

    @router.get("/api/evaluation/release/status")
    def get_release_validation_status() -> dict:
        """Read last release-validation evidence — never executes tests."""
        latest = None
        try:
            reports = evaluation_platform.list_reports(limit=20)
            for item in reports:
                suite = str(item.get("suite_id") or item.get("suiteId") or "")
                if suite in {"release_validate", "release_validation"}:
                    latest = item
                    break
        except Exception:  # noqa: BLE001
            latest = None
        return {
            "lastValidation": latest,
            "truth": {
                "getDoesNotExecuteReleaseTests": True,
                "unmeasuredIsNotPass": True,
            },
        }

    return router
