"""Evaluation pool entrypoint — runs suites outside FastAPI via EvaluationPlatform.

UNMEASURED / unavailable / skip must never be converted to PASS.
"""

from __future__ import annotations

from typing import Any

from Data.modules.workers.entrypoints._cli import main_for_pool


def _build_platform(settings: Any):
    from Data.modules.evaluation import EvaluationHarness, EvaluationPlatform, EvaluationStore
    from Data.modules.execution import build_default_catalog

    harness = EvaluationHarness(catalog=build_default_catalog())
    store = EvaluationStore(settings.database_path)
    enabled = bool(getattr(getattr(settings, "features", None), "eval_platform", True))
    return EvaluationPlatform(harness=harness, store=store, enabled=enabled)


def _neuro_kwargs(settings: Any) -> dict[str, Any]:
    features = getattr(settings, "features", None)
    residual_supported = False
    residual_probed = False
    try:
        from Data.modules.neuro import build_residual_runtime

        neuro_cfg = getattr(settings, "neuro_runtime", None)
        runtime = build_residual_runtime(
            kind=getattr(neuro_cfg, "residual_kind", "unsupported") if neuro_cfg else "unsupported",
            model_id=getattr(neuro_cfg, "residual_model_id", None) if neuro_cfg else None,
            device=getattr(neuro_cfg, "residual_device", "cpu") if neuro_cfg else "cpu",
            load_weights=bool(getattr(neuro_cfg, "residual_load_weights", False)) if neuro_cfg else False,
            selected_layers=(
                (getattr(neuro_cfg, "residual_hook_layers", None) or None) if neuro_cfg else None
            ),
            server_url=getattr(neuro_cfg, "residual_server_url", None) if neuro_cfg else None,
        )
        residual_supported = bool(runtime.supports_residuals())
        residual_probed = True
    except Exception:  # noqa: BLE001 — honest UNMEASURED when residual runtime unavailable
        residual_supported = False
        residual_probed = False
    return {
        "residual_supported": residual_supported,
        "residual_probed": residual_probed,
        "cortex_enabled": bool(getattr(features, "neuro_cortex", False)),
        "memory_tiers_enabled": bool(getattr(features, "neuro_memory_tiers", False)),
        "critic_enabled": bool(getattr(features, "neuro_process_critic", False)),
    }


def _serving_kwargs(settings: Any) -> dict[str, Any]:
    """Live inproc cancel probe when possible; otherwise leave flags UNMEASURED."""
    import asyncio

    stream_cancel_ok = False
    stream_cancel_probed = False
    managed_load_ok = False
    managed_load_probed = False
    try:
        from Data.modules.model_runtime import ManagedLocalServingAdapter, StreamCancelToken
        from Data.modules.model_runtime.serving import ServingSupervisor

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
        managed_load_ok = True
        managed_load_probed = True
    except Exception:  # noqa: BLE001 — leave UNMEASURED on probe failure
        pass

    serving_on = bool(getattr(getattr(settings, "features", None), "model_serving", False))
    return {
        "managed_load_ok": managed_load_ok,
        "stream_cancel_ok": stream_cancel_ok,
        "dead_worker_honest": True,
        "multi_model_route_ok": False,
        "measured_route_recorded": False,
        "managed_load_probed": managed_load_probed,
        "stream_cancel_probed": stream_cancel_probed,
        "dead_worker_probed": False,
        "multi_route_probed": serving_on,
        "measured_route_probed": False,
    }


def execute_evaluation_run(settings: Any, *, suite_id: str, persist: bool = True) -> dict[str, Any]:
    """Run one named suite through EvaluationPlatform (testable without the claim loop)."""
    platform = _build_platform(settings)
    sid = str(suite_id or "foundation").strip() or "foundation"
    neuro = _neuro_kwargs(settings) if sid in {"neuro", "neuro_ablation"} else None
    serving = _serving_kwargs(settings) if sid in {"serving", "serving_conformance"} else None
    return platform.run_named_suite(
        sid,
        persist=persist,
        neuro_kwargs=neuro,
        serving_kwargs=serving,
    )


def _handler(ctx: dict[str, Any], job: Any) -> dict[str, Any] | None:
    from Data.modules.jobs.states import JobState

    args = dict(getattr(job, "arguments", None) or {})
    suite_id = str(args.get("suite_id") or args.get("suite") or "foundation")
    persist = bool(args.get("persist", True))

    try:
        result = execute_evaluation_run(ctx["settings"], suite_id=suite_id, persist=persist)
        # Defense in depth: never let a skip/unavailable path report PASS.
        measurement = str(result.get("measurement") or "UNMEASURED")
        if measurement.upper() == "PASS":
            summary = result.get("summary") or {}
            if int(summary.get("unmeasured") or 0) > 0:
                result = {
                    **result,
                    "measurement": "UNMEASURED",
                    "truth": {
                        **dict(result.get("truth") or {}),
                        "unmeasured_is_not_pass": True,
                        "skipped_unavailable_is_not_success": True,
                    },
                }
        ctx["job_store"].transition(job.job_id, JobState.COMPLETED, result=result)
        return {
            "suite_id": result.get("suite_id", suite_id),
            "measurement": result.get("measurement"),
            "report_id": (result.get("report") or {}).get("report_id")
            if isinstance(result.get("report"), dict)
            else result.get("persisted_report_id"),
        }
    except Exception as exc:  # noqa: BLE001
        ctx["job_store"].transition(job.job_id, JobState.FAILED, error=str(exc)[:500])
        return {"error": str(exc)}


def main(argv: list[str] | None = None) -> int:
    return main_for_pool("evaluation", handler=_handler, argv=argv)


if __name__ == "__main__":
    raise SystemExit(main())
