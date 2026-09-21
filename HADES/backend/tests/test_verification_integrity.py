"""Regression tests for verification checklist integrity (Phase 1).

Reproduces and locks:
A. String \"false\" must not become met=True via bool().
B. passed=True without criteria_checklist must not auto-mark criteria met.
C. Wrong-criterion rows must not bind via positional fallback.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from reasoning.verification import (
    apply_critic_outcome,
    build_acceptance_checklist,
    build_allowed_evidence_refs,
    build_verification_prompt,
    checklist_blocks_completion,
    parse_strict_bool,
    parse_verification_result,
    validate_evidence_refs,
    verification_allows_success,
)


class StrictBoolTests(unittest.TestCase):
    def test_string_false_is_false(self) -> None:
        self.assertIs(parse_strict_bool("false"), False)
        self.assertIs(parse_strict_bool("False"), False)
        self.assertIs(parse_strict_bool("true"), True)

    def test_arbitrary_truthy_string_rejected(self) -> None:
        self.assertIsNone(parse_strict_bool("yesn't"))
        self.assertIsNone(parse_strict_bool("definitely"))
        self.assertIsNone(parse_strict_bool(""))


class BugAStringAsBooleanTests(unittest.TestCase):
    def test_checklist_met_false_string_not_truthy(self) -> None:
        parsed = parse_verification_result(
            '{"passed":true,"issues":[],"final":"x","evidence_refs":["step:1"],'
            '"criteria_checklist":[{"criterion":"A","met":"false"}]}'
        )
        self.assertIsNotNone(parsed)
        assert parsed is not None
        self.assertEqual(len(parsed.criteria_checklist), 1)
        self.assertFalse(parsed.criteria_checklist[0].met)
        checklist = build_acceptance_checklist(["A"], result=parsed)
        self.assertFalse(checklist[0].met)
        ok, reason = verification_allows_success(
            parsed,
            step_outputs=[{"title": "Stap", "agent_id": "executor", "output": "ok"}],
            acceptance_criteria=["A"],
        )
        self.assertFalse(ok)
        self.assertIn("Acceptatiecriteria", reason)


class BugBMissingChecklistTests(unittest.TestCase):
    def test_passed_without_checklist_does_not_auto_meet(self) -> None:
        parsed = parse_verification_result(
            '{"passed":true,"issues":[],"final":"x","evidence_refs":["step:1"]}'
        )
        self.assertIsNotNone(parsed)
        assert parsed is not None
        self.assertEqual(parsed.criteria_checklist, [])
        checklist = build_acceptance_checklist(["Crit1", "Crit2"], result=parsed)
        self.assertEqual([row.met for row in checklist], [False, False])
        self.assertTrue(all("zonder checklist" in row.note or "checklist" in row.note.lower() for row in checklist))
        ok, reason = verification_allows_success(
            parsed,
            step_outputs=[{"title": "Stap", "agent_id": "a", "output": "ok"}],
            acceptance_criteria=["Crit1", "Crit2"],
        )
        self.assertFalse(ok)
        self.assertIn("Acceptatiecriteria", reason)


class BugCPositionalFallbackTests(unittest.TestCase):
    def test_wrong_criterion_does_not_bind_positionally(self) -> None:
        parsed = parse_verification_result(
            '{"passed":true,"issues":[],"final":"x","evidence_refs":["step:1"],'
            '"criteria_checklist":[{"criterion":"OTHER","met":true,"note":"wrong"}]}'
        )
        assert parsed is not None
        checklist = build_acceptance_checklist(["Expected Crit"], result=parsed)
        self.assertEqual(len(checklist), 1)
        self.assertEqual(checklist[0].criterion, "Expected Crit")
        self.assertFalse(checklist[0].met)
        self.assertIn("geen positionele fallback", checklist[0].note.lower())
        ok, _ = verification_allows_success(
            parsed,
            step_outputs=[{"title": "Stap", "agent_id": "a", "output": "ok"}],
            acceptance_criteria=["Expected Crit"],
        )
        self.assertFalse(ok)

    def test_stable_id_match_works(self) -> None:
        parsed = parse_verification_result(
            '{"passed":true,"issues":[],"final":"Klaar","evidence_refs":["step:1"],'
            '"criteria_checklist":[{"id":"c1","criterion":"Klaar resultaat","met":true,"note":"ok"}]}'
        )
        ok, reason = verification_allows_success(
            parsed,
            step_outputs=[{"title": "Stap", "agent_id": "executor", "output": "ok"}],
            acceptance_criteria=["Klaar resultaat"],
        )
        self.assertTrue(ok, reason)


class CircularDraftEvidenceTests(unittest.TestCase):
    def test_draft_step_not_in_allowed_factual_refs(self) -> None:
        steps = [
            {
                "title": "Chatantwoord",
                "agent_id": "chat",
                "output": "De maan is gemaakt van kaas.",
                "is_draft": True,
                "evidence_role": "candidate_answer",
            }
        ]
        allowed = build_allowed_evidence_refs(step_outputs=steps, include_draft_steps=False)
        self.assertNotIn("step:1", allowed)
        ok, reason = validate_evidence_refs(["step:1"], step_outputs=steps)
        self.assertFalse(ok)
        self.assertIn("ongeldige", reason.lower())

    def test_prompt_separates_draft_from_evidence(self) -> None:
        prompt = build_verification_prompt(
            task_title="Chat",
            task_prompt="Wat is de maan?",
            acceptance_criteria=["Feitelijk correct"],
            step_outputs=[
                {
                    "title": "Chatantwoord",
                    "agent_id": "chat",
                    "output": "Kaas",
                    "is_draft": True,
                }
            ],
            tool_observations=[],
        )
        self.assertIn("GEEN feitelijk bewijs", prompt)
        self.assertIn("CONCEPTANTWOORD", prompt)

    def test_self_referential_answer_not_factual_verified(self) -> None:
        draft = "Volgens mijn eigen antwoord is X waar."
        parsed = parse_verification_result(
            '{"passed":true,"issues":[],"final":"' + draft + '","evidence_refs":["step:1"],'
            '"criteria_checklist":[{"id":"c1","criterion":"Feiten geverifieerd","met":true}]}'
        )
        ok, reason = verification_allows_success(
            parsed,
            step_outputs=[
                {
                    "title": "Chatantwoord",
                    "agent_id": "chat",
                    "output": draft,
                    "is_draft": True,
                }
            ],
            acceptance_criteria=["Feiten geverifieerd"],
            require_evidence_when_tools=False,
        )
        self.assertFalse(ok)
        self.assertIn("evidence_refs", reason.lower())


class CriticRewriteContractTests(unittest.TestCase):
    def test_critic_rewrite_not_auto_adopted(self) -> None:
        draft = "Origineel concept."
        parsed = parse_verification_result(
            '{"passed":true,"issues":[],"final":"Herschreven met nieuwe claim Y","evidence_refs":["step:1"],'
            '"criteria_checklist":[{"id":"c1","criterion":"Ok","met":true}]}'
        )
        assert parsed is not None
        self.assertEqual(parsed.final_answer, "")
        self.assertIn("Herschreven", parsed.proposed_final_answer)
        content, note, _ = apply_critic_outcome(
            draft_answer=draft,
            result=parsed,
            allowed=True,
            reason="",
        )
        self.assertEqual(content, draft)
        self.assertIn("pending_recheck", note)


class SchemaRepairTests(unittest.TestCase):
    def test_invalid_json_stays_unverified(self) -> None:
        parsed = parse_verification_result("not json at all")
        assert parsed is not None
        self.assertFalse(parsed.passed)
        self.assertTrue(parsed.incomplete)
        self.assertEqual(parsed.parse_status, "invalid_json")
        ok, _ = verification_allows_success(parsed, acceptance_criteria=["X"])
        self.assertFalse(ok)

    def test_passed_string_repaired_or_rejected(self) -> None:
        parsed = parse_verification_result(
            '{"passed":"true","issues":[],"final":"x","evidence_refs":[],'
            '"criteria_checklist":[{"id":"c1","criterion":"X","met":true}]}'
        )
        assert parsed is not None
        self.assertTrue(parsed.schema_valid)
        self.assertIn(parsed.parse_status, {"valid_schema", "repaired"})


class SoftLimitDoesNotSilentPassTests(unittest.TestCase):
    def test_overflow_criteria_remain_unmet_when_unmatched(self) -> None:
        many = [f"Crit {i}" for i in range(5)]
        parsed = parse_verification_result(
            '{"passed":true,"issues":[],"final":"x","evidence_refs":["step:1"],'
            '"criteria_checklist":[{"id":"c1","criterion":"Crit 0","met":true}]}'
        )
        checklist = build_acceptance_checklist(many, result=parsed)
        self.assertEqual(len(checklist), 5)
        self.assertTrue(checklist[0].met)
        self.assertFalse(any(row.met for row in checklist[1:]))
        self.assertTrue(checklist_blocks_completion(checklist))


if __name__ == "__main__":
    unittest.main()
