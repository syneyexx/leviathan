"""W5 — Neural task advisor, hypothesis board integration, critic mesh."""

from __future__ import annotations

import unittest

from Data.modules.cognition.critics import CriticMesh, IntegrityCritic
from Data.modules.cognition.hypotheses import HypothesisBoard, HypothesisStatus
from Data.modules.cognition.neural_advisor import NeuralTaskModelAdvisor, TaskAdvice
from Data.modules.cognition.task_model import TaskModelBuilder


class NeuralAdvisorTests(unittest.TestCase):
    def test_heuristic_fallback_is_labeled(self) -> None:
        advice = NeuralTaskModelAdvisor().advise("hi")
        self.assertEqual(advice.source, "heuristic_fallback")
        self.assertTrue(advice.public_dict()["truth"]["fallback_is_labeled"])

    def test_neural_path_when_model_returns_json(self) -> None:
        def caller(**kwargs):
            return {
                "text": (
                    '{"task_type":"research_comparison","domain":"research",'
                    '"freshness":"required","required_tools":["research"],'
                    '"required_evidence":["sources"],"risk":"MEDIUM","ambiguity":0.7,'
                    '"language":"en","research_need":"deep","verification_need":"required"}'
                )
            }

        advice = NeuralTaskModelAdvisor(model_caller=caller).advise(
            "Compare the latest agent runtimes with sources"
        )
        self.assertEqual(advice.source, "neural")
        self.assertEqual(advice.research_need, "deep")
        self.assertEqual(advice.freshness, "required")

        task = TaskModelBuilder().build("Compare the latest agent runtimes with sources")
        task.metadata = {"allow_neural_task_override": True}
        updated = NeuralTaskModelAdvisor(model_caller=caller).apply_to_task(task, advice)
        self.assertTrue(updated.requires_research)
        self.assertEqual(updated.metadata["task_advice"]["source"], "neural")


class HypothesisBoardTests(unittest.TestCase):
    def test_board_tracks_support_and_contradiction(self) -> None:
        board = HypothesisBoard()
        hyp = board.add("reconnect drops pending calls", prior_plausibility=0.6)
        hyp.apply_evidence("ev-1", supports=True)
        hyp.apply_evidence("ev-2", supports=True)
        self.assertEqual(hyp.current_status, HypothesisStatus.SUPPORTED)
        hyp.apply_evidence("ev-3", supports=False)
        self.assertEqual(hyp.current_status, HypothesisStatus.UNRESOLVED)
        self.assertGreaterEqual(board.public_dict()["open_count"], 1)


class CriticMeshTests(unittest.TestCase):
    def test_mesh_flags_fabricated_and_is_not_verification(self) -> None:
        report = CriticMesh().run(
            text="I ran the tests and fixed everything.",
            plan_steps=["inspect failure", "patch", "verify with tests"],
            acceptance=["tests green"],
            domain="coding",
            require_evidence=True,
        )
        self.assertTrue(report.public_dict()["truth"]["critic_is_not_verification_proof"])
        self.assertTrue(report.findings)
        self.assertIn(report.recommend, {"replan", "verify", "continue", "stop"})

    def test_integrity_critic_technical_only(self) -> None:
        finding = IntegrityCritic().critique(
            text="Voters debated climate policy extensively."
        )
        self.assertIsNone(finding)
        leak = IntegrityCritic().critique(text="api_key=sk-secret-12345")
        self.assertIsNotNone(leak)
        self.assertEqual(leak.severity, "high")


if __name__ == "__main__":
    unittest.main()
