"""Phase 54 — residual production path, contrastive InfoNCE, chat SSE streaming."""

from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from Data.backend.config import ConfigurationError, Settings
from Data.modules.knowledge.embeddings import LocalHashEmbeddingProvider
from Data.modules.memory import MemoryKind, MemoryStore
from Data.modules.model_runtime.streaming import (
    chat_truth,
    extract_delta_text,
    parse_openai_sse_line,
    sse_encode,
)
from Data.modules.neuro import (
    ContrastiveRetrievalHead,
    DeterministicResidualRuntime,
    LlamaCppResidualAdapter,
    NeuroMemoryFacade,
    ResidualOrchestrator,
    UnsupportedResidualRuntime,
    VllmResidualAdapter,
)
from Data.modules.neuro.residual import ResidualHookPoint, ResidualInjectRequest
from Data.modules.training import (
    EphemeralRecipeWorkerTrainer,
    TrainingRecipeRegistry,
    build_neuro_recipe_trainer,
)


class Phase54ResidualProductionTests(unittest.TestCase):
    def test_vllm_probe_inject_receipt_honesty(self) -> None:
        with mock.patch(
            "Data.modules.neuro.adapters._http_json_get",
            return_value={
                "supports_residuals": True,
                "hooks": [{"layer_index": 4, "name": "mid"}, {"layer_index": 12, "name": "late"}],
            },
        ):
            adapter = VllmResidualAdapter(endpoint="http://127.0.0.1:9001")
        self.assertTrue(adapter.supports_residuals())
        self.assertFalse(adapter.supports_streaming_forward())
        with mock.patch(
            "Data.modules.neuro.adapters._http_json_post",
            return_value={"applied": True, "detail": "ok", "reason": "applied_vllm"},
        ):
            receipt = adapter.inject(
                ResidualInjectRequest(
                    hook=ResidualHookPoint(4, "mid"),
                    mode="ADDITIVE",
                    scale=0.1,
                )
            )
        self.assertTrue(receipt.implemented)
        self.assertTrue(receipt.applied)
        truth = receipt.public_dict()["truth"]
        self.assertTrue(truth["residual_implemented"])
        self.assertTrue(truth["residual_applied"])
        self.assertTrue(truth["unapplied_is_not_success"])

    def test_vllm_unsupported_degrades_to_chat(self) -> None:
        adapter = VllmResidualAdapter(endpoint=None)
        receipt = adapter.inject(
            ResidualInjectRequest(hook=ResidualHookPoint(0, "x"), mode="ADDITIVE", scale=0.2)
        )
        self.assertFalse(receipt.applied)
        self.assertTrue(receipt.degraded_to_chat_completions)
        info = adapter.runtime_info()
        self.assertTrue(info["truth"]["health_ok_is_not_residual_support"])

    def test_llama_forward_when_hooks_confirmed(self) -> None:
        with mock.patch(
            "Data.modules.neuro.adapters._http_json_get",
            return_value={"supports_residuals": True, "hooks": [1, 8]},
        ):
            adapter = LlamaCppResidualAdapter(server_url="http://127.0.0.1:8080")
        self.assertTrue(adapter.supports_residuals())
        with mock.patch(
            "Data.modules.neuro.adapters._http_json_post",
            return_value={
                "implemented": True,
                "text": "hello from residual",
                "reason": "llama_forward",
                "degraded_to_chat_completions": False,
            },
        ):
            from Data.modules.neuro.residual import ResidualForwardRequest

            result = adapter.run_forward(
                ResidualForwardRequest(messages=[{"role": "user", "content": "hi"}])
            )
        self.assertTrue(result.implemented)
        self.assertEqual(result.text, "hello from residual")
        self.assertFalse(result.degraded_to_chat_completions)


class Phase54OrchestratorTests(unittest.TestCase):
    def test_layer_selection_and_alpha_budget(self) -> None:
        port = DeterministicResidualRuntime(n_layers=9, hidden_size=8)
        orch = ResidualOrchestrator(
            residual_port=port,
            enabled=True,
            base_scale=0.2,
            max_total_alpha=0.3,
            max_injects=3,
        )
        report = orch.orchestrate(
            messages=[{"role": "user", "content": "complex residual"}],
            complexity="high",
            token_budget=9000,
            run_forward=True,
        )
        self.assertTrue(report.enabled)
        self.assertGreaterEqual(len(report.plans), 1)
        self.assertLessEqual(report.alpha_used, report.alpha_budget + 1e-6)
        self.assertTrue(any(r.applied for r in report.receipts))
        truth = report.public_dict()["truth"]
        self.assertTrue(truth["residual_applied"])
        self.assertTrue(truth["streaming_degraded"])  # toy has no streaming forward
        self.assertIn("alpha_budget_hits", orch.telemetry)

    def test_multi_inject_coordination(self) -> None:
        port = DeterministicResidualRuntime(n_layers=6, hidden_size=4)
        orch = ResidualOrchestrator(
            residual_port=port,
            enabled=True,
            hook_layers=(1, 3, 5),
            base_scale=0.1,
        )
        plans = orch.plan_injects(complexity="medium")
        self.assertEqual([p.hook.layer_index for p in plans], [1, 3, 5])
        report = orch.orchestrate(complexity="medium", run_forward=False)
        self.assertEqual(len(report.receipts), 3)

    def test_unsupported_truth_fields(self) -> None:
        orch = ResidualOrchestrator(
            residual_port=UnsupportedResidualRuntime(),
            enabled=True,
        )
        report = orch.orchestrate(complexity="high")
        truth = report.public_dict()["truth"]
        self.assertFalse(truth["residual_applied"])
        self.assertTrue(truth["unsupported_is_not_failure_of_core"])
        self.assertTrue(truth["neural_signal_is_not_authority"])


