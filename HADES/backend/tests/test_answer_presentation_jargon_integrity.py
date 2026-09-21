from __future__ import annotations

import unittest

from reasoning.answer_presentation import present_answer, strip_pipeline_jargon


class AnswerPresentationJargonIntegrityTests(unittest.TestCase):
    def test_legitimate_identifier_in_prose_is_preserved(self) -> None:
        text = "The evidence_refs field contains the source IDs used by the critic."
        cleaned, stripped = strip_pipeline_jargon(text)
        self.assertEqual(cleaned, text)
        self.assertFalse(stripped)

    def test_legitimate_identifier_in_code_explanation_is_preserved(self) -> None:
        text = "Use `speech_act` to describe whether the request is a question or an execution request."
        presented = present_answer(text, verification_called=False)
        self.assertEqual(presented.content, text)
        self.assertFalse(presented.pipeline_jargon_stripped)

    def test_standalone_internal_metadata_row_is_removed(self) -> None:
        text = "Resultaat voor de gebruiker.\nevidence_refs: [\"step:1\"]\nDit is de conclusie."
        cleaned, stripped = strip_pipeline_jargon(text)
        self.assertTrue(stripped)
        self.assertNotIn("evidence_refs:", cleaned)
        self.assertIn("Resultaat voor de gebruiker.", cleaned)
        self.assertIn("Dit is de conclusie.", cleaned)

    def test_json_style_metadata_row_is_removed(self) -> None:
        text = 'Antwoord.\n"parse_status": "verified"\nEinde.'
        cleaned, stripped = strip_pipeline_jargon(text)
        self.assertTrue(stripped)
        self.assertNotIn("parse_status", cleaned)
        self.assertEqual(cleaned, "Antwoord.\n\nEinde.")


if __name__ == "__main__":
    unittest.main()
