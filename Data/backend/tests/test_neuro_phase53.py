"""Phase 53+ Neuro Layer — residual orchestrator, cortex blocks, adapters, honesty."""

from __future__ import annotations

import os
import tempfile
import unittest
from unittest import mock

from Data.backend.config import ConfigurationError, Settings
from Data.modules.neuro import (
    CortexRuntime,
    DeterministicResidualRuntime,
    LlamaCppResidualAdapter,
    NeuroSoakHarness,
    ProcessCritic,
    ResidualOrchestrator,
    TrtResidualAdapter,
    UnsupportedResidualRuntime,
    VllmResidualAdapter,
    build_residual_runtime,
)
from Data.modules.neuro.residual import ResidualHookPoint, ResidualInjectRequest
from Data.modules.training import (
    EphemeralRecipeWorkerTrainer,
    FixtureRecipeTrainer,
    TrainingRecipeRegistry,
    build_neuro_recipe_trainer,
)


class Phase53ResidualOrchestratorTests(unittest.TestCase):
    def test_orchestrator_disabled_is_honest(self) -> None:
        port = DeterministicResidualRuntime(n_layers=6, hidden_size=8)
        orch = ResidualOrchestrator(residual_port=port, enabled=False)
        report = orch.orchestrate(complexity="high", run_forward=False)
        self.assertFalse(report.enabled)
        self.assertEqual(report.plans, ())
        truth = report.public_dict()["truth"]
        self.assertTrue(truth["neural_signal_is_not_authority"])
        self.assertTrue(truth["unapplied_is_not_success"])

    def test_orchestrator_plans_mid_late_and_applies_on_toy(self) -> None:
        port = DeterministicResidualRuntime(n_layers=9, hidden_size=8)
        orch = ResidualOrchestrator(
            residual_port=port,
            enabled=True,
            base_scale=0.1,
            max_injects=3,
        )
        report = orch.orchestrate(
            messages=[{"role": "user", "content": "plan residual"}],
            complexity="high",
            token_budget=9000,
            run_forward=True,
        )
        self.assertTrue(report.enabled)
        self.assertTrue(report.residual_available)
        self.assertGreaterEqual(len(report.plans), 1)
        self.assertTrue(any(r.applied for r in report.receipts))
        self.assertIsNotNone(report.forward)
        self.assertFalse(report.forward.degraded_to_chat_completions)  # type: ignore[union-attr]

    def test_orchestrator_unsupported_runtime_receipts_not_success(self) -> None:
        orch = ResidualOrchestrator(
            residual_port=UnsupportedResidualRuntime(),
            enabled=True,
        )
        # Force a synthetic plan via hook_layers against empty hooks → no plans.
        report = orch.orchestrate(complexity="medium")
        self.assertTrue(report.enabled)
        self.assertFalse(report.residual_available)
        self.assertEqual(report.plans, ())
        for receipt in report.receipts:
            self.assertFalse(receipt.applied)

    def test_hook_layer_override(self) -> None:
        port = DeterministicResidualRuntime(n_layers=8, hidden_size=4)
        orch = ResidualOrchestrator(
            residual_port=port,
            enabled=True,
            hook_layers=(1, 6),
        )
        plans = orch.plan_injects(complexity="medium")
        layers = [p.hook.layer_index for p in plans]
        self.assertEqual(layers, [1, 6])


class Phase53AdapterHonestyTests(unittest.TestCase):
    def test_vllm_health_ok_is_not_residual_support(self) -> None:
        adapter = VllmResidualAdapter(endpoint=None)
        self.assertFalse(adapter.supports_residuals())
        info = adapter.runtime_info()
        self.assertTrue(info["truth"]["health_ok_is_not_residual_support"])

    def test_vllm_hooks_confirmed_via_probe(self) -> None:
        with mock.patch(
            "Data.modules.neuro.adapters._http_json_get",
            return_value={
                "supports_residuals": True,
                "hooks": [{"layer_index": 2, "name": "mid"}, {"layer_index": 10, "name": "late"}],
            },
        ):
            adapter = VllmResidualAdapter(endpoint="http://127.0.0.1:9000")
        self.assertTrue(adapter.supports_residuals())
        self.assertEqual(len(adapter.list_hook_points()), 2)
        with mock.patch(
            "Data.modules.neuro.adapters._http_json_post",
            return_value={"applied": True, "detail": "ok", "reason": "applied_vllm"},
        ):
            receipt = adapter.inject(
                ResidualInjectRequest(
                    hook=ResidualHookPoint(2, "mid"),
                    mode="ADDITIVE",
                    scale=0.1,
                )
            )
        self.assertTrue(receipt.implemented)
        self.assertTrue(receipt.applied)

    def test_llama_and_trt_default_unsupported(self) -> None:
        llama = LlamaCppResidualAdapter(model_path="/tmp/x.gguf", selected_layers=(1, 2))
        self.assertFalse(llama.supports_residuals())
        self.assertEqual(len(llama.list_hook_points()), 2)
        trt = TrtResidualAdapter(engine_path="/tmp/engine")
        self.assertFalse(trt.supports_residuals())
        receipt = trt.inject(
            ResidualInjectRequest(hook=ResidualHookPoint(0, "t0"), mode="ADDITIVE", scale=0.2)
        )
        self.assertFalse(receipt.applied)
        self.assertTrue(receipt.degraded_to_chat_completions)

    def test_build_residual_runtime_trt(self) -> None:
        runtime = build_residual_runtime(kind="trt")
        self.assertFalse(runtime.supports_residuals())
        self.assertEqual(runtime.runtime_info()["kind"], "trt")


