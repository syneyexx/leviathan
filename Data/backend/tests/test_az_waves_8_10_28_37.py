"""A–Z Waves 8–10 / 37: learning lifecycle, novelty, grammar structure, paper lineage."""

from __future__ import annotations

import random
import tempfile
import unittest
from pathlib import Path
from unittest import mock
from unittest.mock import MagicMock

from Data.modules.market_sim.data_store import MarketDataStore
from Data.modules.market_sim.experiments import build_strategy_memory_record
from Data.modules.market_sim.learning import init_learner_priors
from Data.modules.market_sim.learning_candidates import generate_population, mutate_spec
from Data.modules.market_sim.learning_memory import LearningEpistemicState
from Data.modules.market_sim.learning_types import LearnerState, new_learning_objective
from Data.modules.market_sim.lesson_retrieval import (
    LESSON_LIFECYCLE_STATES,
    retrieve_prior_lessons_for_generation,
)
from Data.modules.market_sim.service import MarketSimControlPlane
from Data.modules.market_sim.store import MarketSimStore
from Data.modules.market_sim.strategy_search_grammar import (
    STRUCTURAL_PRIMITIVE_IDS,
    SearchPrimitive,
    build_structure_for_family,
    generate_hypothesis_candidate,
    list_primitives,
    measure_candidate_novelty,
)
from Data.modules.market_sim.types import StrategyRecord, StrategyStatus, StrategyVersion


class LessonLifecycleWave8Tests(unittest.TestCase):
    def test_lifecycle_states_cover_required_set(self) -> None:
        required = {
            "PROPOSED",
            "OBSERVED",
            "MEASURED",
            "REPLICATED",
            "VERIFIED",
            "REJECTED",
            "SUPERSEDED",
        }
        self.assertEqual(set(LESSON_LIFECYCLE_STATES), required)
        self.assertEqual(set(LESSON_LIFECYCLE_STATES), {s.value for s in LearningEpistemicState})

    def test_prior_lessons_preserve_lifecycle_on_metadata(self) -> None:
        class _Store:
            def get_agent_lab(self, lab_id):
                return {
                    "lessons": [
                        {
                            "lesson_id": "l-proposed",
                            "claim": "proposed edge",
                            "trust": "AGENT_PROPOSED",
                            "applies_to": ["BTCUSD"],
                            "available_at": "2024-01-01T00:00:00+00:00",
                            "confidence": 0.3,
                        },
                        {
                            "lesson_id": "l-measured",
                            "claim": "measured cost failure",
                            "epistemic_state": "MEASURED",
                            "applies_to": ["BTCUSD"],
                            "available_at": "2024-01-02T00:00:00+00:00",
                            "confidence": 0.6,
                            "rejected": True,
                        },
                    ]
                }

            def list_strategy_memories(self, **kwargs):
                return [
                    build_strategy_memory_record(
                        strategy_id="s1",
                        strategy_version=1,
                        outcome_summary="replicated regime failure",
                        rejected=True,
                        available_at="2024-01-03T00:00:00+00:00",
                        origin="test",
                        epistemic_state="REPLICATED",
                        applicability={"applies_to": ["BTCUSD"]},
                    ),
                    build_strategy_memory_record(
                        strategy_id="s2",
                        strategy_version=1,
                        outcome_summary="verified postmortem",
                        rejected=False,
                        available_at="2024-01-04T00:00:00+00:00",
                        origin="test",
                        epistemic_state="VERIFIED",
                        applicability={"applies_to": ["BTCUSD"]},
                    ),
                    build_strategy_memory_record(
                        strategy_id="s3",
                        strategy_version=1,
                        outcome_summary="superseded under old costs",
                        rejected=True,
                        available_at="2024-01-05T00:00:00+00:00",
                        origin="test",
                        epistemic_state="SUPERSEDED",
                        applicability={"applies_to": ["BTCUSD"]},
                    ),
                    build_strategy_memory_record(
                        strategy_id="s4",
                        strategy_version=1,
                        outcome_summary="paper observed drift",
                        rejected=False,
                        available_at="2024-01-06T00:00:00+00:00",
                        origin="test",
                        epistemic_state="OBSERVED",
                        applicability={"applies_to": ["BTCUSD"]},
                    ),
                ]

        class _Run:
            lab_id = "lab-1"
            learning_run_id = "lr-1"
            metadata = {"symbols": ["BTCUSD"]}

        lessons = retrieve_prior_lessons_for_generation(
            mock.Mock(store=_Store()),
            _Run(),
            perception={"symbols": ["BTCUSD"], "as_of": "2024-06-01T00:00:00+00:00"},
            as_of="2024-06-01T00:00:00+00:00",
            limit=12,
        )
        states = {str(L.get("lifecycle_state") or L.get("epistemic_state")) for L in lessons}
        for required in ("PROPOSED", "MEASURED", "REPLICATED", "VERIFIED", "SUPERSEDED", "OBSERVED"):
            self.assertIn(required, states)
        for lesson in lessons:
            self.assertEqual(lesson["lifecycle_state"], lesson["metadata"]["lifecycle_state"])
            self.assertIn(lesson["lifecycle_state"], LESSON_LIFECYCLE_STATES)

    def test_memory_record_canonicalizes_legacy_agent_proposed(self) -> None:
        row = build_strategy_memory_record(
            strategy_id="s",
            strategy_version=1,
            outcome_summary="x",
            rejected=False,
            available_at="2024-01-01T00:00:00+00:00",
            origin="test",
            epistemic_state="AGENT_PROPOSED",
        )
        # Specialized token preserved; canonical lifecycle is PROPOSED.
        self.assertEqual(row["metadata"]["epistemic_state"], "AGENT_PROPOSED")
        self.assertEqual(row["metadata"]["lifecycle_state"], "PROPOSED")


