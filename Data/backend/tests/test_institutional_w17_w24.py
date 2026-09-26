"""WAVES 17–24 — risk, scenario, attribution, learning, champion, director, team, drift."""

from __future__ import annotations

import unittest

from Data.modules.market_sim.champion_challenger import ChampionChallengerPortfolio
from Data.modules.market_sim.institutional_team import InstitutionalAgentTeam
from Data.modules.market_sim.learning_multi_asset import MultiAssetLearningMandate, validate_learning_symbols
from Data.modules.market_sim.paper_forward_drift import paper_forward_drift_review
from Data.modules.market_sim.portefeuille.attribution import attribute_contributions
from Data.modules.market_sim.research_director import ResearchDirector, ResearchMandate
from Data.modules.market_sim.risk_analytics import compute_risk_analytics
from Data.modules.market_sim.scenario_risk import ScenarioSpec, apply_scenario


class RiskAnalyticsW17Tests(unittest.TestCase):
    def test_var_measured(self) -> None:
        returns = [-0.02, 0.01, -0.015, 0.005] * 5
        report = compute_risk_analytics(
            returns=returns,
            equity=100_000,
            gross_exposure=50_000,
            peak_equity=110_000,
            factor_loadings={"market": 0.8},
        )
        self.assertEqual(report.var_status, "MEASURED")
        self.assertIsNotNone(report.var_95)
        self.assertEqual(report.factor_status, "MEASURED")
        self.assertGreater(report.max_drawdown_pct or 0, 0)


class ScenarioW18Tests(unittest.TestCase):
    def test_scenario_applies_shock(self) -> None:
        scenario = ScenarioSpec(
            scenario_id="s1",
            name="AAPL -10%",
            shocks={"AAPL": -0.10},
        )
        result = apply_scenario(
            positions={"AAPL": {"qty": 100, "side": "LONG"}},
            marks={"AAPL": 100.0},
            cash=0.0,
            scenario=scenario,
        )
        self.assertAlmostEqual(result.base_equity, 10_000.0)
        self.assertAlmostEqual(result.shocked_equity, 9_000.0)
        self.assertAlmostEqual(result.pnl, -1_000.0)


class AttributionW19Tests(unittest.TestCase):
    def test_contributions_sum(self) -> None:
        out = attribute_contributions(
            positions=[
                {"symbol": "AAPL", "strategy_id": "s1", "unrealized_pnl": 100},
                {"symbol": "MSFT", "strategy_id": "s1", "unrealized_pnl": -40},
                {"symbol": "BTC", "strategy_id": "s2", "unrealized_pnl": 20},
            ],
            total_pnl=80,
        )
        self.assertEqual(out["sumContributions"], 80)
        self.assertEqual(out["residual"], 0)
        self.assertTrue(out["truth"]["not_brinson_factor_attribution"])


class MultiAssetLearningW20Tests(unittest.TestCase):
    def test_mandate_accepts_families(self) -> None:
        m = MultiAssetLearningMandate(
            run_id="r1",
            instrument_families=("equity", "forex"),
            primary_family="equity",
            symbols=("AAPL", "EURUSD"),
        )
        result = validate_learning_symbols(
            m, symbol_families={"AAPL": "equity", "EURUSD": "forex", "US10Y": "fixed_income"}
        )
        self.assertEqual(set(result["accepted"]), {"AAPL", "EURUSD"})
        self.assertEqual(result["rejected"][0]["symbol"], "US10Y")
        self.assertFalse(result["ok"])


class ChampionChallengerW21Tests(unittest.TestCase):
    def test_shadow_challenger_until_promote(self) -> None:
        port = ChampionChallengerPortfolio(portfolio_id="p1")
        port.set_champion("alpha", version=1)
        ch = port.add_challenger("beta", version=1, shadow=True)
        self.assertTrue(ch.shadow)
        self.assertEqual(port.champion.strategy_id, "alpha")
        port.promote_challenger("beta")
        self.assertEqual(port.champion.strategy_id, "beta")
        self.assertFalse(port.champion.shadow)


class ResearchDirectorW22Tests(unittest.TestCase):
    def test_director_runs_campaign(self) -> None:
        director = ResearchDirector()
        mandate = ResearchMandate(mandate_id="m1", objective="find momentum", max_campaigns=2)

        def factory(**kwargs):
            return {"campaignId": f"c-{kwargs['index']}", **kwargs}

        out = director.run_under_mandate(mandate, campaign_factory=factory)
        self.assertEqual(out["count"], 2)
        self.assertTrue(out["truth"]["director_does_not_unlock_live_trading"])


class InstitutionalTeamW23Tests(unittest.TestCase):
    def test_team_risk_veto(self) -> None:
        team = InstitutionalAgentTeam(team_id="t1")
        for role in ("strategy_researcher", "critic", "execution", "postmortem"):
            team.bind(role, f"agent-{role}")
        self.assertFalse(team.public_dict()["complete"])
        team.bind("risk", "agent-risk", can_veto=True)
        self.assertTrue(team.risk_can_veto())
        self.assertTrue(team.public_dict()["complete"])


class PaperForwardDriftW24Tests(unittest.TestCase):
    def test_drift_triggers_continual_research(self) -> None:
        out = paper_forward_drift_review(
            baseline_metrics={"sharpe": 1.0, "max_dd": 0.05},
            observed_metrics={"sharpe": 0.2, "max_dd": 0.05},
            relative_threshold=0.25,
        )
        self.assertGreaterEqual(out["driftCount"], 1)
        self.assertIsNotNone(out["continualResearch"])
        self.assertTrue(out["truth"]["auto_live_promotion_forbidden"])


if __name__ == "__main__":
    unittest.main()
