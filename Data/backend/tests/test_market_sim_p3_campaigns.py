"""P3A — Trading Orchestra cadence + asynchronous DecisionRecord semantics."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from Data.modules.market_sim.data_store import MarketDataStore
from Data.modules.market_sim.decision_cadence import (
    AsyncDecisionQueue,
    AsyncDecisionRecord,
    CADENCE_DAILY_CLOSE,
    CADENCE_EVERY_N_BARS,
    CADENCE_OFF,
    should_decide_on_bar,
)
from Data.modules.market_sim.service import MarketSimControlPlane
from Data.modules.market_sim.store import MarketSimStore
from Data.modules.market_sim.types import AgentConfig, AgentRole


class P3ADecisionCadenceTests(unittest.TestCase):
    def test_every_n_bars_gate(self) -> None:
        self.assertFalse(
            should_decide_on_bar(
                cadence=CADENCE_EVERY_N_BARS,
                bar_index=0,
                bar_ts="2024-01-01T00:00:00+00:00",
                every_n=5,
            )
        )
        self.assertTrue(
            should_decide_on_bar(
                cadence=CADENCE_EVERY_N_BARS,
                bar_index=5,
                bar_ts="2024-01-01T05:00:00+00:00",
                every_n=5,
            )
        )
        self.assertFalse(
            should_decide_on_bar(
                cadence=CADENCE_OFF,
                bar_index=5,
                bar_ts="2024-01-01T05:00:00+00:00",
                every_n=1,
            )
        )

    def test_daily_close_boundary(self) -> None:
        self.assertTrue(
            should_decide_on_bar(
                cadence=CADENCE_DAILY_CLOSE,
                bar_index=10,
                bar_ts="2024-01-02T00:00:00+00:00",
                previous_decision_ts="2024-01-01T23:00:00+00:00",
            )
        )
        self.assertFalse(
            should_decide_on_bar(
                cadence=CADENCE_DAILY_CLOSE,
                bar_index=11,
                bar_ts="2024-01-02T01:00:00+00:00",
                previous_decision_ts="2024-01-02T00:00:00+00:00",
            )
        )

    def test_async_decision_queue_causal(self) -> None:
        q = AsyncDecisionQueue()
        q.enqueue(
            AsyncDecisionRecord(
                decision_id="d1",
                as_of="2024-01-02T00:00:00+00:00",
                payload={"side": "buy"},
            )
        )
        q.enqueue(
            AsyncDecisionRecord(
                decision_id="d2",
                as_of="2024-01-05T00:00:00+00:00",
                payload={"side": "sell"},
            )
        )
        applied = q.apply_eligible(as_of="2024-01-03T00:00:00+00:00")
        self.assertEqual([r.decision_id for r in applied], ["d1"])
        self.assertEqual(len(q._pending), 1)
        self.assertTrue(q.public_dict()["truth"]["causal_as_of"])

    def test_create_run_records_cadence_no_default_agents(self) -> None:
        fixture = Path(__file__).resolve().parents[2] / "modules" / "market_sim" / "fixtures" / "BTCUSDT_1h_sample.csv"
        if not fixture.exists():
            # fall back to characterization fixture location
            fixture = Path(__file__).resolve().parents[1] / "fixtures" / "BTCUSDT_1h_sample.csv"
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            markets = root / "markets"
            markets.mkdir()
            # Use any available CSV from repo fixtures
            from Data.backend.tests.test_market_sim_characterization import FIXTURE

            dest = markets / "BTCUSDT_1h.csv"
            dest.write_bytes(FIXTURE.read_bytes())
            store = MarketSimStore(root / "lev.db")
            store.initialize()
            data = MarketDataStore(store, markets)
            plane = MarketSimControlPlane(store=store, data=data, enabled=True)
            sources = plane.scan_market_data()
            run = plane.create_run(source_id=sources[0]["source_id"])
            self.assertEqual(run["agents"], [])
            self.assertEqual(run["metadata"]["decision_cadence"], CADENCE_OFF)

            agents = [
                AgentConfig(
                    agent_id="a-trend",
                    role=AgentRole.TREND.value,
                    label="Trend",
                ).public_dict()
            ]
            run2 = plane.create_run(
                source_id=sources[0]["source_id"],
                agents=agents,
                deliberation_every_n=3,
                decision_cadence="every_n_bars",
            )
            self.assertEqual(len(run2["agents"]), 1)
            self.assertEqual(run2["metadata"]["decision_cadence"], "every_n_bars")
            self.assertEqual(run2["deliberation_every_n"], 3)


class P3AOrchestraExecutorGateTests(unittest.TestCase):
    def test_trading_orchestra_registers_fleet_executor(self) -> None:
        src = Path(__file__).resolve().parents[2] / "modules" / "market_sim" / "orchestra" / "service.py"
        text = src.read_text(encoding="utf-8")
        self.assertIn("register_kind_executor", text)
        self.assertIn("AgentDefinitionKind.TRADING", text)
        self.assertIn("DecisionRecord", open(
            Path(__file__).resolve().parents[2] / "modules" / "market_sim" / "orchestra" / "types.py",
            encoding="utf-8",
        ).read())


class P3BResearchCampaignTests(unittest.TestCase):
    def test_readiness_ladder_blocks_a5(self) -> None:
        from Data.modules.market_sim.readiness import readiness_ladder, normalize_autonomy
        from Data.modules.market_sim.types import MarketSimError

        ladder = readiness_ladder()
        self.assertEqual(ladder["A5"], "IMPOSSIBLE")
        self.assertEqual(ladder["live_trading"], "BLOCKED")
        self.assertEqual(ladder["ceiling"], "A4")
        with self.assertRaises(MarketSimError) as ctx:
            normalize_autonomy("A5")
        self.assertEqual(ctx.exception.code, "A5_IMPOSSIBLE")

    def test_scorecards_penalty_and_rank(self) -> None:
        from Data.modules.market_sim.scorecards import build_scorecard, rank_scorecards

        good = build_scorecard(agent_id="a", trials=5, wins=4, total_return=0.1, max_drawdown=0.05)
        bad = build_scorecard(
            agent_id="b",
            trials=5,
            wins=1,
            total_return=0.02,
            max_drawdown=0.3,
            causality_violations=2,
        )
        self.assertGreater(bad.penalty, 0)
        ranked = rank_scorecards([bad, good])
        self.assertEqual(ranked[0]["agent_id"], "a")
        self.assertEqual(ranked[0]["rank"], 1)

    def test_promotion_requires_acceptance_for_a2(self) -> None:
        from Data.modules.market_sim.promotion import evaluate_promotion
        from Data.modules.market_sim.readiness import may_promote_to

        blocked = evaluate_promotion(
            metrics={
                "trade_count": {"value": 0, "status": "MEASURED"},
                "total_return": {"value": -0.5, "status": "MEASURED"},
                "max_drawdown": {"value": 0.9, "status": "MEASURED"},
            },
            acceptance_criteria={"min_trades": 5, "max_drawdown_pct": 20.0, "min_total_return_pct": 0.0},
            current_level="A0",
            target_level="A2",
        )
        self.assertFalse(blocked["promotable"])
        self.assertEqual(blocked["live_trading"], "BLOCKED")

        # A0→A1 without resolved evidence is denied (no fabricated promotion).
        bare = evaluate_promotion(
            current_level="A0",
            target_level="A1",
            sealed_pass=False,
        )
        self.assertFalse(bare["promotable"])

        # Caller boolean alone cannot authorize A0→A4.
        jump = may_promote_to(current="A0", target="A4", evidence={"accepted": True})
        self.assertFalse(jump["allowed"])
        self.assertIn(jump.get("reason"), {
            "PROMOTION_STAGE_PREREQUISITES",
            "PROMOTION_REJECTS_CALLER_BOOLEAN",
        })

        ok = evaluate_promotion(
            metrics={
                "trade_count": {"value": 10, "status": "MEASURED"},
                "total_return_pct": {"value": 5.0, "status": "MEASURED"},
                "max_drawdown_pct": {"value": 2.0, "status": "MEASURED"},
            },
            acceptance_criteria={"min_trades": 5, "max_drawdown_pct": 20.0, "min_total_return_pct": 0.0},
            current_level="A0",
            target_level="A1",
        )
        self.assertTrue(ok["promotable"])
        self.assertTrue(ok["accepted"])

    def test_campaign_durable_resume_no_rewind(self) -> None:
        from Data.backend.tests.test_market_sim_characterization import FIXTURE
        from Data.modules.market_sim.types import MarketSimError

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            markets = root / "markets"
            markets.mkdir()
            dest = markets / "BTCUSDT_1h.csv"
            dest.write_bytes(FIXTURE.read_bytes())
            store = MarketSimStore(root / "lev.db")
            store.initialize()
            data = MarketDataStore(store, markets)
            plane = MarketSimControlPlane(store=store, data=data, enabled=True)
            sources = plane.scan_market_data()
            strat = plane.create_strategy(name="camp")
            created = plane.create_research_campaign(
                name="BTC strategy research",
                strategy_id=strat["strategy"]["strategy_id"],
                source_id=sources[0]["source_id"],
                max_iterations=3,
                autonomy_ceiling="A1",
            )
            self.assertEqual(created["status"], "CREATED")
            self.assertEqual(created["checkpoint_iteration"], 0)

            # Worker path runs without JobRuntime when called directly
            result = plane.run_research_campaign_on_worker(created["campaign_id"])
            self.assertIn(result["status"], {"COMPLETED", "FAILED"})
            self.assertEqual(result["checkpoint_iteration"], 3)
            self.assertEqual(len(result["trial_ids"]), 3)
            self.assertTrue(result["truth"]["no_rewind_on_crash"])
            iterations = result["results"].get("iterations") or []
            self.assertEqual(len(iterations), 3)
            # Trials must record real simulation attempts — never fabricated "recorded".
            for it in iterations:
                self.assertIn("simulation_executed", it)
            executed = [it for it in iterations if it.get("simulation_executed")]
            if result["status"] == "COMPLETED":
                self.assertGreaterEqual(len(executed), 1)
                self.assertNotEqual(
                    (result.get("scorecard") or {}).get("wins"),
                    len(result["trial_ids"]),
                    "wins must not equal all trials by fabrication",
                )
            # Scorecard must not claim fabricated zero-risk promotion inputs.
            measurement = (result.get("scorecard") or {}).get("measurement") or {}
            self.assertFalse(measurement.get("fabricated_zero_risk", True))

            # Simulate mid-run resume: seed checkpoint at 1 then continue
            mid = plane.get_research_campaign(created["campaign_id"])
            mid["status"] = "RUNNING"
            mid["checkpoint_iteration"] = 1
            mid["current_iteration"] = 1
            mid["trial_ids"] = mid["trial_ids"][:1]
            mid["results"] = {"iterations": [{"iteration": 1, "status": "ok"}]}
            mid["max_iterations"] = 3
            store.upsert_research_campaign(mid)
            resumed = plane.run_research_campaign_on_worker(created["campaign_id"])
            self.assertEqual(resumed["checkpoint_iteration"], 3)
            # Resume advanced from 1 → 3 (2 more), total trials grow
            self.assertGreaterEqual(len(resumed["trial_ids"]), 3)

            with self.assertRaises(MarketSimError) as ctx:
                plane.start_research_campaign(created["campaign_id"])  # no job_runtime
            self.assertEqual(ctx.exception.code, "TRADING_WORKER_UNAVAILABLE")

    def test_brain_as_of_gate_evidence(self) -> None:
        from Data.modules.market_sim.brain_hooks import BrainFacade

        class _Mem:
            def search(self, query: str, *, limit: int = 3) -> list[dict]:
                return [
                    {"id": "old", "created_at": "2020-01-01T00:00:00+00:00"},
                    {"id": "future", "created_at": "2099-01-01T00:00:00+00:00"},
                ]

        out = BrainFacade(memory=_Mem()).retrieve(
            "q", dependencies=["memory"], as_of="2024-01-01T00:00:00+00:00"
        )
        self.assertEqual([h["id"] for h in out.hits], ["old"])


if __name__ == "__main__":
    unittest.main()

