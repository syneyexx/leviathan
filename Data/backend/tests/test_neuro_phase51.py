from __future__ import annotations

import unittest

from Data.modules.context import ContextBuilder
from Data.modules.neuro import (
    DeterministicResidualRuntime,
    NeuroSoakHarness,
    VllmResidualAdapter,
    build_residual_runtime,
)
from Data.modules.reasoning import ReasoningEngine
from Data.modules.training import PreferenceBridge, TrainingRegistry
from Data.modules.verification.types import VerificationOutcome, VerificationReport


class Phase51CompletionTests(unittest.TestCase):
    def test_context_includes_neuro_advisory_section(self) -> None:
        plan = ReasoningEngine().analyze("hello", has_knowledge=False)
        pack = ContextBuilder().build(
            history=[{"role": "user", "content": "hello"}],
            knowledge=[],
            plan=plan,
            neuro=[{"id": "n1", "content": "[process_critic] advisory hint", "status": "advisory"}],
        )
        # Neuro is untrusted reference data (not system authority) — appears in
        # packed sections / user-turn references, never elevated into system role.
        blob = "\n".join(m.get("content", "") for m in pack.messages)
        section_blob = "\n".join(
            getattr(s, "content", "") for s in getattr(pack, "sections", []) or []
        )
        combined = blob + "\n" + section_blob
        self.assertTrue(
            "Neuro advisory" in combined
            or "neuro_advisory" in combined
            or "process_critic" in combined
            or any(getattr(s, "kind", "") == "neuro" for s in getattr(pack, "sections", []) or []),
            msg=f"neuro advisory missing from pack; system={pack.messages[0]['content'][:200]!r}",
        )
        self.assertIn("process_critic", combined)

    def test_vllm_and_llama_stubs_are_honest(self) -> None:
        vllm = build_residual_runtime(kind="vllm")
        llama = build_residual_runtime(kind="llama_cpp")
        self.assertFalse(vllm.supports_residuals())
        self.assertFalse(llama.supports_residuals())
        self.assertIsInstance(vllm, VllmResidualAdapter)

    def test_preference_bridge_registers_from_verification(self) -> None:
        registry = TrainingRegistry()
        bridge = PreferenceBridge(registry)
        reports = [
            VerificationReport(
                report_id="r1",
                outcome=VerificationOutcome.PASSED,
                created_at="2026-01-01T00:00:00+00:00",
                requirements=(),
            ),
            VerificationReport(
                report_id="r2",
                outcome=VerificationOutcome.UNMEASURED,
                created_at="2026-01-01T00:00:00+00:00",
                requirements=(),
            ),
        ]
        jobs = bridge.register_from_verification_reports(reports)
        self.assertEqual(len(jobs), 1)
        self.assertIn("r1", jobs[0].name)
        self.assertTrue(jobs[0].public_dict()["truth"]["registered_is_not_trained"])

    def test_mini_soak_harness(self) -> None:
        harness = NeuroSoakHarness()
        runtime = DeterministicResidualRuntime(n_layers=2, hidden_size=8)
        report = harness.run(
            iterations=2,
            steps=[
                ("residual", lambda: f"ok={runtime.supports_residuals()}"),
                ("fail_once", lambda: (_ for _ in ()).throw(RuntimeError("boom"))),
            ],
        )
        self.assertEqual(report.iterations, 2)
        self.assertEqual(report.passed, 2)
        self.assertEqual(report.failed, 2)
        self.assertTrue(report.public_dict()["truth"]["mini_soak_is_not_production_slo"])


if __name__ == "__main__":
    unittest.main()
