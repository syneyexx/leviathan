"""T15: invented citations on sourced answers are marked uncovered."""

from __future__ import annotations

import unittest

from reasoning.evidence_coverage import (
    annotate_uncovered_citations,
    apply_citation_verification,
    extract_quoted_spans,
    verify_quoted_citations,
)


SOURCE_PASSAGE = (
    "De reactor bleef binnen de veiligheidsmarges tijdens de koude start-test. "
    "Operatoren noteerden geen afwijkende drukpieken."
)


class CitationVerificationT15Tests(unittest.TestCase):
    def test_extract_quoted_spans(self) -> None:
        text = 'Volgens het rapport: "De reactor bleef binnen de veiligheidsmarges tijdens de koude start-test."'
        quotes = extract_quoted_spans(text)
        self.assertEqual(len(quotes), 1)
        self.assertIn("reactor bleef binnen", quotes[0])

    def test_invented_citation_is_uncovered(self) -> None:
        answer = (
            'Het rapport stelt: "De reactor explodeerde spontaan zonder waarschuwing '
            'en alle systemen faalden direct."'
        )
        report = verify_quoted_citations(
            answer,
            evidence_texts={"knowledge:src1": SOURCE_PASSAGE},
        )
        self.assertTrue(report["checked"])
        self.assertTrue(report["has_invented_citation"])
        self.assertEqual(len(report["uncovered"]), 1)
        self.assertEqual(report["uncovered"][0]["reason"], "quote_not_in_sources")
        self.assertEqual(report["covered"], [])

    def test_real_citation_is_covered(self) -> None:
        answer = (
            'Het rapport stelt: "De reactor bleef binnen de veiligheidsmarges '
            'tijdens de koude start-test."'
        )
        report = verify_quoted_citations(
            answer,
            evidence_texts={"knowledge:src1": SOURCE_PASSAGE},
        )
        self.assertTrue(report["checked"])
        self.assertFalse(report["has_invented_citation"])
        self.assertEqual(len(report["covered"]), 1)
        self.assertEqual(report["covered"][0]["ref"], "knowledge:src1")

    def test_annotate_marks_uncovered_in_answer(self) -> None:
        answer = 'Bron: "Dit is een verzonnen citaat dat nergens voorkomt."'
        report = verify_quoted_citations(
            answer,
            evidence_texts={"knowledge:src1": SOURCE_PASSAGE},
        )
        annotated, notes = annotate_uncovered_citations(answer, report)
        self.assertTrue(any(n.startswith("invented_citations:") for n in notes))
        self.assertIn("[HADES citaatcontrole]", annotated)
        self.assertIn("ongedekt", annotated)

    def test_apply_skips_when_no_sources_in_turn(self) -> None:
        answer = 'Gewoon chat: "Dit is een citaat zonder bronnen in deze beurt."'
        annotated, report, notes = apply_citation_verification(
            answer,
            evidence_texts={},
            sources_used=False,
        )
        self.assertEqual(annotated, answer)
        self.assertFalse(report["checked"])
        self.assertEqual(report["reason"], "no_sources_in_turn")
        self.assertEqual(notes, [])

    def test_apply_marks_invented_on_sourced_turn(self) -> None:
        answer = 'Volgens de kennisbank: "Dit citaat is volledig verzonnen door het model."'
        annotated, report, notes = apply_citation_verification(
            answer,
            evidence_texts={"knowledge:src1": SOURCE_PASSAGE},
            sources_used=True,
        )
        self.assertTrue(report["has_invented_citation"])
        self.assertIn("[HADES citaatcontrole]", annotated)
        self.assertTrue(any(n.startswith("invented_citations:") for n in notes))


if __name__ == "__main__":
    unittest.main()
