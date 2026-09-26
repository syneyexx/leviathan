"""Adversarial acceptance suite — W01/W02 false-success regressions (A01–A06, T01–T05)."""

from __future__ import annotations

import math
import tempfile
import unittest
from pathlib import Path

from Data.modules.cognition.ttc import Candidate, SchemaScorer
from Data.modules.evaluation.assistant_benchmark import (
    AssistantBenchmarkRunner,
    TaskFamily,
    default_assistant_tasks,
)
from Data.modules.market_sim.agent_lab import (
    AcceptanceCriteria,
    evaluate_candidate_pipeline,
    new_agent_lab,
)
from Data.modules.market_sim.causality import MarketView, SimulationClock
from Data.modules.market_sim.readiness import may_promote_to
from Data.modules.market_sim.types import Bar, MarketSimError


class MeasurementIntegrityAdversarialTests(unittest.TestCase):
    def test_a01_wrong_model_fails_no_fabricated_retry(self) -> None:
        calls: list[str] = []

        def caller(*, prompt: str) -> str:
            calls.append(prompt)
            return "WRONG"

        runner = AssistantBenchmarkRunner(model_caller=caller, profile="leviathan")
        task = next(t for t in default_assistant_tasks() if t.family == TaskFamily.INSTRUCTION_FOLLOWING)
        result = runner.run_task(task)
        self.assertFalse(result.success)
        self.assertTrue(result.metrics.measured)
        self.assertGreaterEqual(len(calls), 2)
        self.assertTrue(all("ACK" not in (a.get("response") or "") for a in (result.raw_evidence.get("attempts") or [])))

    def test_a02_no_model_unmeasured(self) -> None:
        runner = AssistantBenchmarkRunner(model_caller=None, profile="baseline")
        task = next(t for t in default_assistant_tasks() if t.family == TaskFamily.INSTRUCTION_FOLLOWING)
        result = runner.run_task(task)
        self.assertFalse(result.success)
        self.assertFalse(result.metrics.measured)
        self.assertFalse(result.public_dict()["truth"]["model_quality_measured"])

    def test_a03_schema_string_where_number_fails(self) -> None:
        scorer = SchemaScorer()
        candidate = Candidate(
            candidate_id="c1",
            output='{"value": "not-a-number"}',
            structured={"value": "not-a-number"},
        )
        score = scorer.score(
            candidate,
            context={
                "response_schema": {
                    "type": "object",
                    "required": ["value"],
                    "properties": {"value": {"type": "number"}},
                }
            },
        )
        self.assertTrue(score.hard_fail)
        self.assertLess(score.score, 1.0)


class TradingFalseSuccessAdversarialTests(unittest.TestCase):
    def test_t02_missing_and_nan_drawdown_fail(self) -> None:
        criteria = AcceptanceCriteria(min_trades=1, require_val_pass=False, require_robustness_pass=False)
        missing = criteria.evaluate({"trade_count": 5}, val_pass=True, robustness_pass=True)
        self.assertFalse(missing["passed"])
        self.assertTrue(any("drawdown" in r.lower() or "UNMEASURED" in r for r in missing["reasons"]))

        nan = criteria.evaluate(
            {"trade_count": 5, "max_drawdown_pct": float("nan")},
            val_pass=True,
            robustness_pass=True,
        )
        self.assertFalse(nan["passed"])
        inf = criteria.evaluate(
            {"trade_count": 5, "max_drawdown_pct": float("inf")},
            val_pass=True,
            robustness_pass=True,
        )
        self.assertFalse(inf["passed"])

    def test_t03_candidate_budget_atomic(self) -> None:
        lab = new_agent_lab(max_candidates=1)
        ok_metrics = {
            "trade_count": 10,
            "max_drawdown_pct": 5.0,
            "total_return_pct": 1.0,
        }
        evaluate_candidate_pipeline(
            lab,
            strategy_id="s1",
            strategy_version=1,
            hypothesis="h1",
            train_metrics=ok_metrics,
            val_metrics=ok_metrics,
            robustness_metrics=ok_metrics,
        )
        self.assertEqual(len(lab.candidates), 1)
        with self.assertRaises(MarketSimError) as ctx:
            evaluate_candidate_pipeline(
                lab,
                strategy_id="s2",
                strategy_version=1,
                hypothesis="h2",
                train_metrics=ok_metrics,
                val_metrics=ok_metrics,
                robustness_metrics=ok_metrics,
            )
        self.assertEqual(ctx.exception.code, "CANDIDATE_BUDGET_EXHAUSTED")
        self.assertEqual(len(lab.candidates), 1)

    def test_t04_caller_accepted_boolean_denied(self) -> None:
        gate = may_promote_to(current="A0", target="A4", evidence={"accepted": True})
        self.assertFalse(gate["allowed"])

    def test_t05_marketview_cache_advances_with_clock(self) -> None:
        bars = [
            Bar(ts="2024-01-01T00:00:00+00:00", open=1, high=1, low=1, close=1, volume=1),
            Bar(ts="2024-01-01T01:00:00+00:00", open=2, high=2, low=2, close=2, volume=1),
        ]
        clock = SimulationClock(bars=bars)
        clock.advance()
        view = MarketView(clock=clock, instrument="BTC", timeframe="1h")
        self.assertEqual(view.feature("close"), 1.0)
        clock.advance()
        self.assertEqual(view.feature("close"), 2.0)

    def test_t01_campaign_without_simulation_cannot_count_win(self) -> None:
        """Unit-level: fabricated trial results without simulation_executed are not wins."""
        from Data.modules.market_sim.scorecards import build_scorecard

        # Scorecard wins must be supplied from acceptance, not trial count.
        card = build_scorecard(
            agent_id="x",
            trials=3,
            wins=0,
            total_return=0.0,
            max_drawdown=1.0,
        )
        payload = card.public_dict()
        self.assertEqual(payload["wins"], 0)
        self.assertEqual(payload["trials"], 3)


class CitationValidityHonestyTests(unittest.TestCase):
    def test_a06_no_audit_is_unmeasured(self) -> None:
        import tempfile
        from pathlib import Path

        from Data.backend.migrations import MigrationRunner
        from Data.modules.research.quality_scorecard import build_quality_scorecard
        from Data.modules.research.store import ResearchStore
        from Data.modules.research.types import ResearchEvidence, ResearchSource, SourceType

        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "r.db"
            MigrationRunner(db).apply_all()
            store = ResearchStore(db)
            store.initialize()
            project = store.create_project(title="t", topic="topic about X")
            from datetime import datetime, timezone

            now = datetime.now(timezone.utc).isoformat()
            store.upsert_source(
                ResearchSource(
                    source_id="s1",
                    project_id=project.project_id,
                    source_type=SourceType.SEED,
                    created_at=now,
                    canonical_uri="seed://a",
                    original_uri="seed://a",
                    title="A",
                )
            )
            store.add_evidence(
                ResearchEvidence(
                    evidence_id="e1",
                    project_id=project.project_id,
                    source_id="s1",
                    span_text="some quote",
                    created_at=now,
                    location="span",
                )
            )
            card = build_quality_scorecard(store, project, report_markdown=None, citation_report=None)
            cit = card.dimensions["citation_validity"]
            self.assertEqual(cit.measurement, "UNMEASURED")
            self.assertIsNone(cit.score)


if __name__ == "__main__":
    unittest.main()
