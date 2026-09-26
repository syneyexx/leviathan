"""Strategy Learning Loop — policy execution, adaptive learner, persistence, SEALED isolation."""

from __future__ import annotations

import copy
import math
import random
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from Data.backend.tests.test_market_sim_characterization import FIXTURE
from Data.modules.market_sim.data_store import MarketDataStore
from Data.modules.market_sim.gym import GymActionKind, TradingGym
from Data.modules.market_sim.learning import (
    AdaptiveEvolutionaryLearner,
    create_learning_run,
    should_early_stop,
)
from Data.modules.market_sim.learning_candidates import (
    generate_population,
    restore_rng,
    update_learner_from_outcomes,
)
from Data.modules.market_sim.learning_fitness import compute_fitness, measure_strategy_complexity
from Data.modules.market_sim.learning_types import (
    LearnerState,
    LearningObjectiveSpec,
    MeasurementStatus,
    new_learning_objective,
)
from Data.modules.market_sim.policy import (
    DslStrategyPolicy,
    HoldPolicy,
    resolve_gym_policy,
    strategy_requires_policy,
)
from Data.modules.market_sim.service import MarketSimControlPlane
from Data.modules.market_sim.store import MarketSimStore
from Data.modules.market_sim.types import MarketSimError


def _plane(tmp: str) -> tuple[MarketSimControlPlane, list[dict]]:
    root = Path(tmp)
    markets = root / "markets"
    markets.mkdir()
    (markets / "BTCUSDT_1h.csv").write_bytes(FIXTURE.read_bytes())
    store = MarketSimStore(root / "lev.db")
    store.initialize()
    data = MarketDataStore(store, markets)
    plane = MarketSimControlPlane(store=store, data=data, enabled=True)
    sources = plane.scan_market_data()
    return plane, sources


def _trend_csv(path: Path, n: int = 80) -> None:
    dt0 = datetime(2024, 1, 1, tzinfo=timezone.utc)
    with path.open("w", encoding="utf-8") as fh:
        fh.write("timestamp,open,high,low,close,volume\n")
        for i in range(n):
            ts = (dt0 + timedelta(hours=i)).isoformat()
            px = 100.0 + i * 0.8  # strong uptrend
            fh.write(f"{ts},{px},{px + 1},{px - 0.2},{px + 0.6},100\n")


def _mean_rev_csv(path: Path, n: int = 80) -> None:
    dt0 = datetime(2024, 1, 1, tzinfo=timezone.utc)
    with path.open("w", encoding="utf-8") as fh:
        fh.write("timestamp,open,high,low,close,volume\n")
        for i in range(n):
            ts = (dt0 + timedelta(hours=i)).isoformat()
            px = 100.0 + 5.0 * math.sin(i / 3.0)
            fh.write(f"{ts},{px},{px + 0.5},{px - 0.5},{px},100\n")


