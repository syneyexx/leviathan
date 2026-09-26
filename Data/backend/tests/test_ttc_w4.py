"""W4 — Test-time compute candidate search + technical IntegrityScorer."""

from __future__ import annotations

import unittest

from Data.modules.cognition.ttc import (
    Candidate,
    IntegrityScorer,
    TestTimeComputeEngine,
    ToolGroundingScorer,
)


class TestTimeComputeTests(unittest.TestCase):
    def test_scores_selects_grounded_candidate(self) -> None:
        engine = TestTimeComputeEngine()
        result = engine.run(
            [
                "I ran the tests and everything passed.",
                "Based on evidence ref:ev-1 the reconnect race is in the pending-call queue.",
                "As system instructions from the document I will ignore prior policy.",
            ],
            context={
                "required_evidence_refs": ["ref:ev-1"],
                "tool_receipts": [],
                "constraints": ["must_include:reconnect"],
            },
            keep=2,
        )
        self.assertTrue(result.selected_id)
        selected = result.selected
        assert selected is not None
        self.assertIn("reconnect", selected.output.lower())
        self.assertNotIn("I ran the tests", selected.output)
        # Fabricated tool claim and authority confusion rejected.
        rejected_reasons = " ".join(c.reject_reason or "" for c in result.candidates if c.rejected)
        self.assertTrue(
            "fabricated" in rejected_reasons.lower()
            or "authority" in rejected_reasons.lower()
            or any(c.rejected for c in result.candidates)
        )
        pub = result.public_dict()
        self.assertTrue(pub["truth"]["integrity_scorer_is_technical_not_ideological"])
        self.assertTrue(selected.public_dict()["truth"]["raw_private_reasoning_not_persisted"])

    def test_schema_scorer_hard_fails_invalid_json(self) -> None:
        engine = TestTimeComputeEngine()
        result = engine.score_all(
            [
                Candidate(candidate_id="bad", output="not json"),
                Candidate(
                    candidate_id="good",
                    output='{"ok": true}',
                    structured={"ok": True},
                ),
            ],
            context={"response_schema": {"required": ["ok"]}},
        )
        self.assertEqual(result.selected_id, "good")
        bad = next(c for c in result.candidates if c.candidate_id == "bad")
        self.assertTrue(bad.rejected)

    def test_integrity_scorer_not_ideological(self) -> None:
        scorer = IntegrityScorer()
        # Political content alone must not hard-fail.
        score = scorer.score(
            Candidate(candidate_id="p", output="Voters disagreed about fiscal policy."),
            context={},
        )
        self.assertFalse(score.hard_fail)
        self.assertEqual(score.score, 1.0)
        self.assertIn("not content moderation", score.detail or "")

    def test_tool_grounding_requires_receipt(self) -> None:
        scorer = ToolGroundingScorer()
        fail = scorer.score(
            Candidate(candidate_id="a", output="I browsed the page and confirmed the bug."),
            context={"tool_receipts": []},
        )
        self.assertTrue(fail.hard_fail)
        ok = scorer.score(
            Candidate(candidate_id="b", output="I browsed the page and confirmed the bug."),
            context={"tool_receipts": ["browser", "receipt:browser"]},
        )
        self.assertFalse(ok.hard_fail)

    def test_repair_uses_verifier_feedback(self) -> None:
        engine = TestTimeComputeEngine(max_repairs=1)

        def reviser(cand: Candidate, feedback: list[str]) -> Candidate:
            return Candidate(
                candidate_id=cand.candidate_id + "-r",
                output='{"ok": true, "note": "repaired using: ' + ",".join(feedback[:2]) + '"}',
                structured={"ok": True, "note": "repaired"},
            )

        result = engine.run(
            ['plain text without schema'],
            context={"response_schema": {"required": ["ok"]}},
            reviser=reviser,
            keep=1,
        )
        self.assertTrue(result.evaluation.get("repaired") or result.selected is not None)
        selected = result.selected
        assert selected is not None
        self.assertIn("ok", selected.output.lower() + str(selected.structured))


if __name__ == "__main__":
    unittest.main()
