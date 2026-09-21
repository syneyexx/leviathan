from __future__ import annotations

import unittest

from Data.modules.neuro import NeuroAdvisor


class NeuroAdvisorTests(unittest.TestCase):
    def test_disabled_emits_no_signals(self) -> None:
        advisor = NeuroAdvisor(enabled=False)
        result = advisor.assess("delete everything now")
        self.assertFalse(result.enabled)
        self.assertEqual(result.signals, ())
        self.assertTrue(result.public_dict()["truth"]["neural_signal_is_not_authority"])

    def test_process_critic_is_advisory_only(self) -> None:
        advisor = NeuroAdvisor(enabled=True, process_critic=True)
        result = advisor.assess("please delete the archive")
        self.assertTrue(result.enabled)
        kinds = [s.kind for s in result.signals]
        self.assertIn("process_critic", kinds)
        critic = next(s for s in result.signals if s.kind == "process_critic")
        self.assertGreaterEqual(critic.strength, 0.5)
        self.assertTrue(critic.public_dict()["truth"]["advisory_only"])

    def test_residual_injection_honest_unimplemented(self) -> None:
        advisor = NeuroAdvisor(enabled=True, residual_injection=True)
        result = advisor.assess("hello")
        residual = next(s for s in result.signals if s.kind == "residual_injection")
        self.assertFalse(residual.provenance.get("implemented"))


if __name__ == "__main__":
    unittest.main()
