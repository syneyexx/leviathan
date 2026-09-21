"""T5/F-06: neural READ must not replace LM provider content as primary."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from reasoning.runtime_selection import (
    NeuralRequirement,
    RuntimeKind,
    RuntimeSelectionRequest,
    select_model_runtime,
    should_fail_closed,
)


class NeuralReadHonestyTests(unittest.TestCase):
    def test_read_refuses_neural_primary_even_when_capable(self) -> None:
        decision = select_model_runtime(
            RuntimeSelectionRequest(
                neural_mode="read",
                allow_neural=True,
                neural_available=True,
                neural_ready=True,
                neural_requirement=NeuralRequirement.PREFERRED,
                shadow_sample_rate=0.0,
            )
        )
        self.assertEqual(decision.primary, RuntimeKind.STANDARD)
        self.assertEqual(decision.neural_mode, "off")
        self.assertEqual(decision.fallback_reason, "neural_read_not_product_ready")
        self.assertTrue(decision.detail.get("research_only"))
        self.assertTrue(decision.detail.get("not_product_ready"))
        self.assertFalse(should_fail_closed(decision))

    def test_read_required_fail_closed(self) -> None:
        decision = select_model_runtime(
            RuntimeSelectionRequest(
                neural_mode="read",
                allow_neural=True,
                neural_available=True,
                neural_ready=True,
                neural_requirement=NeuralRequirement.REQUIRED,
                shadow_sample_rate=0.0,
            )
        )
        self.assertEqual(decision.primary, RuntimeKind.STANDARD)
        self.assertTrue(should_fail_closed(decision))

    def test_shadow_still_keeps_standard_primary(self) -> None:
        decision = select_model_runtime(
            RuntimeSelectionRequest(
                neural_mode="shadow",
                allow_neural=True,
                neural_available=True,
                neural_ready=True,
                neural_requirement=NeuralRequirement.PREFERRED,
                shadow_sample_rate=1.0,
            )
        )
        self.assertEqual(decision.primary, RuntimeKind.STANDARD)
        self.assertEqual(decision.neural_mode, "shadow")
        self.assertTrue(decision.shadow)


if __name__ == "__main__":
    unittest.main()
