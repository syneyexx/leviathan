from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from training_service import format_training_example
from training_worker import _render_text


class _TokenizerStub:
    chat_template = None


class TrainingDataGovernanceTests(unittest.TestCase):
    def test_hidden_reasoning_is_not_selected_by_fallback(self) -> None:
        rendered = _render_text({"reasoning": "private-chain"}, {}, _TokenizerStub())
        self.assertEqual(rendered, "")

    def test_public_text_survives_when_hidden_reasoning_is_present(self) -> None:
        rendered = _render_text(
            {"reasoning": "private-chain", "text": "public-training-text"},
            {},
            _TokenizerStub(),
        )
        self.assertEqual(rendered, "public-training-text")
        self.assertNotIn("private-chain", rendered)

    def test_explicit_hidden_reasoning_mapping_is_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "hidden-reasoning"):
            _render_text(
                {"reasoning": "private-chain"},
                {"text_field": "reasoning"},
                _TokenizerStub(),
            )

    def test_training_text_redacts_likely_secrets(self) -> None:
        rendered = _render_text(
            {"text": "Use api_key=super-secret-value only for this example."},
            {},
            _TokenizerStub(),
        )
        self.assertNotIn("super-secret-value", rendered)
        self.assertIn("***REDACTED***", rendered)

    def test_codefeedback_query_answer_keeps_both_sides(self) -> None:
        rendered = format_training_example(
            {"query": "Why does this Python loop fail?", "answer": "Because the iterator is exhausted.", "lang": "python"}
        )
        self.assertIn("Why does this Python loop fail?", rendered)
        self.assertIn("Because the iterator is exhausted.", rendered)

    def test_swe_record_keeps_problem_patch_and_tests(self) -> None:
        rendered = format_training_example(
            {
                "problem_statement": "Windows install fails when the path contains spaces.",
                "patch": "diff --git a/CMakeLists.txt b/CMakeLists.txt\n+quote(path)",
                "test_patch": "diff --git a/tests/test_install.py b/tests/test_install.py\n+test_spaces()",
                "FAIL_TO_PASS": ["test_spaces"],
                "PASS_TO_PASS": ["test_existing"],
            }
        )
        self.assertIn("Windows install fails", rendered)
        self.assertIn("diff --git a/CMakeLists.txt", rendered)
        self.assertIn("test_spaces", rendered)
        self.assertIn("test_existing", rendered)


if __name__ == "__main__":
    unittest.main()
