"""Evaluation platform — harness + durable store + scorecards + promotion checks.

EXTENDS EvaluationHarness; does not replace it. One empirical owner (U321–U340).
"""

from __future__ import annotations

from typing import Any

from .harness import EvaluationHarness
from .scorecard import build_scorecard, scorecard_from_report_dicts
from .store import EvaluationStore, seed_default_regressions
from .types import (
    EvalCase,
    EvalReport,
    MeasurementState,
    RegressionCase,
    Scorecard,
    measurement_is_pass,
)


class EvaluationPlatform:
    """Wave 2 control surface: run → record → scorecard → promotion relevance."""

    def __init__(
        self,
        *,
        harness: EvaluationHarness,
        store: EvaluationStore,
        enabled: bool = True,
    ) -> None:
        self.harness = harness
        self.store = store
        self.enabled = enabled
        self.store.initialize()
        if self.enabled:
            seed_default_regressions(self.store)

    def run_and_record(
        self,
        name: str,
        cases: list[EvalCase] | tuple[EvalCase, ...],
        *,
        suite_id: str | None = None,
        suite_version: str = "1",
        system_level: bool = False,
        persist: bool = True,
    ) -> EvalReport:
        report = self.harness.run_suite(
            name,
            cases,
            suite_id=suite_id,
            suite_version=suite_version,
            system_level=system_level,
        )
        if persist and self.enabled:
            return self.store.save_report(report)
        return report

    def run_foundation(self, *, persist: bool = True) -> EvalReport:
        return self.run_and_record(
            "foundation",
            self.harness.default_foundation_suite(),
            suite_id="foundation",
            suite_version="2",
            system_level=True,
            persist=persist,
        )

    def run_regression_corpus(self, *, persist: bool = True) -> EvalReport:
        regressions = self.store.list_regressions()
        cases = [item.case for item in regressions]
        if not cases:
            cases = self.harness.default_regression_suite()
        return self.run_and_record(
            "regression",
            cases,
            suite_id="regression",
            suite_version="1",
            system_level=True,
            persist=persist,
        )

    def add_regression(self, item: RegressionCase) -> RegressionCase:
        return self.store.add_regression(item)

    def list_regressions(self, *, limit: int = 100) -> list[dict[str, Any]]:
        return [item.public_dict() for item in self.store.list_regressions(limit=limit)]

    def list_reports(self, *, limit: int = 50) -> list[dict[str, Any]]:
        return self.store.list_reports(limit=limit)

    def get_report(self, report_id: str) -> dict[str, Any] | None:
        return self.store.get_report(report_id)

    def latest_report(self, suite_id: str) -> dict[str, Any] | None:
        return self.store.latest_report(suite_id)

    def build_system_scorecard(
        self,
        *,
        suite_ids: tuple[str, ...] = (
            "foundation",
            "regression",
            "assistant_benchmark",
            "paired_assistant",
            "ablations",
            "neuro_ablation",
            "frontier_reasoning",
            "frontier_ablation",
            "serving_conformance",
        ),
        required_components: tuple[str, ...] | None = None,
    ) -> Scorecard:
        reports_raw: list[dict[str, Any]] = []
        for suite_id in suite_ids:
            latest = self.store.latest_report(suite_id)
            if latest:
                reports_raw.append(latest)
        if not reports_raw:
            # Empty scorecard — system UNMEASURED, never PASS.
            return build_scorecard(
                [],
                name="system scorecard",
                required_components=required_components or ("evaluation",),
            )
        return scorecard_from_report_dicts(
            reports_raw,
            name="system scorecard",
            required_components=required_components,
        )

    def has_relevant_eval(
        self,
        *,
        component: str | None = None,
        suite_id: str | None = None,
        require_pass: bool = False,
    ) -> dict[str, Any]:
        return self.store.has_relevant_eval(
            component=component,
            suite_id=suite_id,
            require_pass=require_pass,
        )

    def promotion_gate(
        self,
        *,
        component: str | None = None,
        suite_id: str = "foundation",
    ) -> dict[str, Any]:
        """Exit/promotion helper: relevant eval recorded; UNMEASURED ≠ promotable."""
        relevance = self.has_relevant_eval(
            component=component,
            suite_id=suite_id,
            require_pass=True,
        )
        measurement = MeasurementState(
            relevance.get("measurement") or MeasurementState.UNMEASURED.value
        )
        return {
            **relevance,
            "promotable": bool(relevance.get("promotable"))
            and measurement_is_pass(measurement),
            "truth": {
                "unmeasured_is_not_passed": True,
                "evaluation_required_for_promotion": True,
                "evaluation_is_not_production_proof": True,
            },
        }

    def run_assistant_benchmark(self, *, persist: bool = True) -> dict[str, Any]:
        """Round 5: end-to-end assistant benchmark across task families."""
        from .assistant_benchmark import AssistantBenchmarkRunner, default_assistant_tasks
        from .types import EvalCaseResult, EvalOutcome, EvalReport, JudgmentKind, MeasurementState

        runner = AssistantBenchmarkRunner(profile="leviathan")
        runs = runner.run_suite(default_assistant_tasks())
        results: list[EvalCaseResult] = []
        for run in runs:
            outcome = EvalOutcome.PASSED if run.success else EvalOutcome.FAILED
            if run.metrics.false_success:
                outcome = EvalOutcome.FAILED
            results.append(
                EvalCaseResult(
                    case_id=run.task_id,
                    outcome=outcome,
                    detail=run.detail,
                    judgment_kind=JudgmentKind.EXECUTABLE_VERIFIER,
                    measurement=MeasurementState.PASS
                    if outcome == EvalOutcome.PASSED
                    else MeasurementState.FAIL,
                    artifact_refs=(run.run_id,),
                    component="assistant",
                )
            )
        measured = EvalReport(
            suite_id="assistant_benchmark",
            name="assistant_benchmark",
            results=tuple(results),
            summary={
                "passed": sum(1 for r in results if r.outcome == EvalOutcome.PASSED),
                "failed": sum(1 for r in results if r.outcome == EvalOutcome.FAILED),
                "unmeasured": 0,
                "error": 0,
                "total": len(results),
            },
            suite_version="1",
            component_scope=("assistant",),
            system_level=True,
            artifact_refs=tuple(r.run_id for r in runs),
        )
        if persist and self.enabled:
            measured = self.store.save_report(measured)
        return {
            "report": measured.public_dict(),
            "runs": [r.public_dict() for r in runs],
            "truth": {
                "end_to_end_assistant_benchmark": True,
                "metrics_tracked": True,
            },
        }

    def run_paired_evaluation(self, *, persist: bool = False) -> dict[str, Any]:
        from .paired import run_paired_evaluation

        paired = run_paired_evaluation()
        payload = paired.public_dict()
        if persist and self.enabled:
            from .types import EvalCase, EvalCaseResult, EvalOutcome, EvalReport, JudgmentKind, MeasurementState

            results = []
            for delta in paired.deltas:
                if delta.regressed:
                    outcome, measurement = EvalOutcome.FAILED, MeasurementState.FAIL
                elif delta.improved or delta.leviathan_success:
                    outcome, measurement = EvalOutcome.PASSED, MeasurementState.PASS
                else:
                    outcome, measurement = EvalOutcome.FAILED, MeasurementState.FAIL
                results.append(
                    EvalCaseResult(
                        case_id=f"paired:{delta.task_id}",
                        outcome=outcome,
                        detail=delta.detail,
                        judgment_kind=JudgmentKind.EXECUTABLE_VERIFIER,
                        measurement=measurement,
                        paired_with=f"baseline:{delta.task_id}",
                        component="assistant",
                    )
                )
            report = EvalReport(
                suite_id="paired_assistant",
                name="paired_baseline_vs_leviathan",
                results=tuple(results),
                summary={
                    "passed": sum(1 for r in results if r.outcome == EvalOutcome.PASSED),
                    "failed": sum(1 for r in results if r.outcome == EvalOutcome.FAILED),
                    "unmeasured": 0,
                    "error": 0,
                    "total": len(results),
                },
                suite_version="1",
                component_scope=("assistant",),
                system_level=True,
            )
            saved = self.store.save_report(report)
            payload["persisted_report_id"] = saved.report_id
            # Surface regressions explicitly — never hide in aggregate.
            payload["regressions"] = [
                d.public_dict() for d in paired.deltas if d.regressed
            ]
        return payload

    def run_ablations(self, *, persist: bool = False) -> dict[str, Any]:
        from .ablations import run_all_ablations

        reports = run_all_ablations()
        payload = {
            "ablations": [r.public_dict() for r in reports],
            "truth": {
                "feature_flag_is_not_ablation_result": True,
                "raw_run_evidence_stored": True,
            },
        }
        if persist and self.enabled:
            from .types import EvalCaseResult, EvalOutcome, EvalReport, JudgmentKind, MeasurementState

            results = []
            for abl in reports:
                # Both conditions must be measured; PASS only if with/without executed.
                ok = abl.with_feature.measured and abl.without_feature.measured
                results.append(
                    EvalCaseResult(
                        case_id=f"ablation:{abl.feature}",
                        outcome=EvalOutcome.PASSED if ok else EvalOutcome.UNMEASURED,
                        detail=f"delta_success={abl.delta_success}",
                        judgment_kind=JudgmentKind.EXECUTABLE_VERIFIER,
                        measurement=MeasurementState.PASS if ok else MeasurementState.UNMEASURED,
                        artifact_refs=(abl.report_id,),
                        component="ablation",
                    )
                )
            report = EvalReport(
                suite_id="ablations",
                name="feature_ablations",
                results=tuple(results),
                summary={
                    "passed": sum(1 for r in results if r.outcome == EvalOutcome.PASSED),
                    "failed": 0,
                    "unmeasured": sum(1 for r in results if r.outcome == EvalOutcome.UNMEASURED),
                    "error": 0,
                    "total": len(results),
                },
                suite_version="1",
                component_scope=("ablation",),
                system_level=True,
            )
            saved = self.store.save_report(report)
            payload["persisted_report_id"] = saved.report_id
        return payload

    def run_frontier_reasoning(self, *, persist: bool = False) -> dict[str, Any]:
        """F16 / R24 frontier reasoning contract suite."""
        report = self.harness.run_suite(
            "frontier_reasoning",
            self.harness.frontier_reasoning_suite(),
            suite_id="frontier_reasoning",
            system_level=True,
        )
        if persist and self.enabled:
            report = self.store.save_report(report)
        return self._named_suite_report("frontier_reasoning", report)

    def run_frontier_ablations(self, *, persist: bool = False) -> dict[str, Any]:
        from .frontier_reasoning import frontier_ablation_public_bundle, run_all_frontier_ablations

        reports = run_all_frontier_ablations()
        payload = frontier_ablation_public_bundle()
        if persist and self.enabled:
            from .types import EvalCaseResult, EvalOutcome, EvalReport, JudgmentKind, MeasurementState

            results = []
            for abl in reports:
                ok = abl.with_feature.measured and abl.without_feature.measured
                results.append(
                    EvalCaseResult(
                        case_id=f"frontier_ablation:{abl.feature}",
                        outcome=EvalOutcome.PASSED if ok else EvalOutcome.UNMEASURED,
                        detail=f"delta_success={abl.delta_success}",
                        judgment_kind=JudgmentKind.EXECUTABLE_VERIFIER,
                        measurement=MeasurementState.PASS if ok else MeasurementState.UNMEASURED,
                        artifact_refs=(abl.report_id,),
                        component="cognition",
                    )
                )
            report = EvalReport(
                suite_id="frontier_ablation",
                name="frontier_feature_ablations",
                results=tuple(results),
                summary={
                    "passed": sum(1 for r in results if r.outcome == EvalOutcome.PASSED),
                    "failed": 0,
                    "unmeasured": sum(1 for r in results if r.outcome == EvalOutcome.UNMEASURED),
                    "error": 0,
                    "total": len(results),
                },
                suite_version="1",
                component_scope=("cognition",),
                system_level=True,
            )
            saved = self.store.save_report(report)
            payload["persisted_report_id"] = saved.report_id
        return payload

    def run_named_suite(
        self,
        suite_id: str,
        *,
        persist: bool = True,
        neuro_kwargs: dict[str, Any] | None = None,
        serving_kwargs: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Dispatch a known suite by id for workers / Job Kernel.

        Unknown or unavailable suites return measurement=UNMEASURED.
        Never converts skip / unavailable into PASS.
        """
        aliases = {
            "assistant": "assistant_benchmark",
            "paired": "paired_assistant",
            "platform": "foundation",
            "neuro": "neuro_ablation",
            "serving": "serving_conformance",
            "frontier": "frontier_reasoning",
        }
        sid = aliases.get(str(suite_id or "").strip(), str(suite_id or "").strip())

        if sid == "foundation":
            report = self.run_foundation(persist=persist)
            return self._named_suite_report(sid, report)
        if sid == "regression":
            report = self.run_regression_corpus(persist=persist)
            return self._named_suite_report(sid, report)
        if sid == "assistant_benchmark":
            payload = self.run_assistant_benchmark(persist=persist)
            return self._named_suite_payload(sid, payload)
        if sid == "paired_assistant":
            payload = self.run_paired_evaluation(persist=persist)
            if persist and self.enabled and payload.get("persisted_report_id"):
                saved = self.store.get_report(str(payload["persisted_report_id"]))
                if saved:
                    payload = {**payload, "report": saved}
            return self._named_suite_payload(sid, payload)
        if sid == "ablations":
            payload = self.run_ablations(persist=persist)
            if persist and self.enabled and payload.get("persisted_report_id"):
                saved = self.store.get_report(str(payload["persisted_report_id"]))
                if saved:
                    payload = {**payload, "report": saved}
            return self._named_suite_payload(sid, payload)
        if sid == "frontier_reasoning":
            return self.run_frontier_reasoning(persist=persist)
        if sid == "frontier_ablation":
            payload = self.run_frontier_ablations(persist=persist)
            if persist and self.enabled and payload.get("persisted_report_id"):
                saved = self.store.get_report(str(payload["persisted_report_id"]))
                if saved:
                    payload = {**payload, "report": saved}
            return self._named_suite_payload(sid, payload)
        if sid == "neuro_ablation":
            nk = dict(neuro_kwargs or {})
            report = self.harness.run_suite(
                "neuro_ablation",
                self.harness.neuro_ablation_suite(
                    residual_supported=bool(nk.get("residual_supported", False)),
                    cortex_enabled=bool(nk.get("cortex_enabled", False)),
                    memory_tiers_enabled=bool(nk.get("memory_tiers_enabled", False)),
                    critic_enabled=bool(nk.get("critic_enabled", False)),
                    residual_probed=bool(nk.get("residual_probed", False)),
                ),
                suite_id="neuro_ablation",
            )
            if persist and self.enabled:
                report = self.store.save_report(report)
            return self._named_suite_report(sid, report)
        if sid == "serving_conformance":
            sk = dict(serving_kwargs or {})
            # Defaults are honest UNMEASURED when probes are absent.
            report = self.harness.run_suite(
                "serving_conformance",
                self.harness.serving_conformance_suite(
                    managed_load_ok=bool(sk.get("managed_load_ok", False)),
                    stream_cancel_ok=bool(sk.get("stream_cancel_ok", False)),
                    dead_worker_honest=bool(sk.get("dead_worker_honest", True)),
                    multi_model_route_ok=bool(sk.get("multi_model_route_ok", False)),
                    measured_route_recorded=bool(sk.get("measured_route_recorded", False)),
                    managed_load_probed=bool(sk.get("managed_load_probed", False)),
                    stream_cancel_probed=bool(sk.get("stream_cancel_probed", False)),
                    dead_worker_probed=bool(sk.get("dead_worker_probed", False)),
                    multi_route_probed=bool(sk.get("multi_route_probed", False)),
                    measured_route_probed=bool(sk.get("measured_route_probed", False)),
                ),
                suite_id="serving_conformance",
                system_level=True,
            )
            if persist and self.enabled:
                report = self.store.save_report(report)
            return self._named_suite_report(sid, report)

        return {
            "suite_id": sid or "unknown",
            "measurement": MeasurementState.UNMEASURED.value,
            "reason": "unknown_or_unavailable_suite",
            "truth": {
                "unmeasured_is_not_pass": True,
                "skipped_unavailable_is_not_success": True,
            },
        }

    @staticmethod
    def _named_suite_report(suite_id: str, report: EvalReport) -> dict[str, Any]:
        payload = report.public_dict()
        summary = payload.get("summary") or {}
        measurement = MeasurementState.PASS.value
        if int(summary.get("unmeasured") or 0) > 0:
            measurement = MeasurementState.UNMEASURED.value
        elif int(summary.get("failed") or 0) > 0 or int(summary.get("error") or 0) > 0:
            measurement = MeasurementState.FAIL.value
        elif int(summary.get("passed") or 0) <= 0:
            measurement = MeasurementState.UNMEASURED.value
        return {
            "suite_id": suite_id,
            "report": payload,
            "summary": summary,
            "measurement": measurement,
            "truth": {
                "unmeasured_is_not_pass": True,
                "skipped_unavailable_is_not_success": True,
            },
        }

    @staticmethod
    def _named_suite_payload(suite_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        report = payload.get("report") if isinstance(payload.get("report"), dict) else None
        summary = (report or {}).get("summary") or {}
        if report:
            measurement = MeasurementState.PASS.value
            if int(summary.get("unmeasured") or 0) > 0:
                measurement = MeasurementState.UNMEASURED.value
            elif int(summary.get("failed") or 0) > 0 or int(summary.get("error") or 0) > 0:
                measurement = MeasurementState.FAIL.value
            elif int(summary.get("total") or 0) == 0:
                measurement = MeasurementState.UNMEASURED.value
        else:
            # No scored report — never invent PASS from a skip / empty payload.
            measurement = MeasurementState.UNMEASURED.value
            if payload.get("regressions"):
                measurement = MeasurementState.FAIL.value
        return {
            "suite_id": suite_id,
            **payload,
            "measurement": measurement,
            "truth": {
                **dict(payload.get("truth") or {}),
                "unmeasured_is_not_pass": True,
                "skipped_unavailable_is_not_success": True,
            },
        }

    def public_dict(self) -> dict[str, Any]:
        scorecard = self.build_system_scorecard()
        return {
            "enabled": self.enabled,
            "reports": len(self.store.list_reports(limit=200)),
            "regressions": len(self.store.list_regressions(limit=500)),
            "scorecard": scorecard.public_dict(),
            "truth": {
                "unmeasured_is_not_passed": True,
                "evaluation_is_release_authority_not_theatre": True,
                "one_empirical_platform": True,
            },
        }
