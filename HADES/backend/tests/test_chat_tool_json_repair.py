"""Bounded JSON repair for local-model tool/critic payloads."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from reasoning.json_util import loads_json_object, loads_json_value
from reasoning.tool_protocol import _parse_arguments, merge_stream_fragment
from reasoning.tools import parse_tool_choice
from reasoning.understanding import parse_classifier_output
from reasoning.verification import (
    build_allowed_evidence_refs,
    build_verification_prompt,
    parse_verification_result,
    verification_allows_success,
)


class JsonRepairTests(unittest.TestCase):
    def test_trailing_comma_object(self) -> None:
        parsed = loads_json_object('{"passed": true, "issues": [],}')
        self.assertEqual(parsed, {"passed": True, "issues": []})

    def test_python_literals_and_single_quotes(self) -> None:
        parsed = loads_json_object("{'text': True, 'count': None}")
        self.assertEqual(parsed, {"text": True, "count": None})

    def test_double_encoded_object(self) -> None:
        parsed = loads_json_object('"{\\"q\\": \\"hi\\"}"')
        self.assertEqual(parsed, {"q": "hi"})

    def test_garbage_stays_none(self) -> None:
        self.assertIsNone(loads_json_object("{not-json"))
        self.assertIsNone(loads_json_value("hello world"))


class ToolArgumentRepairTests(unittest.TestCase):
    def test_trailing_comma_arguments(self) -> None:
        args, _raw, err = _parse_arguments('{"text": "Hallo",}')
        self.assertIsNone(err)
        self.assertEqual(args, {"text": "Hallo"})

    def test_still_rejects_broken_json(self) -> None:
        args, _raw, err = _parse_arguments("{not-json")
        self.assertEqual(args, {})
        self.assertIn("malformed", err or "")

    def test_text_fallback_repairs_tool_json(self) -> None:
        choice = parse_tool_choice(
            '```json\n{"hades_tool_call":{"plugin_id":"echo","tool_name":"echo","input":{"args":["x"],},},}\n```'
        )
        self.assertIsNotNone(choice)
        assert choice is not None
        self.assertEqual(choice["plugin_id"], "echo")
        self.assertEqual(choice["input"]["args"], ["x"])


class StreamMergeTests(unittest.TestCase):
    def test_snapshot_chunks_are_not_duplicated(self) -> None:
        acc = ""
        for piece in ('{"q":', '{"q":"hi"}', '{"q":"hi"}'):
            acc = merge_stream_fragment(acc, piece)
        self.assertEqual(acc, '{"q":"hi"}')

    def test_true_suffix_deltas_still_concatenate(self) -> None:
        acc = merge_stream_fragment('{"q":', '"hi"}')
        self.assertEqual(acc, '{"q":"hi"}')


class CriticJsonAndStepNumberingTests(unittest.TestCase):
    def test_critic_json_with_trailing_comma_parses(self) -> None:
        parsed = parse_verification_result(
            'Natuurlijk:\n{"passed":true,"issues":[],"final":"ok","evidence_refs":["step:1"],'
            '"criteria_checklist":[{"id":"c1","criterion":"Ok","met":true,}],}\n'
        )
        self.assertIsNotNone(parsed)
        assert parsed is not None
        self.assertTrue(parsed.passed)
        self.assertNotEqual(parsed.parse_status, "invalid_json")

    def test_draft_does_not_occupy_step_1(self) -> None:
        steps = [
            {
                "title": "Chatantwoord",
                "agent_id": "chat",
                "output": "Concept",
                "is_draft": True,
                "evidence_role": "candidate_answer",
            },
            {"title": "Echo-resultaat", "agent_id": "tool", "output": "Hallo", "step_id": "c1"},
        ]
        allowed = build_allowed_evidence_refs(step_outputs=steps)
        self.assertIn("step:1", allowed)
        prompt = build_verification_prompt(
            task_title="Chat",
            task_prompt="Gebruik echo",
            acceptance_criteria=["Tool gebruikt"],
            step_outputs=steps,
            tool_observations=[
                {
                    "call_id": "c1",
                    "plugin_id": "echo",
                    "tool_name": "echo",
                    "status": "completed",
                }
            ],
            draft_answer="Concept",
        )
        self.assertIn("step:1 Echo-resultaat", prompt)
        self.assertIn("geen step-ref", prompt.lower())
        parsed = parse_verification_result(
            '{"passed":true,"issues":[],"final":"Hallo","evidence_refs":["step:1","tool:c1"],'
            '"criteria_checklist":[{"id":"c1","criterion":"Tool gebruikt","met":true}]}'
        )
        ok, reason = verification_allows_success(
            parsed,
            step_outputs=steps,
            tool_observations=[
                {
                    "call_id": "c1",
                    "plugin_id": "echo",
                    "tool_name": "echo",
                    "status": "completed",
                }
            ],
            acceptance_criteria=["Tool gebruikt"],
        )
        self.assertTrue(ok, reason)

    def test_classifier_repairs_trailing_comma(self) -> None:
        parsed = parse_classifier_output(
            '{"intent":"execute","independent_outcomes":1,"has_dependencies":false,'
            '"ambiguity":"low","freshness":false,"tools":true,"evidence_kind":"tool_results",}'
        )
        self.assertIsNotNone(parsed)
        assert parsed is not None
        self.assertEqual(parsed["intent"], "execute")
        self.assertTrue(parsed["tools"])


if __name__ == "__main__":
    unittest.main()