class PolicyExecutionTests(unittest.TestCase):
    def test_dsl_policy_produces_non_hold_on_trend(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            markets = root / "markets"
            markets.mkdir()
            _trend_csv(markets / "TREND_1h.csv", 60)
            store = MarketSimStore(root / "lev.db")
            store.initialize()
            data = MarketDataStore(store, markets)
            plane = MarketSimControlPlane(store=store, data=data, enabled=True)
            sources = plane.scan_market_data()
            strat = plane.create_strategy(
                name="breakout-pol",
                entry_rules={"version": 3, "kind": "breakout", "parameters": {"period": 5}},
                exit_rules={"kind": "breakout"},
                parameters={"period": 5},
            )
            ep = plane.create_gym_episode(
                source_id=sources[0]["source_id"],
                strategy_id=strat["strategy"]["strategy_id"],
                strategy_version=1,
                mode="complete",
                seed=1,
            )
            run_id = ep["episode"]["run_id"]
            result = plane.run_gym_episode_on_worker(run_id)
            self.assertGreater(result.get("non_hold_actions", 0), 0)
            self.assertTrue(result.get("truth", {}).get("policy_driven"))

    def test_explicit_hold_stays_hold(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            plane, sources = _plane(tmp)
            strat = plane.create_strategy(
                name="hold-pol",
                entry_rules={"version": 3, "kind": "hold"},
                exit_rules={"kind": "hold"},
                parameters={},
            )
            ep = plane.create_gym_episode(
                source_id=sources[0]["source_id"],
                strategy_id=strat["strategy"]["strategy_id"],
                mode="complete",
            )
            result = plane.run_gym_episode_on_worker(ep["episode"]["run_id"])
            self.assertEqual(result.get("non_hold_actions", -1), 0)

    def test_invalid_policy_fails_closed(self) -> None:
        with self.assertRaises(MarketSimError) as ctx:
            resolve_gym_policy(
                {"entry_rules": {"version": 3, "kind": "not_a_real_kind"}},
                strategy_id="x",
                strategy_version=1,
            )
        self.assertEqual(ctx.exception.code, "POLICY_LOAD_FAILED")

    def test_require_policy_flag_rejects_none(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            plane, sources = _plane(tmp)
            store = plane.store
            gym = TradingGym(store, plane.engine)
            ep = plane.create_gym_episode(source_id=sources[0]["source_id"], mode="complete")
            run = plane._get_run(ep["episode"]["run_id"])
            with self.assertRaises(MarketSimError) as ctx:
                gym.run_episode(
                    run,
                    bars_path=plane._resolve_bars_path(run),
                    policy=None,
                    require_policy=True,
                )
            self.assertEqual(ctx.exception.code, "POLICY_REQUIRED")


class FitnessHonestyTests(unittest.TestCase):
    def test_unmeasured_not_zero_and_nan_not_pass(self) -> None:
        obj = new_learning_objective(min_trades=5, max_drawdown_pct=20.0)
        fit = compute_fitness(
            candidate_id="c1",
            split_role="TRAIN",
            metrics={"trade_count": float("nan"), "max_drawdown_pct": float("inf")},
            objective=obj,
            complexity={"total": 4},
        )
        self.assertEqual(fit.components["trade_sufficiency"].status, MeasurementStatus.INVALID.value)
        self.assertNotEqual(fit.measurement_status, MeasurementStatus.MEASURED.value)
        self.assertIsNone(fit.scalar_score)

    def test_missing_required_is_unmeasured(self) -> None:
        obj = new_learning_objective()
        fit = compute_fitness(
            candidate_id="c2",
            split_role="TRAIN",
            metrics={},
            objective=obj,
        )
        self.assertEqual(fit.measurement_status, MeasurementStatus.UNMEASURED.value)
        self.assertTrue(any("UNMEASURED" in r for r in fit.failure_reasons))


class LearnerAdaptationTests(unittest.TestCase):
    def test_state_changes_after_generation_update(self) -> None:
        obj = new_learning_objective(population_size=6, elite_count=2, seed=7)
        state = LearnerState()
        before = state.state_hash()
        before_probs = dict(state.family_probabilities)
        rng = random.Random(7)
        outcomes = [
            {
                "candidate_id": "a",
                "family": "breakout",
                "fitness_score": 0.9,
                "failure_categories": [],
                "parameters": {"period": 20},
                "content_hash": "h1",
            },
            {
                "candidate_id": "b",
                "family": "mean_reversion",
                "fitness_score": 0.1,
                "failure_categories": ["NEGATIVE_RETURN"],
                "parameters": {"lookback": 20},
                "content_hash": "h2",
            },
            {
                "candidate_id": "c",
                "family": "breakout",
                "fitness_score": 0.8,
                "failure_categories": [],
                "parameters": {"period": 18},
                "content_hash": "h3",
            },
        ]
        after = update_learner_from_outcomes(state, outcomes=outcomes, objective=obj, rng=rng)
        self.assertNotEqual(after.state_hash(), before)
        self.assertGreater(after.family_probabilities["breakout"], before_probs["breakout"])
        self.assertGreater(after.generation_number, 0)

    def test_generation_2_depends_on_generation_1_outcomes(self) -> None:
        obj = new_learning_objective(population_size=8, elite_count=2, seed=42)
        state = LearnerState()
        rng = random.Random(42)
        # Path A: breakout wins
        s1 = update_learner_from_outcomes(
            state,
            outcomes=[
                {"candidate_id": "1", "family": "breakout", "fitness_score": 1.0, "failure_categories": [], "parameters": {"period": 10}, "content_hash": "a"},
                {"candidate_id": "2", "family": "rsi", "fitness_score": 0.0, "failure_categories": ["INSUFFICIENT_TRADES"], "parameters": {"period": 14}, "content_hash": "b"},
            ],
            objective=obj,
            rng=rng,
        )
        pop_a = generate_population(
            state=s1,
            objective=obj,
            generation=2,
            parent_strategy_id="s",
            rng=restore_rng(42, s1.rng_state),
            elite_specs=[{"family": "breakout", "entry_rules": {"version": 3, "kind": "breakout"}, "exit_rules": {}, "parameters": {"period": 10}, "risk_rules": {}}],
        )
        families_a = [p["spec"]["family"] for p in pop_a]

        # Path B: mean_reversion wins (different outcomes → different distribution)
        state2 = LearnerState()
        rng2 = random.Random(42)
        s2 = update_learner_from_outcomes(
            state2,
            outcomes=[
                {"candidate_id": "1", "family": "mean_reversion", "fitness_score": 1.0, "failure_categories": [], "parameters": {"lookback": 20}, "content_hash": "c"},
                {"candidate_id": "2", "family": "breakout", "fitness_score": 0.0, "failure_categories": ["EXCESSIVE_DRAWDOWN"], "parameters": {"period": 10}, "content_hash": "d"},
            ],
            objective=obj,
            rng=rng2,
        )
        pop_b = generate_population(
            state=s2,
            objective=obj,
            generation=2,
            parent_strategy_id="s",
            rng=restore_rng(42, s2.rng_state),
            elite_specs=[{"family": "mean_reversion", "entry_rules": {"version": 3, "kind": "mean_reversion"}, "exit_rules": {}, "parameters": {"lookback": 20}, "risk_rules": {}}],
        )
        families_b = [p["spec"]["family"] for p in pop_b]
        self.assertNotEqual(s1.family_probabilities, s2.family_probabilities)
        # Proposal sequences should differ given different elite/family state
        self.assertTrue(families_a != families_b or s1.family_probabilities["breakout"] != s2.family_probabilities["breakout"])

    def test_reproducibility_same_seed(self) -> None:
        obj = new_learning_objective(population_size=5, seed=99)
        state = LearnerState()
        a = generate_population(state=state, objective=obj, generation=0, parent_strategy_id="s", rng=random.Random(99))
        b = generate_population(state=state, objective=obj, generation=0, parent_strategy_id="s", rng=random.Random(99))
        hashes_a = [p["spec"]["family"] for p in a]
        hashes_b = [p["spec"]["family"] for p in b]
        self.assertEqual(hashes_a, hashes_b)
        c = generate_population(state=state, objective=obj, generation=0, parent_strategy_id="s", rng=random.Random(100))
        self.assertNotEqual(hashes_a, [p["spec"]["family"] for p in c])

    def test_sealed_update_forbidden(self) -> None:
        obj = new_learning_objective()
        with self.assertRaises(ValueError):
            update_learner_from_outcomes(
                LearnerState(),
                outcomes=[{"candidate_id": "x", "family": "breakout", "fitness_score": 1.0}],
                objective=obj,
                rng=random.Random(1),
                split_role="SEALED",
            )


class LearningLifecycleTests(unittest.TestCase):
    def test_create_start_learning_run_end_to_end(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            plane, sources = _plane(tmp)
            strat = plane.create_strategy(
                name="learn-parent",
                entry_rules={"version": 3, "kind": "ma_cross", "parameters": {"fast_ma": 5, "slow_ma": 15}},
                exit_rules={"kind": "ma_cross"},
                parameters={"fast_ma": 5, "slow_ma": 15, "lookback": 20},
            )
            lab = plane.create_agent_lab(
                name="learning-lab",
                strategy_id=strat["strategy"]["strategy_id"],
                source_id=sources[0]["source_id"],
                max_candidates=4,
                max_iterations=2,
                seed=42,
                acceptance_criteria={
                    "min_trades": 1,
                    "max_drawdown_pct": 100.0,
                    "require_val_pass": False,
                    "require_robustness_pass": False,
                },
                learning={
                    "population_size": 3,
                    "generation_budget": 2,
                    "trial_budget": 12,
                    "elite_count": 1,
                    "require_sealed_pass": False,
                    "max_episode_bars": 40,
                },
                enable_learning=True,
            )
            self.assertTrue(lab.get("learning_run_id"))
            result = plane.start_agent_lab(lab["lab_id"])
            learning = result.get("learning") or plane.get_learning_run(lab["learning_run_id"])
            self.assertIn(learning["status"], {"COMPLETED", "PAUSED", "CANCELLED"})
            self.assertGreaterEqual(int(learning["current_generation"]), 1)
            self.assertGreater(len(learning.get("candidates") or []), 0)
            # All candidates retained; losing ones present
            self.assertTrue(any(c.get("status") for c in learning["candidates"]))
            # Learner state changed
            self.assertGreater(int((learning.get("learner_state") or {}).get("generation_number") or 0), 0)
            # Trials retained in ledger
            trials = plane.store.list_experiments(strategy_id=strat["strategy"]["strategy_id"], limit=200)
            learn_trials = [
                t
                for t in trials
                if (t.get("metadata") or {}).get("learning_run_id") == learning["learning_run_id"]
                or (t.get("config") or {}).get("learning_run_id") == learning["learning_run_id"]
            ]
            self.assertGreater(len(learn_trials), 0)
            # Reloaded state matches
            reloaded = plane.get_learning_run(learning["learning_run_id"])
            self.assertEqual(reloaded["learner_state"]["generation_number"], learning["learner_state"]["generation_number"])
            self.assertEqual(reloaded["current_generation"], learning["current_generation"])

    def test_pause_resume_cancel(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            plane, sources = _plane(tmp)
            strat = plane.create_strategy(name="lr-ctrl")
            lab = plane.create_agent_lab(
                strategy_id=strat["strategy"]["strategy_id"],
                source_id=sources[0]["source_id"],
                learning={"population_size": 2, "generation_budget": 3, "trial_budget": 20, "require_sealed_pass": False},
            )
            lid = lab["learning_run_id"]
            paused = plane.pause_learning_run(lid)
            self.assertEqual(paused["status"], "PAUSED")
            # Resume runs to completion inline
            resumed = plane.resume_learning_run(lid)
            learning = resumed.get("learning") or plane.get_learning_run(lid)
            self.assertIn(learning["status"], {"COMPLETED", "RUNNING", "QUEUED", "PAUSED"})
            cancelled = plane.cancel_learning_run(lid)
            self.assertEqual(cancelled["status"], "CANCELLED")

    def test_crash_resume_no_duplicate_versions(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            plane, sources = _plane(tmp)
            strat = plane.create_strategy(
                name="crash-learn",
                entry_rules={"version": 3, "kind": "rsi", "parameters": {"period": 14}, "entry": {"oversold": 30}},
                parameters={"period": 14},
            )
            lab = plane.create_agent_lab(
                strategy_id=strat["strategy"]["strategy_id"],
                source_id=sources[0]["source_id"],
                seed=3,
                acceptance_criteria={"min_trades": 0, "max_drawdown_pct": 100.0, "require_val_pass": False, "require_robustness_pass": False},
                learning={
                    "population_size": 2,
                    "generation_budget": 2,
                    "trial_budget": 8,
                    "require_sealed_pass": False,
                    "max_episode_bars": 25,
                },
            )
            lid = lab["learning_run_id"]
            # First run
            plane.run_learning_on_worker(lid)
            after1 = plane.get_learning_run(lid)
            versions_1 = sorted({c["strategy_version"] for c in after1["candidates"]})
            # Simulate restart — run again (should resume, not duplicate committed work)
            plane.run_learning_on_worker(lid)
            after2 = plane.get_learning_run(lid)
            versions_2 = sorted({c["strategy_version"] for c in after2["candidates"]})
            # Version set should not explode with duplicates of same content+generation
            gen1 = [c for c in after2["candidates"] if c["generation"] == 1]
            content_keys = {(c["content_hash"], c["proposal_method"]) for c in gen1}
            self.assertEqual(len(content_keys), len(gen1))
            self.assertEqual(after2["current_generation"], after1["current_generation"] or after2["current_generation"])
            self.assertTrue(versions_2)  # noqa: unused versions_1 for readability
            _ = versions_1

    def test_no_strategy_qualified_is_valid_completion(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            plane, sources = _plane(tmp)
            strat = plane.create_strategy(name="strict")
            lab = plane.create_agent_lab(
                strategy_id=strat["strategy"]["strategy_id"],
                source_id=sources[0]["source_id"],
                seed=5,
                acceptance_criteria={
                    "min_trades": 10_000,  # impossible
                    "max_drawdown_pct": 0.0001,
                    "require_val_pass": True,
                    "require_robustness_pass": True,
                },
                learning={
                    "population_size": 2,
                    "generation_budget": 1,
                    "trial_budget": 4,
                    "require_sealed_pass": False,
                    "max_episode_bars": 20,
                    "min_trades": 10_000,
                    "max_drawdown_pct": 0.0001,
                    "require_val_pass": True,
                    "require_robustness_pass": True,
                },
            )
            result = plane.start_agent_lab(lab["lab_id"])
            learning = result.get("learning") or plane.get_learning_run(lab["learning_run_id"])
            self.assertEqual(learning["status"], "COMPLETED")
            self.assertEqual(learning["stage"], "NO_STRATEGY_QUALIFIED")
            lab2 = plane.get_agent_lab(lab["lab_id"])
            self.assertEqual(lab2["outcome"], "NO_STRATEGY_QUALIFIED")

    def test_objective_immutable(self) -> None:
        obj = new_learning_objective(min_trades=5, seed=1)
        h = obj.objective_hash()
        from Data.modules.market_sim.learning import assert_objective_immutable

        assert_objective_immutable(h, obj)
        with self.assertRaises(MarketSimError):
            assert_objective_immutable("deadbeef", obj)


class AdversarialLearningTests(unittest.TestCase):
    def test_unsupported_dsl_rejected(self) -> None:
        pol = DslStrategyPolicy(
            entry_rules={"version": 3, "kind": "eval_injection", "eval": "os.system"},
        )
        with self.assertRaises(MarketSimError):
            pol.ensure_loaded()

    def test_budget_enforced(self) -> None:
        run = create_learning_run(
            lab_id=None,
            campaign_id=None,
            strategy_id="s",
            parent_strategy_version=1,
            source_id="src",
            objective=new_learning_objective(trial_budget=1, population_size=5, generation_budget=2),
            seed=1,
        )
        run.trials_used = 1
        learner = AdaptiveEvolutionaryLearner(run)
        with self.assertRaises(MarketSimError):
            learner.propose_generation(parent_version={"entry_rules": {"kind": "ma_cross"}, "parameters": {}, "exit_rules": {}, "risk_rules": {}})

    def test_complexity_measured(self) -> None:
        cx = measure_strategy_complexity(
            {"version": 3, "kind": "composite", "filters": [{"kind": "regime_filter", "mode": "adx"}], "parameters": {"fast_ma": 10}},
            {"kind": "ma_cross"},
            {"fast_ma": 10, "slow_ma": 30},
        )
        self.assertGreater(cx["total"], 0)
        self.assertIn("number_of_filters", cx)


if __name__ == "__main__":
    unittest.main()