class Phase53CortexBlockTests(unittest.TestCase):
    def test_named_blocks_and_early_exit(self) -> None:
        port = DeterministicResidualRuntime(n_layers=8, hidden_size=8)
        # Floors very low so first critic round early-exits.
        cortex = CortexRuntime(
            residual_port=port,
            critic=ProcessCritic(enabled=True),
            max_k=3,
            consistency_floor=0.0,
            grounding_floor=0.0,
            named_blocks_enabled=True,
            early_exit_enabled=True,
        )
        report = cortex.run(
            messages=[{"role": "user", "content": "cite evid-1 for the claim"}],
            depth=2,
            critic_rounds=3,
            evidence_ids=("evid-1",),
            knowledge_ids=("doc-1",),
        )
        self.assertTrue(report.engaged)
        self.assertTrue(any(b.circuit != "generic" for b in report.blocks))
        self.assertTrue(report.early_exit)
        self.assertLessEqual(report.k_used, report.max_k)
        self.assertTrue(report.public_dict()["truth"]["depth_is_not_authority"])

    def test_max_k_caps_critic_rounds(self) -> None:
        port = DeterministicResidualRuntime(n_layers=6, hidden_size=8)
        cortex = CortexRuntime(
            residual_port=port,
            critic=ProcessCritic(enabled=True),
            max_k=1,
            consistency_floor=0.99,
            grounding_floor=0.99,
            early_exit_enabled=False,
        )
        report = cortex.run(
            messages=[{"role": "user", "content": "no citations here"}],
            depth=1,
            critic_rounds=5,
        )
        self.assertEqual(report.max_k, 1)
        self.assertLessEqual(report.k_used, 1)


class Phase53TrainingWorkerTests(unittest.TestCase):
    def test_fixture_trainer_selected_by_default(self) -> None:
        trainer = build_neuro_recipe_trainer(real_worker=False)
        self.assertIsInstance(trainer, FixtureRecipeTrainer)

    def test_ephemeral_worker_trainer_runs_externally(self) -> None:
        trainer = build_neuro_recipe_trainer(real_worker=True)
        self.assertIsInstance(trainer, EphemeralRecipeWorkerTrainer)
        registry = TrainingRecipeRegistry(trainer=trainer)
        run = registry.execute(
            "contrastive_memory_v1",
            samples=[{"x": 1, "critic_approved": True}],
        )
        self.assertEqual(run.status.value, "COMPLETED")
        self.assertTrue(run.metrics)
        self.assertEqual(run.metrics.get("worker"), "ephemeral_subprocess")
        self.assertTrue(run.metrics.get("truth", {}).get("external_worker_execution"))


class Phase53SoakAndConfigTests(unittest.TestCase):
    def test_long_soak_requires_flag(self) -> None:
        harness = NeuroSoakHarness(long_soak_enabled=False)
        with self.assertRaises(ValueError):
            harness.run(iterations=2, mode="long", steps=[("noop", lambda: "ok")])

    def test_long_soak_when_enabled(self) -> None:
        harness = NeuroSoakHarness(long_soak_enabled=True)
        report = harness.run(iterations=2, mode="long", steps=[("noop", lambda: "ok")])
        self.assertEqual(report.mode, "long")
        self.assertTrue(report.long_soak_enabled)
        self.assertTrue(report.public_dict()["truth"]["long_soak_is_not_multi_hour_slo_claim"])

    def test_child_flags_require_neuro_parent(self) -> None:
        cases = [
            {"LEVIATHAN_FEATURE_NEURO_RESIDUAL_ORCHESTRATOR": "true"},
            {"LEVIATHAN_FEATURE_NEURO_CORTEX_BLOCKS": "true", "LEVIATHAN_FEATURE_NEURO_CORTEX": "true"},
            {"LEVIATHAN_FEATURE_NEURO_CONTRASTIVE_TRAINING": "true"},
            {"LEVIATHAN_FEATURE_NEURO_SOAK_LONG": "true"},
            {"LEVIATHAN_NEURO_TRAINING_REAL_WORKER": "true"},
        ]
        for env in cases:
            with self.subTest(env=env):
                with mock.patch.dict(os.environ, {"LEVIATHAN_FEATURE_NEURO": "false", **env}, clear=False):
                    with self.assertRaises(ConfigurationError):
                        Settings.from_env()

    def test_cortex_blocks_requires_cortex(self) -> None:
        env = {
            "LEVIATHAN_FEATURE_NEURO": "true",
            "LEVIATHAN_FEATURE_NEURO_CORTEX": "false",
            "LEVIATHAN_FEATURE_NEURO_CORTEX_BLOCKS": "true",
        }
        with mock.patch.dict(os.environ, env, clear=False):
            with self.assertRaises(ConfigurationError):
                Settings.from_env()

    def test_hook_layers_and_cortex_max_k_parse(self) -> None:
        env = {
            "LEVIATHAN_FEATURE_NEURO": "true",
            "LEVIATHAN_NEURO_RESIDUAL_HOOK_LAYERS": "2, 5, 9",
            "LEVIATHAN_NEURO_CORTEX_MAX_K": "3",
            "LEVIATHAN_NEURO_MEMORY_TIER0_MAX_SLOTS": "32",
            "LEVIATHAN_NEURO_RESIDUAL_KIND": "trt",
        }
        with mock.patch.dict(os.environ, env, clear=False):
            cfg = Settings.from_env()
        self.assertEqual(cfg.neuro_runtime.residual_hook_layers, (2, 5, 9))
        self.assertEqual(cfg.neuro_runtime.cortex_max_k, 3)
        self.assertEqual(cfg.neuro_runtime.memory_tier0_max_slots, 32)
        self.assertEqual(cfg.neuro_runtime.residual_kind, "trt")
        summary = cfg.public_summary()
        self.assertIn("neuro_residual_orchestrator", summary["features"])


if __name__ == "__main__":
    unittest.main()
