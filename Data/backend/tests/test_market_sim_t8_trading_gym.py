"""T8 — TradingGym, scorecards, readiness ladder, trajectory export, sim-real gap."""

from __future__ import annotations

import inspect
import tempfile
import unittest
from pathlib import Path

from Data.backend.migrations import MIGRATIONS
from Data.modules.market_sim.data_store import MarketDataStore
from Data.modules.market_sim.gym import (
    CURRICULUM_STAGES,
    assert_not_sealed_dataset,
    can_enter_curriculum_stage,
    curriculum_catalog,
    load_gym_from_path,
    new_episode_spec,
)
from Data.modules.market_sim.multi_engine import MultiAgentEngine
from Data.modules.market_sim.scorecards import (
    build_agent_scorecard,
    can_advance_readiness,
    leaderboard_with_penalty,
    parse_readiness_level,
)
from Data.modules.market_sim.service import MarketSimControlPlane
from Data.modules.market_sim.sim_real_gap import compute_sim_real_gap
from Data.modules.market_sim.store import MarketSimStore, utc_now
from Data.modules.market_sim.trajectory_export import (
    build_trajectory_records,
    contamination_scan,
    export_trajectories_jsonl,
)
from Data.modules.market_sim.types import MarketSimError


FIXTURE = Path(__file__).resolve().parent / "fixtures" / "market_data" / "BTCUSDT_1h.csv"