class NoveltyExplorationWave9Tests(unittest.TestCase):
    def test_population_exposes_novelty_and_uses_exploration_rate(self) -> None:
        obj = new_learning_objective(population_size=12, elite_count=1, seed=7, exploration_rate=0.5)
        state = LearnerState(exploration_rate=0.5)
        elite = {
            "family": "ma_cross",
            "entry_rules": {
                "version": 3,
                "kind": "ma_cross",
                "parameters": {"fast_ma": 5, "slow_ma": 20},
            },
            "exit_rules": {"kind": "ma_cross"},
            "parameters": {"fast_ma": 5, "slow_ma": 20},
            "risk_rules": {"max_position_pct": 25, "stop_loss": {"pct": 0.05}},
        }
        pop = generate_population(
            state=state,
            objective=obj,
            generation=1,
            parent_strategy_id="parent",
            rng=random.Random(7),
            elite_specs=[elite],
        )
        self.assertEqual(len(pop), 12)
        explore = [p for p in pop if p.get("method") == "EXPLORATION"]
        self.assertGreaterEqual(len(explore), 4)
        for item in pop:
            self.assertIn("novelty", item)
            self.assertIn("structural_novelty", item)
            self.assertIn("parameter_novelty", item)
            self.assertEqual(item["exploration_rate"], 0.5)
            self.assertGreaterEqual(float(item["structural_novelty"]), 0.0)
            self.assertLessEqual(float(item["structural_novelty"]), 1.0)

    def test_rejected_lessons_influence_but_supersedable_under_new_costs(self) -> None:
        rejected = {
            "claim": "breakout fails under high fees",
            "trust": "REJECTED",
            "rejected": True,
            "applies_to": ["breakout"],
            "confidence": 0.9,
            "cost_assumptions": {"fee_bps": 10, "slippage_bps": 5},
        }
        under_old = init_learner_priors(
            lessons=[rejected],
            cost_assumptions={"fee_bps": 10, "slippage_bps": 5},
            exploration_rate=0.2,
        )
        self.assertLess(under_old.lesson_priors.get("breakout", 0), 0)

        under_new = init_learner_priors(
            lessons=[rejected],
            cost_assumptions={"fee_bps": 1, "slippage_bps": 1},
            exploration_rate=0.2,
        )
        self.assertNotIn("breakout", under_new.lesson_priors)

        superseded = dict(rejected)
        superseded["trust"] = "SUPERSEDED"
        superseded["epistemic_state"] = "SUPERSEDED"
        after_super = init_learner_priors(
            lessons=[superseded],
            cost_assumptions={"fee_bps": 10, "slippage_bps": 5},
        )
        self.assertNotIn("breakout", after_super.lesson_priors)

    def test_measure_candidate_novelty_structural_vs_parameter(self) -> None:
        base = generate_hypothesis_candidate(family="momentum", perception={"regime": "trend"})
        twin = generate_hypothesis_candidate(family="momentum", perception={"regime": "trend"})
        twin.parameters = dict(base.parameters)
        twin.entry_rules = dict(base.entry_rules)
        twin.exit_rules = dict(base.exit_rules)
        twin.risk_rules = dict(base.risk_rules)
        twin.family = base.family
        same = measure_candidate_novelty(twin, reference_pool=[base.public_dict()])
        self.assertLessEqual(same["structural_novelty"], 0.35)

        structural = generate_hypothesis_candidate(family="mean_reversion", perception={"regime": "chop"})
        structural.entry_rules = {
            **dict(structural.entry_rules),
            "horizon": "multi_day",
            "features": ["returns", "volatility"],
            "stop_loss": {"pct": 0.12},
        }
        structural.exit_rules = {
            **dict(structural.exit_rules),
            "mode": "time_stop",
            "horizon": "multi_day",
        }
        distinct = measure_candidate_novelty(structural, reference_pool=[base.public_dict()])
        self.assertGreater(distinct["structural_novelty"], same["structural_novelty"])


