"""Wave 1 research hypothesis contracts — persist, lifecycle, falsification immutability."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from Data.modules.market_sim.research_hypothesis import (
    assert_falsification_immutable,
    new_research_hypothesis,
    research_hypothesis_from_mapping,
    transition_hypothesis_status,
)
from Data.modules.market_sim.store import MarketSimStore


class ResearchHypothesisW1Tests(unittest.TestCase):
    def test_create_persist_retrieve(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = MarketSimStore(Path(tmp) / "lev.db")
            store.initialize()
            hyp = new_research_hypothesis(
                statement="Breakouts after compression may show positive net expectancy.",
                mechanism="Volatility contraction → expansion",
                rationale_summary="Operator brief for discovery",
                created_at="2024-06-01T00:00:00+00:00",
                lab_id="lab-w1",
                falsification_criteria=[
                    "net_expectancy_after_costs <= 0 on validation",
                    "max_drawdown exceeds acceptance policy",
                ],
                trust="AGENT_PROPOSED",
                status="PROPOSED",
            )
            saved = store.upsert_research_hypothesis(hyp.public_dict())
            self.assertEqual(saved["hypothesis_id"], hyp.hypothesis_id)
            loaded = store.get_research_hypothesis(hyp.hypothesis_id)
            self.assertIsNotNone(loaded)
            assert loaded is not None
            self.assertEqual(loaded["statement"], hyp.statement)
            self.assertEqual(loaded["lab_id"], "lab-w1")
            self.assertEqual(loaded["status"], "PROPOSED")
            listed = store.list_research_hypotheses(lab_id="lab-w1", limit=10)
            self.assertEqual(len(listed), 1)
            self.assertEqual(listed[0]["hypothesis_id"], hyp.hypothesis_id)

    def test_status_transitions(self) -> None:
        hyp = new_research_hypothesis(
            statement="Momentum continues in trending regimes.",
            created_at="2024-06-01T00:00:00+00:00",
            falsification_criteria=["fails regime matrix"],
        )
        self.assertEqual(hyp.status, "PROPOSED")
        transition_hypothesis_status(
            hyp,
            new_status="TESTING",
            evidence_ref="trial-1",
            trust="UNDER_TEST",
        )
        self.assertEqual(hyp.status, "TESTING")
        self.assertEqual(hyp.trust, "UNDER_TEST")
        self.assertIn("trial-1", hyp.evidence_refs)
        # Falsification unchanged across transitions
        self.assertEqual(hyp.falsification_criteria, ["fails regime matrix"])
        transition_hypothesis_status(
            hyp,
            new_status="REJECTED",
            counterevidence_ref="val-fail-1",
            trust="REJECTED",
        )
        self.assertEqual(hyp.status, "REJECTED")
        self.assertIn("val-fail-1", hyp.counterevidence_refs)

    def test_falsification_immutable_after_create(self) -> None:
        hyp = new_research_hypothesis(
            statement="RSI mean reversion edge exists.",
            created_at="2024-06-01T00:00:00+00:00",
            falsification_criteria=["net_expectancy <= 0"],
        )
        self.assertTrue(hyp.falsification_frozen)
        assert_falsification_immutable(hyp, proposed_criteria=["net_expectancy <= 0"])
        with self.assertRaises(ValueError) as ctx:
            assert_falsification_immutable(
                hyp,
                proposed_criteria=["loosened: net_expectancy <= -10"],
            )
        self.assertIn("FALSIFICATION_IMMUTABLE", str(ctx.exception))
        # Persist + reload preserves frozen criteria
        with tempfile.TemporaryDirectory() as tmp:
            store = MarketSimStore(Path(tmp) / "lev.db")
            store.initialize()
            store.upsert_research_hypothesis(hyp.public_dict())
            loaded = store.get_research_hypothesis(hyp.hypothesis_id)
            restored = research_hypothesis_from_mapping(loaded)
            self.assertEqual(restored.falsification_criteria, ["net_expectancy <= 0"])
            with self.assertRaises(ValueError):
                assert_falsification_immutable(
                    restored,
                    proposed_criteria=["different criteria after results"],
                )

    def test_public_dict_no_private_cot_fields(self) -> None:
        hyp = new_research_hypothesis(
            statement="Public structured reasoning only.",
            rationale_summary="Short public rationale",
            created_at="2024-06-01T00:00:00+00:00",
            falsification_criteria=["insufficient sample"],
            metadata={"origin": "unit_test"},
        )
        public = hyp.public_dict()
        forbidden = {
            "chain_of_thought",
            "private_cot",
            "cot",
            "reasoning_trace",
            "hidden_rationale",
            "raw_model_thoughts",
            "scratchpad",
        }
        self.assertTrue(public["truth"]["no_private_cot"])
        self.assertTrue(public["truth"]["public_structured_reasoning"])
        for key in forbidden:
            self.assertNotIn(key, public)
            self.assertNotIn(key, public.get("metadata") or {})
        # Round-trip via store must not invent private fields
        with tempfile.TemporaryDirectory() as tmp:
            store = MarketSimStore(Path(tmp) / "lev.db")
            store.initialize()
            store.upsert_research_hypothesis(public)
            loaded = store.get_research_hypothesis(hyp.hypothesis_id)
            assert loaded is not None
            for key in forbidden:
                self.assertNotIn(key, loaded)


if __name__ == "__main__":
    unittest.main()
