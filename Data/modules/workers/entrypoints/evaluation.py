"""Evaluation pool entrypoint — runs suites outside FastAPI; UNMEASURED stays UNMEASURED."""

from __future__ import annotations

from typing import Any

from Data.modules.workers.entrypoints._cli import main_for_pool


def _handler(ctx: dict[str, Any], job: Any) -> dict[str, Any] | None:
    from Data.modules.jobs.states import JobState

    args = dict(getattr(job, "arguments", None) or {})
    suite_id = str(args.get("suite_id") or args.get("suite") or "foundation")
    persist = bool(args.get("persist", True))

    try:
        settings = ctx["settings"]
        report_dict: dict[str, Any]

        if suite_id in {"foundation", "platform"} and getattr(settings.features, "eval_platform", False):
            from Data.modules.evaluation import EvaluationPlatform, EvaluationStore

            store = EvaluationStore(settings.database_path)
            store.initialize()
            platform = EvaluationPlatform(store=store)
            if hasattr(platform, "run_foundation"):
                report = platform.run_foundation(persist=persist)
            else:
                report = platform.run_suite(suite_id)  # type: ignore[attr-defined]
            report_dict = report.public_dict() if hasattr(report, "public_dict") else dict(report)
        else:
            from Data.modules.evaluation import EvaluationHarness, EvaluationStore

            harness = EvaluationHarness()
            cases_fn = {
                "foundation": getattr(harness, "default_foundation_suite", None),
                "neuro_ablation": getattr(harness, "neuro_ablation_suite", None),
            }.get(suite_id)
            if cases_fn is None:
                # Honest unavailable — do not invent a suite or mark PASS.
                ctx["job_store"].transition(
                    job.job_id,
                    JobState.COMPLETED,
                    result={
                        "suite_id": suite_id,
                        "measurement": "UNMEASURED",
                        "reason": "suite_builder_unavailable",
                        "truth": {"unmeasured_is_not_pass": True},
                    },
                )
                return {"suite_id": suite_id, "measurement": "UNMEASURED"}

            if suite_id == "neuro_ablation":
                cases = cases_fn(
                    residual_supported=False,
                    cortex_enabled=bool(getattr(settings.features, "neuro_cortex", False)),
                    memory_tiers_enabled=bool(getattr(settings.features, "neuro_memory_tiers", False)),
                    critic_enabled=bool(getattr(settings.features, "neuro_process_critic", False)),
                )
            else:
                cases = cases_fn()
            report = harness.run_suite(suite_id, cases, suite_id=suite_id)
            if persist and getattr(settings.features, "eval_platform", False):
                store = EvaluationStore(settings.database_path)
                store.initialize()
                report = store.save_report(report)
            report_dict = report.public_dict() if hasattr(report, "public_dict") else dict(report)

        # Never upgrade UNMEASURED/NOT_APPLICABLE to PASS in the worker.
        summary = report_dict.get("summary") or report_dict.get("scorecard") or {}
        ctx["job_store"].transition(
            job.job_id,
            JobState.COMPLETED,
            result={
                "suite_id": suite_id,
                "report": report_dict,
                "summary": summary,
                "truth": {
                    "unmeasured_is_not_pass": True,
                    "skipped_unavailable_is_not_success": True,
                },
            },
        )
        return {"suite_id": suite_id, "report_id": report_dict.get("report_id")}
    except Exception as exc:  # noqa: BLE001
        ctx["job_store"].transition(job.job_id, JobState.FAILED, error=str(exc)[:500])
        return {"error": str(exc)}


def main(argv: list[str] | None = None) -> int:
    return main_for_pool("evaluation", handler=_handler, argv=argv)


if __name__ == "__main__":
    raise SystemExit(main())