class GrammarStructuralWave10Tests(unittest.TestCase):
    def test_structural_primitives_exist(self) -> None:
        ids = {p["id"] for p in list_primitives()}
        for required in ("entry", "exit", "stop", "horizon", "features"):
            self.assertIn(required, ids)
            self.assertIn(required, STRUCTURAL_PRIMITIVE_IDS)
        structure = build_structure_for_family("rsi")
        prims = {n.primitive for n in structure.nodes}
        self.assertIn(SearchPrimitive.ENTRY, prims)
        self.assertIn(SearchPrimitive.EXIT, prims)
        self.assertIn(SearchPrimitive.STOP, prims)
        self.assertIn(SearchPrimitive.HORIZON, prims)
        self.assertIn(SearchPrimitive.FEATURES, prims)

    def test_hypothesis_varies_entry_exit_stop_horizon_features(self) -> None:
        hyp = generate_hypothesis_candidate(family="breakout", perception={"regime": "trend_up"})
        self.assertIn("horizon", hyp.entry_rules)
        self.assertIn("features", hyp.entry_rules)
        self.assertIn("stop_loss", hyp.entry_rules)
        self.assertIn("horizon", hyp.exit_rules)
        self.assertEqual(hyp.metadata.get("structural_primitives"), list(STRUCTURAL_PRIMITIVE_IDS))

    def test_mutate_spec_can_change_exit_horizon_features(self) -> None:
        state = LearnerState(
            mutation_rates={
                "numeric": 0.0,
                "categorical": 0.0,
                "structure": 0.0,
                "feature": 0.0,
                "risk": 0.0,
                "exit": 1.0,
                "horizon": 1.0,
                "features": 1.0,
            }
        )
        base = {
            "family": "ma_cross",
            "entry_rules": {
                "version": 3,
                "kind": "ma_cross",
                "parameters": {"fast_ma": 5, "slow_ma": 20},
            },
            "exit_rules": {"kind": "ma_cross"},
            "parameters": {"fast_ma": 5, "slow_ma": 20},
            "risk_rules": {"max_position_pct": 25},
        }
        mutated, ops = mutate_spec(base, rng=random.Random(3), state=state)
        self.assertTrue({"MODIFY_EXIT", "REPLACE_FEATURE"} & set(ops))
        self.assertIn("horizon", mutated["entry_rules"])
        self.assertIn("features", mutated["entry_rules"])
        self.assertIn("mode", mutated["exit_rules"])


