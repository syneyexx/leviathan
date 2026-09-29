"""Wave 5 — strategy search grammar / multi-objective fitness."""

from __future__ import annotations

import unittest

from Data.modules.market_sim.learning_fitness import compute_fitness
from Data.modules.market_sim.learning_types import LearningObjectiveSpec
from Data.modules.market_sim.research_cycle import run_research_generation_cycle
from Data.modules.market_sim.strategy_search_grammar import (
    MULTI_OBJECTIVE_AXES,
    SearchPhase,
    SearchPrimitive,
    assess_leakage_risk,
    build_structure_for_family,
    enrich_proposal_with_contract,
    generate_hypothesis_candidate,
    list_primitives,
    optimize_parameters,
)


class StrategySearchGrammarTests(unittest.TestCase):
    def test_primitives_cover_required_domains(self) -> None:
        ids = {p["id"] for p in list_primitives()}
        for required in (
            "price_transform",
            "returns",
            "trend",
            "momentum",
            "volatility",
            "mean_reversion",
            "volume",
            "liquidity",
            "cross_sectional_rank",
            "spread",
            "term_structure",
            "carry",
            "macro",
            "fundamental",
            "event",
            "regime_filter",
            "risk_scaling",
            "portfolio_constraint",
            "execution_rule",
        ):
            self.assertIn(required, ids)

    def test_hypothesis_generation_separate_from_optimization(self) -> None:
        hyp = generate_hypothesis_candidate(
            family="momentum",
            perception={"regime": "trend_up"},
            falsifiable_hypothesis="Momentum beats costs on trend_up.",
        )
        self.assertEqual(hyp.phase, SearchPhase.HYPOTHESIS_GENERATION.value)
        self.assertTrue(hyp.falsifiable_hypothesis)
        self.assertTrue(hyp.expected_mechanism)
        self.assertTrue(hyp.expected_failure_regimes)
        self.assertTrue(hyp.required_data)
        self.assertTrue(hyp.parameter_bounds)
        self.assertIn(hyp.leakage_risk, {"LOW", "MEDIUM", "HIGH", "UNKNOWN"})

        optimized = optimize_parameters(hyp, suggested={"lookback": 999})
        self.assertEqual(optimized.phase, SearchPhase.PARAMETER_OPTIMIZATION.value)
        # Hypothesis preserved; params clamped to bounds.
        self.assertEqual(optimized.falsifiable_hypothesis, hyp.falsifiable_hypothesis)
        self.assertLessEqual(float(optimized.parameters["lookback"]), 120.0)
        self.assertNotEqual(optimized.phase, hyp.phase)

    def test_structure_composes_risk_and_execution(self) -> None:
        structure = build_structure_for_family("mean_reversion")
        prims = {n.primitive for n in structure.nodes}
        self.assertIn(SearchPrimitive.MEAN_REVERSION, prims)
        self.assertIn(SearchPrimitive.RISK_SCALING, prims)
        self.assertIn(SearchPrimitive.EXECUTION_RULE, prims)
        self.assertIn(SearchPrimitive.PORTFOLIO_CONSTRAINT, prims)

    def test_leakage_assessment_flags_fundamentals(self) -> None:
        risk, note = assess_leakage_risk(required_data=["ohlcv", "fundamentals"], uses_fundamentals=True)
        self.assertIn(risk, {"MEDIUM", "HIGH"})
        self.assertIn("fundamentals", note)

    def test_enrich_proposal_attaches_contract(self) -> None:
        enriched = enrich_proposal_with_contract(
            {"family": "rsi", "entry_rules": {"kind": "rsi"}, "parameters": {"period": 14}},
            perception={"regime": "range"},
        )
        self.assertIn("falsifiable_hypothesis", enriched)
        self.assertIn("leakage_risk", enriched)
        self.assertIn("parameter_bounds", enriched["metadata"])
        self.assertEqual(enriched["metadata"]["search_phase"], SearchPhase.HYPOTHESIS_GENERATION.value)

    def test_research_cycle_wires_grammar_contract(self) -> None:
        result = run_research_generation_cycle(
            perception_snapshot={"regime": "trend_up", "symbols": ["AAPL"], "timeframe": "1h"},
            family_preferences=["momentum"],
            model_complete=None,
        )
        self.assertTrue(result.author_proposals)
        proposal = result.author_proposals[0]
        meta = proposal.get("metadata") or {}
        self.assertTrue(meta.get("falsifiable_hypothesis") or proposal.get("falsifiable_hypothesis"))
        self.assertIn("leakage_risk", meta or proposal)

    def test_multi_objective_fitness_not_sharpe_only(self) -> None:
        for axis in (
            "tail_risk_quality",
            "turnover_quality",
            "concentration_quality",
            "cost_sensitivity_quality",
            "regime_stability",
        ):
            self.assertIn(axis, MULTI_OBJECTIVE_AXES)

        obj = LearningObjectiveSpec(objective_id="mo-test")
        fitness = compute_fitness(
            candidate_id="c1",
            split_role="TRAIN",
            metrics={
                "total_return_pct": 12.0,
                "sharpe": 1.2,
                "max_drawdown_pct": 8.0,
                "trade_count": 20,
                "turnover": 30.0,
                "total_fees": 5.0,
                "cvar_95": 6.0,
                "concentration": 40.0,
                "regime_stability": 0.8,
                "cost_sensitivity": 10.0,
            },
            objective=obj,
            complexity={"total": 8},
        )
        comps = fitness.components
        self.assertEqual(comps["tail_risk_quality"].status, "MEASURED")
        self.assertEqual(comps["regime_stability"].status, "MEASURED")
        self.assertEqual(comps["cost_sensitivity_quality"].status, "MEASURED")
        self.assertEqual(comps["concentration_quality"].status, "MEASURED")
        self.assertIsNotNone(fitness.scalar_score)
        # Missing Sharpe alone must not be the only axis — drawdown still measured.
        self.assertEqual(comps["drawdown_quality"].status, "MEASURED")


if __name__ == "__main__":
    unittest.main()
