"""Strategy family registry — single source of truth for learner-generatable DSL kinds."""

from __future__ import annotations

import unittest

from Data.modules.market_sim import learning_types
from Data.modules.market_sim.learning_candidates import FAMILY_TEMPLATES
from Data.modules.market_sim.strategy_families import (
    SUPPORTED_STRATEGY_FAMILIES,
    assert_family_registry_covers_dsl,
    family_templates,
    research_generatable_families,
)


class StrategyFamiliesRegistryTests(unittest.TestCase):
    def test_assert_family_registry_covers_dsl_empty(self) -> None:
        missing = assert_family_registry_covers_dsl()
        self.assertEqual(missing, [])

    def test_research_generatable_excludes_hold(self) -> None:
        generatable = research_generatable_families()
        self.assertTrue(generatable)
        self.assertNotIn("hold", generatable)
        self.assertEqual(tuple(SUPPORTED_STRATEGY_FAMILIES), tuple(generatable))

    def test_family_templates_keys_match_generatable(self) -> None:
        templates = family_templates()
        generatable = set(research_generatable_families())
        self.assertEqual(set(templates.keys()), generatable)
        self.assertEqual(set(FAMILY_TEMPLATES.keys()), generatable)
        self.assertNotIn("hold", templates)

    def test_learning_types_supported_same_source(self) -> None:
        self.assertEqual(
            tuple(learning_types.SUPPORTED_STRATEGY_FAMILIES),
            tuple(SUPPORTED_STRATEGY_FAMILIES),
        )
        # Same object when imported from strategy_families into learning_types
        self.assertIs(
            learning_types.SUPPORTED_STRATEGY_FAMILIES,
            SUPPORTED_STRATEGY_FAMILIES,
        )


if __name__ == "__main__":
    unittest.main()
