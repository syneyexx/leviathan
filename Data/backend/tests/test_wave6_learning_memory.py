"""Wave 6 — durable learning memory contract."""

from __future__ import annotations

import unittest

from Data.modules.market_sim.agent_lab import LessonTrust
from Data.modules.market_sim.learning_memory import (
    DurableLearningLesson,
    EpistemicState,
    LearningEpistemicState,
    LearningLesson,
    advance_epistemic_state,
    deduplicate_lessons,
    map_epistemic_to_trust,
    map_trust_to_epistemic,
    new_durable_lesson,
    persistable_lesson_payload,
    strip_chain_of_thought,
    validate_epistemic_transition,
)


class LearningMemoryContractTests(unittest.TestCase):
    def test_epistemic_maps_onto_existing_trust(self) -> None:
        self.assertEqual(map_trust_to_epistemic(LessonTrust.AGENT_PROPOSED.value), EpistemicState.PROPOSED)
        self.assertEqual(map_trust_to_epistemic(LessonTrust.VALIDATED.value), EpistemicState.VERIFIED)
        self.assertEqual(map_trust_to_epistemic(LessonTrust.REJECTED.value), EpistemicState.REJECTED)
        self.assertEqual(map_trust_to_epistemic("MEASURED"), EpistemicState.MEASURED)
        self.assertEqual(map_trust_to_epistemic("REPLICATED"), EpistemicState.REPLICATED)
        self.assertEqual(map_trust_to_epistemic("SUPERSEDED"), EpistemicState.SUPERSEDED)
        self.assertEqual(map_epistemic_to_trust(EpistemicState.PROPOSED), LessonTrust.AGENT_PROPOSED.value)
        self.assertEqual(map_epistemic_to_trust(EpistemicState.VERIFIED), LessonTrust.VALIDATED.value)
        # Enum alias stability
        self.assertIs(EpistemicState, LearningEpistemicState)

    def test_lesson_required_fields(self) -> None:
        lesson = new_durable_lesson(
            claim="High turnover collapses under fee stress",
            origin="learning_runtime",
            producer="strategy_critic",
            domain="market_sim",
            subject="momentum",
            evidence_refs=["exp-1"],
            experiment_refs=["trial-9"],
            strategy_id="strat-a",
            strategy_version=3,
            dataset_versions=["ds-v1"],
            environment="paper",
            confidence=0.4,
            failure_categories=["cost_sensitivity"],
            negative_evidence=True,
        )
        d = lesson.public_dict()
        for key in (
            "lesson_id",
            "origin",
            "created_at",
            "available_at",
            "producer",
            "domain",
            "subject",
            "claim",
            "evidence_refs",
            "experiment_refs",
            "strategy_id",
            "strategy_version",
            "dataset_versions",
            "environment",
            "confidence",
            "validation_stage",
            "epistemic_state",
            "failure_categories",
            "contradictions",
            "supersedes",
            "trust_state",
        ):
            self.assertIn(key, d)
        self.assertTrue(d["negative_evidence"])
        self.assertTrue(d["truth"]["no_private_cot"])
        self.assertEqual(d["trust"], LessonTrust.REJECTED.value)

    def test_strip_chain_of_thought(self) -> None:
        cleaned = strip_chain_of_thought(
            {
                "claim": "ok",
                "chain_of_thought": "secret reasoning",
                "metadata": {"scratchpad": "nope", "note": "keep"},
            }
        )
        self.assertNotIn("chain_of_thought", cleaned)
        self.assertEqual(cleaned["claim"], "ok")
        self.assertNotIn("scratchpad", cleaned["metadata"])
        self.assertEqual(cleaned["metadata"]["note"], "keep")

    def test_persistable_payload_strips_cot(self) -> None:
        lesson = new_durable_lesson(
            claim="Regime filter required",
            metadata={"chain_of_thought": "secret-cot-trace", "public_note": "visible"},
        )
        payload = persistable_lesson_payload(lesson)
        self.assertNotIn("chain_of_thought", payload.get("metadata") or {})
        self.assertNotIn("secret-cot-trace", str(payload.get("metadata")))
        self.assertIn("visible", str(payload.get("metadata")))

    def test_retain_negative_and_dedup_safe(self) -> None:
        pos = new_durable_lesson(claim="Momentum works in trends", epistemic_state="PROPOSED")
        pos2 = new_durable_lesson(claim="Momentum works in trends", epistemic_state="MEASURED")
        neg = new_durable_lesson(
            claim="Momentum fails under cost stress",
            negative_evidence=True,
            epistemic_state="REJECTED",
            failure_categories=["cost_sensitivity"],
        )
        deduped = deduplicate_lessons([pos, pos2, neg])
        claims = [d.claim for d in deduped]
        self.assertEqual(sum(1 for c in claims if "works in trends" in c.lower()), 1)
        self.assertTrue(any(d.negative_evidence for d in deduped))
        measured = next(d for d in deduped if "works in trends" in d.claim.lower())
        self.assertEqual(measured.epistemic_state, EpistemicState.MEASURED.value)

    def test_epistemic_transitions(self) -> None:
        validate_epistemic_transition("PROPOSED", "OBSERVED")
        validate_epistemic_transition("MEASURED", "REPLICATED")
        validate_epistemic_transition("REPLICATED", "VERIFIED")
        with self.assertRaises(ValueError):
            validate_epistemic_transition("REJECTED", "VERIFIED")
        lesson = new_durable_lesson(claim="x", epistemic_state="PROPOSED")
        advanced = advance_epistemic_state(lesson, "MEASURED")
        self.assertEqual(advanced.epistemic_state, "MEASURED")
        self.assertEqual(map_epistemic_to_trust(advanced.trust_state), LessonTrust.AGENT_PROPOSED.value)

    def test_lab_lesson_projection_compatible(self) -> None:
        lesson = new_durable_lesson(claim="compatible", subject="rsi", epistemic_state="VERIFIED")
        self.assertIsInstance(lesson, LearningLesson)
        self.assertIsInstance(lesson, DurableLearningLesson)
        lab = lesson.to_lab_lesson_dict()
        self.assertEqual(lab["trust"], LessonTrust.VALIDATED.value)
        self.assertEqual(lab["metadata"]["epistemic_state"], "VERIFIED")


if __name__ == "__main__":
    unittest.main()