class TradingGymTests(unittest.TestCase):
    def test_reset_step_deterministic(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = MarketSimStore(Path(tmp) / "db.sqlite")
            store.initialize()
            spec = new_episode_spec(
                bars_path=str(FIXTURE),
                curriculum_stage="trend",
                seed=7,
                end_index=30,
                created_at=utc_now(),
            )
            gym_a = load_gym_from_path(spec, store=store)
            gym_b = load_gym_from_path(spec, store=store)
            obs_a = gym_a.reset()
            obs_b = gym_b.reset()
            self.assertEqual(obs_a.as_of, obs_b.as_of)
            rewards_a = []
            rewards_b = []
            for action in ("BUY", "HOLD", "SELL", "HOLD", "FLAT"):
                ra = gym_a.step(action)
                rb = gym_b.step(action)
                rewards_a.append(ra.reward)
                rewards_b.append(rb.reward)
            self.assertEqual(rewards_a, rewards_b)
            self.assertTrue(obs_a.truth if hasattr(obs_a, "truth") else True)
            ep = gym_a.episode_public_dict()
            self.assertTrue(ep["truth"]["reward_from_kernel"])
            self.assertTrue(ep["truth"]["sealed_unreachable"])

    def test_sealed_dataset_unreachable(self) -> None:
        with self.assertRaises(MarketSimError) as ctx:
            assert_not_sealed_dataset({"sealed": True, "role": "SEALED_TEST"})
        self.assertEqual(ctx.exception.code, "SEALED_WINDOW_UNREACHABLE")
        with self.assertRaises(MarketSimError):
            new_episode_spec(
                bars_path=str(FIXTURE),
                created_at=utc_now(),
                dataset={"sealed": False, "role": "SEALED_HOLDOUT"},
            )

    def test_curriculum_gating(self) -> None:
        self.assertTrue(can_enter_curriculum_stage(None, "trend"))
        self.assertFalse(can_enter_curriculum_stage(None, "stress"))
        self.assertTrue(can_enter_curriculum_stage("trend", "mean_reversion"))
        self.assertFalse(can_enter_curriculum_stage("trend", "adversarial"))
        self.assertEqual(len(curriculum_catalog()), len(CURRICULUM_STAGES))

    def test_domain_randomization_varies_by_stage(self) -> None:
        from Data.modules.market_sim.gym import DomainRandomization

        mild = DomainRandomization.sample(1, stage="trend")
        stress = DomainRandomization.sample(1, stage="stress")
        self.assertGreater(stress.fee_bps, mild.fee_bps)

    def test_service_episode_lifecycle(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            markets = root / "markets"
            markets.mkdir()
            store = MarketSimStore(root / "db.sqlite")
            store.initialize()
            data = MarketDataStore(store, markets)
            svc = MarketSimControlPlane(store, data, enabled=True)
            created = svc.create_gym_episode(
                bars_path=str(FIXTURE),
                curriculum_stage="trend",
                seed=3,
                end_index=15,
            )
            eid = created["episode"]["episode_id"]
            self.assertEqual(created["episode"]["status"], "running")
            stepped = svc.gym_step(eid, action="BUY")
            self.assertIn("reward", stepped)
            # Drive to completion
            while True:
                ep = svc.get_gym_episode(eid)
                if ep["status"] == "completed":
                    break
                svc.gym_step(eid, action="HOLD")
            self.assertEqual(svc.get_gym_episode(eid)["status"], "completed")


class ScorecardReadinessTests(unittest.TestCase):
    def test_scorecard_has_sharpe_and_cis(self) -> None:
        equity = [100.0]
        for i in range(1, 40):
            equity.append(equity[-1] * (1.0 + (0.01 if i % 3 else -0.005)))
        card = build_agent_scorecard(
            agent_id="agent-a",
            equity=equity,
            regime="trend",
            year=2024,
            violations={"risk_rejections": 1, "override_attempts": 0, "causality_attempts": 0},
            created_at=utc_now(),
        )
        payload = card.public_dict()
        self.assertIn("sharpe", payload)
        self.assertIn("max_drawdown", payload)
        self.assertIn("bootstrap", payload)
        self.assertEqual(payload["violations"]["risk_rejections"], 1)

    def test_leaderboard_penalty(self) -> None:
        rows = [
            {
                "agent_id": "strong",
                "equity": 120.0,
                "sharpe": {"status": "MEASURED", "value": 2.5},
                "equity_points": 80,
            },
            {
                "agent_id": "weak",
                "equity": 110.0,
                "sharpe": {"status": "MEASURED", "value": 0.05},
                "equity_points": 80,
            },
        ]
        ranked = leaderboard_with_penalty(rows, q=0.05)
        self.assertEqual(len(ranked), 2)
        self.assertIn("multiple_testing_penalty", ranked[0])
        self.assertIn("adjusted_p", ranked[0])

    def test_leaderboard_source_includes_sharpe(self) -> None:
        src = inspect.getsource(MultiAgentEngine._leaderboard)
        self.assertIn("sharpe", src.lower())
        self.assertIn("max_drawdown", src.lower())
        self.assertIn("leaderboard_with_penalty", src)

    def test_readiness_ladder_a5_blocked(self) -> None:
        with self.assertRaises(MarketSimError) as ctx:
            parse_readiness_level("A5")
        self.assertEqual(ctx.exception.code, "READINESS_A5_BLOCKED")
        decision = can_advance_readiness("A0", "A1", evidence={"measurement": "UNMEASURED"})
        self.assertFalse(decision["allowed"])
        self.assertIn("UNMEASURED_blocks_advancement", decision["reasons"])
        ok = can_advance_readiness("A0", "A1", evidence={"measurement": "MEASURED"})
        self.assertTrue(ok["allowed"])
        skip = can_advance_readiness("A0", "A3", evidence={"measurement": "MEASURED"})
        self.assertFalse(skip["allowed"])

    def test_service_readiness_and_scorecard(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            store = MarketSimStore(root / "db.sqlite")
            store.initialize()
            data = MarketDataStore(store, root / "markets")
            (root / "markets").mkdir()
            svc = MarketSimControlPlane(store, data, enabled=True)
            card = svc.create_agent_scorecard(
                agent_id="a1",
                equity=[100, 101, 102, 101, 103, 104],
                regime="mixed",
            )
            self.assertEqual(card["agent_id"], "a1")
            listed = svc.list_agent_scorecards(agent_id="a1")
            self.assertEqual(len(listed), 1)
            with self.assertRaises(MarketSimError):
                svc.set_agent_readiness("a1", level="A5")
            advanced = svc.set_agent_readiness(
                "a1", level="A1", measurement="MEASURED", reason="gym pass"
            )
            self.assertEqual(advanced["level"], "A1")


class TrajectoryExportTests(unittest.TestCase):
    def test_contamination_blocks_sealed(self) -> None:
        records = [{"as_of": "2024-06-01T00:00:00+00:00", "action": "BUY"}]
        scan = contamination_scan(
            records,
            sealed_windows=[
                {
                    "start_ts": "2024-01-01T00:00:00+00:00",
                    "end_ts": "2024-12-31T00:00:00+00:00",
                    "role": "SEALED_TEST",
                }
            ],
        )
        self.assertTrue(scan["contaminated"])

    def test_export_verified_only(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            store = MarketSimStore(root / "db.sqlite")
            store.initialize()
            data = MarketDataStore(store, root / "markets")
            (root / "markets").mkdir()
            svc = MarketSimControlPlane(store, data, enabled=True)
            created = svc.create_gym_episode(
                bars_path=str(FIXTURE), seed=1, end_index=8, curriculum_stage="trend"
            )
            eid = created["episode"]["episode_id"]
            with self.assertRaises(MarketSimError):
                svc.export_gym_trajectory(eid)
            while svc.get_gym_episode(eid)["status"] != "completed":
                svc.gym_step(eid, action="HOLD")
            exported = svc.export_gym_trajectory(
                eid, dest_path=str(root / "exports")
            )
            self.assertGreater(exported["record_count"], 0)
            self.assertTrue(Path(exported["path"]).is_file())
            self.assertFalse(exported["contamination"]["contaminated"])


class SimRealGapTests(unittest.TestCase):
    def test_gap_report_foundation(self) -> None:
        report = compute_sim_real_gap(
            sim_fills=[
                {"client_order_id": "c1", "side": "BUY", "ts": "t1", "price": 100.0, "slippage": 0.1},
                {"client_order_id": "c2", "side": "SELL", "ts": "t2", "price": 101.0, "slippage": 0.1},
            ],
            paper_fills=[
                {"client_order_id": "c1", "side": "BUY", "ts": "t1", "price": 100.5, "slippage": 0.2},
            ],
            calibration_source_ids=["cal-1"],
            evaluation_source_ids=["eval-1"],
            created_at=utc_now(),
        )
        self.assertEqual(report["matched_fills"], 1)
        self.assertEqual(report["missed_in_paper"], 1)
        self.assertAlmostEqual(report["fill_price_delta_mean"], 0.5)
        self.assertTrue(report["truth"]["calibration_disjoint_from_evaluation"])
        self.assertTrue(report["truth"]["sim_to_real_gap"])

    def test_service_persists_gap(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            store = MarketSimStore(root / "db.sqlite")
            store.initialize()
            data = MarketDataStore(store, root / "markets")
            (root / "markets").mkdir()
            svc = MarketSimControlPlane(store, data, enabled=True)
            report = svc.create_sim_real_gap_report(
                sim_fills=[{"client_order_id": "x", "side": "BUY", "ts": "t", "price": 1.0}],
                paper_fills=[{"client_order_id": "x", "side": "BUY", "ts": "t", "price": 1.1}],
            )
            self.assertIn("report_id", report)


class Migration48Tests(unittest.TestCase):
    def test_migration_48_present(self) -> None:
        head = MIGRATIONS[-1].version
        self.assertGreaterEqual(head, 48)
        by_ver = {m.version: m.name for m in MIGRATIONS}
        self.assertEqual(by_ver[48], "trading_gym_scorecards")


if __name__ == "__main__":
    unittest.main()