def _plane(tmp: Path) -> MarketSimControlPlane:
    markets = tmp / "markets"
    markets.mkdir()
    store = MarketSimStore(tmp / "lev.db")
    store.initialize()
    data = MarketDataStore(store, markets)
    plane = MarketSimControlPlane(store=store, data=data, enabled=True)
    plane._runners_externalized = staticmethod(lambda: False)  # type: ignore[method-assign]
    provider = MagicMock()
    provider.status.return_value = MagicMock(reachable=True, latency_ms=1.0)
    provider.fetch_quote.return_value = {"price": 100.0, "symbol": "BTCUSDT"}
    plane.providers = MagicMock()
    plane.providers.get.return_value = provider
    return plane


def _seed_strategy(plane: MarketSimControlPlane, strategy_id: str = "strat-lineage") -> StrategyVersion:
    record = StrategyRecord(
        strategy_id=strategy_id,
        name="Lineage Test Strategy",
        description="test",
        status=StrategyStatus.RESEARCH.value,
        tags=["test"],
        current_version=1,
        content_hash="hash-lineage",
        created_at="2026-01-01T00:00:00+00:00",
        updated_at="2026-01-01T00:00:00+00:00",
        metadata={},
    )
    version = StrategyVersion(
        version_id=f"{strategy_id}-v1",
        strategy_id=strategy_id,
        version=1,
        content_hash="hash-lineage-v1",
        parameters={"period": 10},
        entry_rules={"version": 3, "kind": "momentum", "parameters": {"period": 10}},
        exit_rules={"kind": "momentum"},
        risk_rules={},
        required_timeframes=["1D"],
        brain_dependencies=[],
        created_at="2026-01-01T00:00:00+00:00",
        changelog="seed",
        metadata={"applicability": {}},
    )
    plane.store.create_strategy(record, version)
    return version


class PaperLineageWave37Tests(unittest.TestCase):
    def test_autonomous_paper_step_receipt_includes_lineage_ids(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            plane = _plane(Path(tmp))
            _seed_strategy(plane)
            paper = plane.create_and_persist_paper_deployment(
                strategy_id="strat-lineage",
                mode="autonomous_paper",
                symbol="BTCUSDT",
                universe=["BTCUSDT"],
            )
            dep_id = paper["deployment"]["deployment_id"]
            with mock.patch.object(plane, "paper_forward_step") as fwd:
                fwd.return_value = {
                    "forward": {"checkpoint_step": 1},
                    "result": {
                        "allowed": True,
                        "blocked": False,
                        "order": {"order_id": "ord-lineage-1", "side": "HOLD"},
                    },
                }
                with mock.patch(
                    "Data.modules.market_sim.autonomous_paper_loop.assert_deployment_ready_for_orders",
                    return_value=None,
                ):
                    out = plane.autonomous_paper_step(dep_id, side="HOLD")
            receipt = out["receipt"]
            for key in (
                "trace_id",
                "root_id",
                "root_trace_id",
                "parent_id",
                "parent_trace_id",
                "decision_id",
                "order_id",
            ):
                self.assertIn(key, receipt)
            self.assertTrue(receipt["trace_id"])
            self.assertTrue(receipt["root_id"])
            self.assertTrue(receipt["parent_id"])
            self.assertTrue(receipt["decision_id"])
            self.assertEqual(receipt["order_id"], "ord-lineage-1")
            self.assertEqual(receipt["decision_id"], receipt["step_id"])
            self.assertEqual(receipt["root_id"], receipt["root_trace_id"])


if __name__ == "__main__":
    unittest.main()