class Phase54ContrastiveTests(unittest.TestCase):
    def test_embedding_infonce_and_lexical_fallback(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            mem = MemoryStore(Path(tmp) / "m.db")
            mem.initialize()
            facade = NeuroMemoryFacade(enabled=True, memory_store=mem)
            facade.write_episodic("gateway residual evidence", kind=MemoryKind.DECISION)
            lexical = ContrastiveRetrievalHead(facade, embeddings_available=False)
            lreport = lexical.retrieve("gateway")
            self.assertEqual(lreport.method, "lexical")
            self.assertFalse(lreport.measured)
            self.assertTrue(lreport.public_dict()["truth"]["unmeasured_is_not_passed"])

            provider = LocalHashEmbeddingProvider(dimensions=32)
            vector = ContrastiveRetrievalHead(facade, embedding_provider=provider)
            vreport = vector.retrieve("gateway")
            self.assertEqual(vreport.method, "embedding")
            self.assertTrue(vreport.measured)
            if vreport.hits:
                self.assertIn("infonce_weight", vreport.hits[0])
                self.assertIn("contrastive_score", vreport.hits[0])


class Phase54TrainingWorkerTests(unittest.TestCase):
    def test_contrastive_recipe_status_machine_no_fake_completed(self) -> None:
        trainer = build_neuro_recipe_trainer(real_worker=True)
        self.assertIsInstance(trainer, EphemeralRecipeWorkerTrainer)
        registry = TrainingRecipeRegistry(trainer=trainer)
        run = registry.execute(
            "contrastive_memory_v1",
            samples=[{"q": "a", "pos": "b", "neg": "c"}],
        )
        self.assertEqual(run.status.value, "COMPLETED")
        self.assertTrue(run.metrics)
        self.assertEqual(run.metrics.get("worker"), "ephemeral_subprocess")

    def test_no_trainer_does_not_fabricate_completed(self) -> None:
        registry = TrainingRecipeRegistry(trainer=None)
        run = registry.execute("contrastive_memory_v1", samples=[{"x": 1}])
        self.assertEqual(run.status.value, "FAILED")
        self.assertEqual(run.metrics, {})


class Phase54StreamingHelpersTests(unittest.TestCase):
    def test_sse_encode_and_truth(self) -> None:
        block = sse_encode("token", {"text": "hello"})
        self.assertIn("event: token", block)
        self.assertIn("data: {\"text\":\"hello\"}", block)
        self.assertTrue(block.endswith("\n\n"))
        truth = chat_truth(streaming_degraded=True, residual_applied=False)
        self.assertTrue(truth["streaming_degraded"])
        self.assertTrue(truth["model_output_is_not_evidence"])
        self.assertFalse(truth["residual_applied"])

    def test_parse_openai_sse(self) -> None:
        self.assertEqual(parse_openai_sse_line("data: [DONE]"), {"_done": True})
        chunk = parse_openai_sse_line(
            'data: {"choices":[{"delta":{"content":"Hi"}}]}'
        )
        assert chunk is not None
        self.assertEqual(extract_delta_text(chunk), "Hi")


class Phase54FlagValidationTests(unittest.TestCase):
    def test_chat_sse_requires_chat_streaming(self) -> None:
        env = {
            "LEVIATHAN_FEATURE_CHAT_STREAMING": "false",
            "LEVIATHAN_FEATURE_CHAT_SSE": "true",
        }
        with mock.patch.dict(os.environ, env, clear=False):
            with self.assertRaises(ConfigurationError):
                Settings.from_env()

    def test_chat_streaming_flags_parse(self) -> None:
        env = {
            "LEVIATHAN_FEATURE_CHAT_STREAMING": "true",
            "LEVIATHAN_FEATURE_CHAT_SSE": "true",
        }
        with mock.patch.dict(os.environ, env, clear=False):
            cfg = Settings.from_env()
        self.assertTrue(cfg.features.chat_streaming)
        self.assertTrue(cfg.features.chat_sse)
        summary = cfg.public_summary()
        self.assertTrue(summary["features"]["chat_streaming"])
        self.assertTrue(summary["features"]["chat_sse"])


if __name__ == "__main__":
    unittest.main()
