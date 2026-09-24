"""Research narrative uses shared Model Control Plane caller (research role)."""

from __future__ import annotations

import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from typing import Any

from Data.modules.research import UnconfiguredWebProvider
from Data.modules.research.reports import ReportBuilder
from Data.modules.research.service import ResearchService
from Data.modules.research.store import ResearchStore
from Data.modules.research.types import AnalysisMode, ResearchDepth, ResearchStatus


class ResearchModelControlPlaneTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.db_path = self.root / "research.db"
        self.store = ResearchStore(self.db_path)
        self.store.initialize()
        self.calls: list[dict[str, Any]] = []

        def _caller(**kwargs: Any) -> dict[str, Any]:
            self.calls.append(dict(kwargs))
            return {
                "text": "Model narrative restating findings only.",
                "model_id": "research-model",
                "route": {"reason": "role:research"},
                "usage_source": "unavailable",
            }

        self.caller = _caller
        self.service = ResearchService(
            self.store,
            web=UnconfiguredWebProvider(),
            allow_outbound=False,
            snapshots_root=self.root / "snapshots",
            reports_root=self.root / "reports",
            sources_root=self.root / "sources",
            model_caller=self.caller,
        )

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_set_model_caller_propagates_to_reports(self) -> None:
        seen: list[Any] = []

        def alt(**kwargs: Any) -> dict[str, Any]:
            seen.append(kwargs)
            return {"text": "alt"}

        self.service.set_model_caller(alt)
        self.assertIs(self.service.model_caller, alt)
        self.assertIs(self.service.reports.model_caller, alt)
        self.assertIs(self.service.runner.reports.model_caller, alt)

    def test_model_analysis_mode_uses_research_role_and_background(self) -> None:
        project = self.store.create_project(
            title="Widget study",
            topic="Widget Alpha launch year",
            depth=ResearchDepth.QUICK,
        )
        project = self.store.save_project(
            replace(
                project,
                status=ResearchStatus.COMPLETED,
                analysis_mode=AnalysisMode.MODEL,
            )
        )
        builder = ReportBuilder(
            self.store,
            reports_root=self.root / "reports",
            model_caller=self.caller,
        )
        report = builder.generate(project)
        self.assertEqual(len(self.calls), 1)
        call = self.calls[0]
        self.assertEqual(call.get("model_role"), "research")
        self.assertEqual(call.get("domain"), "research")
        self.assertEqual(call.get("job_class"), "BACKGROUND")
        self.assertEqual(call.get("role"), "researcher")
        self.assertIn("Model-assisted narrative", report.body_markdown)
        self.assertTrue(report.generation_trace.get("model_assisted"))
        self.assertTrue(report.generation_trace.get("model_control_plane"))
        self.assertEqual(report.generation_trace.get("model_role"), "research")

    def test_deterministic_mode_skips_model_caller(self) -> None:
        project = self.store.create_project(
            title="Deterministic",
            topic="No model",
            depth=ResearchDepth.QUICK,
        )
        project = self.store.save_project(
            replace(
                project,
                status=ResearchStatus.COMPLETED,
                analysis_mode=AnalysisMode.DETERMINISTIC_FALLBACK,
            )
        )
        builder = ReportBuilder(
            self.store,
            reports_root=self.root / "reports",
            model_caller=self.caller,
        )
        report = builder.generate(project)
        self.assertEqual(self.calls, [])
        self.assertFalse(report.generation_trace.get("model_assisted"))
        self.assertTrue(report.generation_trace.get("deterministic"))


if __name__ == "__main__":
    unittest.main()
