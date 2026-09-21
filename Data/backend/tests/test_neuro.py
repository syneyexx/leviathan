from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from Data.modules.memory import MemoryKind, MemoryStore
from Data.modules.neuro import (
    CortexPlanner,
    NeuroAdvisor,
    NeuroMemoryFacade,
    ProcessCritic,
    UnsupportedResidualRuntime,
)
from Data.modules.neuro.residual import ResidualForwardRequest, ResidualHookPoint, ResidualInjectRequest
from Data.modules.reasoning import ReasoningPlan


class NeuroLayerPhase46Tests(unittest.TestCase):
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
        self.assertGreaterEqual(critic.strength, 0.0)
        self.assertTrue(critic.public_dict()["truth"]["advisory_only"])

    def test_residual_injection_honest_unimplemented(self) -> None:
        advisor = NeuroAdvisor(enabled=True, residual_injection=True)
        result = advisor.assess("hello")
        residual = next(s for s in result.signals if s.kind == "residual_injection")
        self.assertFalse(residual.provenance.get("implemented"))

    def test_unsupported_residual_runtime(self) -> None:
        runtime = UnsupportedResidualRuntime()
        self.assertFalse(runtime.supports_residuals())
        hook = ResidualHookPoint(layer_index=12, name="block_12")
        receipt = runtime.inject(
            ResidualInjectRequest(hook=hook, mode="ADDITIVE", scale=0.1, source="test")
        )
        self.assertFalse(receipt.implemented)
        self.assertFalse(receipt.applied)
        forward = runtime.run_forward(ResidualForwardRequest(messages=[{"role": "user", "content": "x"}]))
        self.assertTrue(forward.degraded_to_chat_completions)
        self.assertIsNone(forward.text)

    def test_cortex_planner_lean_vs_complex(self) -> None:
        planner = CortexPlanner(enabled=True, max_depth=2)
        lean = planner.plan(
            ReasoningPlan(intent="chat", complexity="low", use_knowledge=False, steps=("respond",))
        )
        self.assertFalse(lean.engage)
        complex_plan = planner.plan(
            ReasoningPlan(intent="research", complexity="high", use_knowledge=True, steps=("search", "verify")),
            residual_available=False,
            memory_tiers_enabled=True,
            process_critic_enabled=True,
        )
        self.assertTrue(complex_plan.engage)
        self.assertIn(1, complex_plan.use_memory_tiers)

    def test_process_critic_grounding_with_ids(self) -> None:
        critic = ProcessCritic(enabled=True)
        score = critic.score(
            "Based on doc-123 the answer is 42",
            plan_steps=("search",),
            knowledge_ids=("doc-123",),
        )
        self.assertGreater(score.factual_grounding, 0.4)
        self.assertEqual(score.method, "lexical_grounding_ids")

    def test_memory_facade_tier0_and_tier1(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = MemoryStore(Path(tmp) / "mem.db")
            store.initialize()
            facade = NeuroMemoryFacade(enabled=True, memory_store=store)
            facade.write_working("hot residual hint about reactors")
            facade.write_episodic(
                "decision: use gateway for side effects",
                kind=MemoryKind.DECISION,
                trust="explicit",
            )
            bundle = facade.retrieve("reactors gateway", tiers=(0, 1), limit_per_tier=5)
            self.assertTrue(bundle.hits)
            tiers = {hit.tier for hit in bundle.hits}
            self.assertTrue(0 in tiers or 1 in tiers)
            self.assertTrue(bundle.public_dict()["truth"]["memory_facade_does_not_fork_stores"])

    def test_memory_facade_refuses_when_disabled(self) -> None:
        facade = NeuroMemoryFacade(enabled=False)
        with self.assertRaises(RuntimeError):
            facade.write_working("x")

    def test_memory_store_rejects_model_output_via_facade(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = MemoryStore(Path(tmp) / "mem.db")
            store.initialize()
            facade = NeuroMemoryFacade(enabled=True, memory_store=store)
            with self.assertRaises(ValueError):
                facade.write_episodic("hallucination", trust="model_output")


if __name__ == "__main__":
    unittest.main()
