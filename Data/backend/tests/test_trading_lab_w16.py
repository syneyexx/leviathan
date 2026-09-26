"""W16 — PaperDeployment, feed health, sim/shadow/paper comparison."""

from __future__ import annotations

import unittest
from datetime import datetime, timedelta, timezone

from Data.modules.market_sim.features import FEATURE_PIPELINE_VERSION
from Data.modules.market_sim.paper_deployment import (
    arm_deployment_kill_switch,
    assert_deployment_may_order,
    assess_feed_health,
    compare_sim_shadow_paper,
    create_paper_deployment,
    refresh_deployment_feed,
)
from Data.modules.market_sim.strategy_asset import ExecutionCompatibilityManifest, StrategyAsset
from Data.modules.market_sim.types import MarketSimError, StrategyStatus


class PaperDeploymentTests(unittest.TestCase):
    def _asset(self, status: str = StrategyStatus.VALIDATED.value) -> StrategyAsset:
        return StrategyAsset(
            asset_id="asset-1",
            name="demo",
            version=2,
            status=status,
            compatibility=ExecutionCompatibilityManifest(
                required_feature_pipeline_version=FEATURE_PIPELINE_VERSION,
                required_features=["sma"],
                paper_compatible=True,
            ),
        )

    def test_rejects_incompatible_and_draft(self) -> None:
        with self.assertRaises(MarketSimError) as ctx:
            create_paper_deployment(
                asset=self._asset(StrategyStatus.DRAFT.value),
                universe=["AAA"],
                feed_id="feed-1",
                available_features={"sma"},
            )
        self.assertEqual(ctx.exception.code, "ASSET_NOT_READY")
        bad = self._asset()
        bad.compatibility.required_feature_pipeline_version = "other"
        with self.assertRaises(MarketSimError) as ctx2:
            create_paper_deployment(
                asset=bad,
                universe=["AAA"],
                feed_id="feed-1",
                available_features={"sma"},
            )
        self.assertEqual(ctx2.exception.code, "INCOMPATIBLE_DEPLOYMENT")

    def test_create_and_kill_and_feed_blocks(self) -> None:
        dep = create_paper_deployment(
            asset=self._asset(),
            universe=["AAA", "bbb"],
            feed_id="feed-1",
            available_features={"sma"},
            cadence="hourly",
        )
        self.assertEqual(dep.status, "VALIDATED")
        self.assertEqual(dep.universe, ["AAA", "BBB"])
        self.assertTrue(dep.public_dict()["truth"]["paper_does_not_prove_live_profitability"])
        self.assertFalse(dep.compatibility.public_dict()["live_compatible"])

        now = datetime.now(timezone.utc)
        healthy = assess_feed_health(
            feed_id="feed-1",
            last_tick_ts=(now - timedelta(seconds=5)).isoformat(),
            as_of=now.isoformat(),
        )
        self.assertEqual(healthy.status, "HEALTHY")
        refresh_deployment_feed(dep, healthy)
        dep.status = "RUNNING"
        assert_deployment_may_order(dep)

        stale = assess_feed_health(
            feed_id="feed-1",
            last_tick_ts=(now - timedelta(seconds=500)).isoformat(),
            as_of=now.isoformat(),
            max_staleness_seconds=60,
        )
        self.assertEqual(stale.status, "STALE")
        refresh_deployment_feed(dep, stale)
        with self.assertRaises(MarketSimError) as ctx:
            assert_deployment_may_order(dep)
        self.assertEqual(ctx.exception.code, "FEED_UNCERTAIN")

        refresh_deployment_feed(dep, healthy)
        arm_deployment_kill_switch(dep, armed=True, reason="operator")
        with self.assertRaises(MarketSimError) as ctx2:
            assert_deployment_may_order(dep)
        self.assertEqual(ctx2.exception.code, "KILL_SWITCH")


class GapComparisonTests(unittest.TestCase):
    def test_three_way_comparison(self) -> None:
        report = compare_sim_shadow_paper(
            symbol="AAA",
            modelled_fills=[{"price": 100}, {"price": 101}],
            shadow_intents=[{"price": 100.5}],
            paper_observed=[{"price": 102}],
        )
        self.assertEqual(report["modelled_vs_paper"]["status"], "MEASURED")
        self.assertIsNotNone(report["shadow_vs_paper"])
        self.assertTrue(report["truth"]["paper_does_not_prove_live_profitability"])
        empty = compare_sim_shadow_paper(symbol="BBB")
        self.assertEqual(empty["modelled_vs_paper"]["status"], "UNMEASURED")


if __name__ == "__main__":
    unittest.main()
