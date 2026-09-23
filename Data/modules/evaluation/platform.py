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
        suite_ids: tuple[str, ...] = ("foundation", "regression"),
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
