"""T16 / W09 adversarial — unsupported markets + research citation language."""

from __future__ import annotations

import unittest

from Data.modules.market_sim.instruments import (
    CapabilityState,
    InstrumentFamily,
    family_capability,
    infer_family,
    spec_for_symbol,
    support_matrix,
)
from Data.modules.research.citation_audit import _looks_factual, _looks_interpretation


class UnsupportedMarketFamilyTests(unittest.TestCase):
    def test_t16_options_futures_forex_explicit_not_equity(self) -> None:
        """Options stay NOT_IMPLEMENTED; futures/FX may be AVAILABLE but never silently equity."""
        opt = spec_for_symbol("AAPL", metadata={"family": "options"})
        self.assertEqual(opt.family, InstrumentFamily.OPTIONS)
        self.assertEqual(opt.metadata.get("capability"), CapabilityState.NOT_IMPLEMENTED.value)
        self.assertNotEqual(opt.family, InstrumentFamily.EQUITY)

        fut = spec_for_symbol("ES", metadata={"family": "futures"})
        self.assertEqual(fut.family, InstrumentFamily.FUTURES)
        self.assertNotEqual(fut.family, InstrumentFamily.EQUITY)
        self.assertEqual(family_capability(fut.family), CapabilityState.AVAILABLE)

        fx = infer_family("EURUSD", metadata={"instrument_type": "forex"})
        self.assertEqual(fx, InstrumentFamily.FOREX)
        self.assertNotEqual(fx, InstrumentFamily.EQUITY)
        self.assertEqual(family_capability(fx), CapabilityState.AVAILABLE)

        matrix = support_matrix()
        by_fam = {r["family"]: r for r in matrix["families"]}
        self.assertTrue(by_fam["equity"]["end_to_end"])
        self.assertFalse(by_fam["options"]["end_to_end"])
        self.assertEqual(by_fam["options"]["capability"], "NOT_IMPLEMENTED")
        self.assertEqual(by_fam["futures"]["capability"], "AVAILABLE")
        self.assertEqual(by_fam["forex"]["capability"], "AVAILABLE")


class ResearchCitationLanguageTests(unittest.TestCase):
    def test_dutch_factual_sentence_detected(self) -> None:
        sentence = "Het bedrijf heeft in 2024 een nieuwe versie aangekondigd voor het platform."
        self.assertTrue(_looks_factual(sentence))

    def test_hedging_does_not_clear_factual_duty(self) -> None:
        # Contains hedge ("might") AND factual marker (increased + percent digits).
        sentence = "Revenue might have increased by 12 percent according to the filing."
        self.assertTrue(_looks_factual(sentence))
        self.assertFalse(_looks_interpretation(sentence))

    def test_pure_interpretation_without_facts(self) -> None:
        sentence = "Overall this seems like a reasonable interpretation of the situation."
        self.assertTrue(_looks_interpretation(sentence))
        self.assertFalse(_looks_factual(sentence))


if __name__ == "__main__":
    unittest.main()
