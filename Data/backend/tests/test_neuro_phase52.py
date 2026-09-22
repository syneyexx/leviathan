from __future__ import annotations

import tempfile
import threading
import unittest
from pathlib import Path
from unittest import mock

from Data.modules.evaluation import EvaluationHarness
from Data.modules.memory import MemoryKind, MemoryStore
from Data.modules.neuro import (
    ContrastiveRetrievalHead,
    CortexPlanner,
    CortexRuntime,
    DeterministicResidualRuntime,
    HFTransformersResidualAdapter,
    LlamaCppResidualAdapter,
    NeuroAdvisor,
    NeuroMemoryFacade,
    NeuroSnapshotStore,
    ProcessCritic,
    VllmResidualAdapter,
    build_residual_runtime,
)
from Data.modules.neuro.residual import (
    ResidualForwardRequest,
    ResidualHookPoint,
    ResidualInjectRequest,
    ResidualReadRequest,
    UnsupportedResidualRuntime,
)
from Data.modules.observability import ObservabilityHub
from Data.modules.reasoning import ReasoningPlan
from Data.modules.training import (
    FixtureRecipeTrainer,
    PreferenceBridge,
    RecipeRunStatus,
    TrainingRecipeRegistry,
    TrainingRegistry,
)


class _FakeEmbeddingProvider:
    provider_id = "fake"

    def available(self) -> bool:
        return True

    def embed_query(self, text: str) -> list[float]:
        return [float(len(text) % 7), 1.0, 0.5]

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return [[float(len(t) % 7), 1.0, 0.25] for t in texts]


class Phase52ResidualAdapterTests(unittest.TestCase):
    def test_inject_receipt_provenance_fields(self) -> None:
        runtime = UnsupportedResidualRuntime()
        hook = ResidualHookPoint(layer_index=0, name="b0")
        receipt = runtime.inject(ResidualInjectRequest(hook=hook, mode="ADDITIVE", scale=0.1))
        payload = receipt.public_dict()
        self.assertFalse(payload["implemented"])
        self.assertFalse(payload["applied"])
        self.assertTrue(payload["degraded_to_chat_completions"])
        self.assertTrue(payload["reason"])

    def test_deterministic_modes_additive_gated_disabled(self) -> None:
        runtime = DeterministicResidualRuntime(n_layers=2, hidden_size=8)
        hook = list(runtime.list_hook_points())[0]
        before = runtime.read(ResidualReadRequest(hook=hook))
        add = runtime.inject(
            ResidualInjectRequest(hook=hook, mode="ADDITIVE", scale=0.5, payload_ref="mem-1")
        )
        self.assertTrue(add.applied)
        gated = runtime.inject(
            ResidualInjectRequest(hook=hook, mode="GATED", scale=0.0, payload_ref="mem-2")
        )
        self.assertTrue(gated.applied)
        disabled = runtime.inject(ResidualInjectRequest(hook=hook, mode="DISABLED", scale=1.0))
        self.assertTrue(disabled.implemented)
        self.assertFalse(disabled.applied)
        after = runtime.read(ResidualReadRequest(hook=hook))
        self.assertTrue(before.available and after.available)
        self.assertTrue(any(e["name"] == "residual_inject" for e in runtime._telemetry))

    def test_hf_without_model_is_unsupported(self) -> None:
        adapter = HFTransformersResidualAdapter(model_id=None, load_weights=True)
        self.assertFalse(adapter.supports_residuals())
        info = adapter.runtime_info()
        self.assertFalse(info["weights_loaded"])
        forward = adapter.run_forward(
            ResidualForwardRequest(messages=[{"role": "user", "content": "hi"}])
        )
        self.assertTrue(forward.degraded_to_chat_completions)
        self.assertFalse(forward.implemented)

    def test_hf_config_ready_without_weights_does_not_claim_support(self) -> None:
        fake_config = mock.Mock()
        fake_config.num_hidden_layers = 4
        transformers_mod = mock.Mock()
        transformers_mod.AutoConfig.from_pretrained.return_value = fake_config
        with mock.patch.dict(
            "sys.modules",
            {"torch": mock.Mock(), "transformers": transformers_mod},
        ):
            adapter = HFTransformersResidualAdapter(
                model_id="sshleifer/tiny-gpt2",
                load_weights=False,
            )
        self.assertFalse(adapter.supports_residuals())
        self.assertTrue(adapter.runtime_info().get("config_ready") or adapter._error)
        receipt = adapter.inject(
            ResidualInjectRequest(
                hook=ResidualHookPoint(0, "hf_block_0"),
                mode="ADDITIVE",
                scale=0.1,
            )
        )
        self.assertFalse(receipt.applied)
        self.assertTrue(receipt.degraded_to_chat_completions)

    def test_vllm_llama_honest_unsupported(self) -> None:
        self.assertFalse(VllmResidualAdapter(endpoint=None).supports_residuals())
        llama = LlamaCppResidualAdapter(model_path="/tmp/model.gguf", selected_layers=(2, 4))
        self.assertFalse(llama.supports_residuals())
        self.assertEqual(len(llama.list_hook_points()), 2)

    def test_ablation_residual_on_vs_off(self) -> None:
        harness = EvaluationHarness()
        off = harness.run_suite(
            "neuro_ablation_off",
            harness.neuro_ablation_suite(
                residual_supported=False,
                cortex_enabled=True,
                memory_tiers_enabled=True,
                critic_enabled=True,
            ),
        )
        residual_off = next(r for r in off.results if r.case_id == "neuro-residual-port")
        self.assertEqual(residual_off.outcome.value, "UNMEASURED")

        on = harness.run_suite(
            "neuro_ablation_on",
            harness.neuro_ablation_suite(
                residual_supported=True,
                cortex_enabled=True,
                memory_tiers_enabled=True,
                critic_enabled=True,
            ),
        )
        residual_on = next(r for r in on.results if r.case_id == "neuro-residual-port")
        self.assertEqual(residual_on.outcome.value, "PASSED")


class Phase52CortexCriticTests(unittest.TestCase):
    def test_planner_lean_vs_complex_with_budget_and_memory(self) -> None:
        planner = CortexPlanner(enabled=True, max_depth=2, max_critic_rounds=2)
        lean = planner.plan(
            ReasoningPlan(intent="conversation", complexity="low", use_knowledge=False, steps=("respond",)),
            token_budget=2000,
            memory_coverage=0.9,
            working_memory_load=0.1,
        )
        self.assertEqual(lean.path, "lean")
        self.assertFalse(lean.engage)

        complex_plan = planner.plan(
            ReasoningPlan(
                intent="research",
                complexity="high",
                use_knowledge=True,
                steps=("search", "verify", "synthesize"),
            ),
            residual_available=True,
            memory_tiers_enabled=True,
            process_critic_enabled=True,
            token_budget=9000,
            memory_hit_quality=0.2,
            memory_coverage=0.1,
            working_memory_load=0.9,
        )
        self.assertEqual(complex_plan.path, "complex")
        self.assertTrue(complex_plan.engage)
        self.assertGreaterEqual(complex_plan.depth, 1)
        self.assertGreaterEqual(complex_plan.critic_rounds, 1)
        self.assertIn(2, complex_plan.use_memory_tiers)

    def test_cortex_runtime_mid_forward_critic_steer(self) -> None:
        runtime = DeterministicResidualRuntime(n_layers=6, hidden_size=16)
        cortex = CortexRuntime(
            residual_port=runtime,
            critic=ProcessCritic(enabled=True),
            consistency_floor=0.99,
            grounding_floor=0.99,
        )
        report = cortex.run(
            messages=[{"role": "user", "content": "analyze reactor coolant without citations"}],
            depth=2,
            critic_rounds=2,
            knowledge_ids=("doc-42",),
            evidence_ids=("evid-7",),
        )
        self.assertTrue(report.engaged)
        self.assertGreaterEqual(report.mid_forward_interventions, 1)
        self.assertTrue(report.residual_replay_layers)
        self.assertEqual(report.path, "complex")
        self.assertTrue(report.public_dict()["truth"]["depth_is_not_authority"])

    def test_critic_grounding_drops_hard_without_citations(self) -> None:
        critic = ProcessCritic(enabled=True)
        uncited = critic.score(
            "The answer is obviously 42",
            knowledge_ids=("doc-123",),
            evidence_ids=("evid-9",),
        )
        self.assertLess(uncited.factual_grounding, 0.15)
        self.assertIn("missed", uncited.method)

        cited = critic.score(
            "Per evid-9 and doc-123 the answer is 42",
            knowledge_ids=("doc-123",),
            evidence_ids=("evid-9",),
        )
        self.assertGreater(cited.factual_grounding, 0.6)
        self.assertEqual(cited.method, "lexical_grounding_ids")

        no_ids = critic.score("Pure speculation")
        self.assertLessEqual(no_ids.factual_grounding, 0.2)


class Phase52MemoryTests(unittest.TestCase):
    def test_priority_eviction_and_budgeted_retrieve(self) -> None:
        facade = NeuroMemoryFacade(enabled=True, working_capacity=2)
        facade.write_working("low priority alpha", priority=0.1)
        facade.write_working("high priority beta", priority=0.9)
        facade.write_working("medium gamma", priority=0.5)
        snap = facade.working.snapshot()
        self.assertEqual(len(snap), 2)
        contents = " ".join(s["content"] for s in snap)
        self.assertIn("beta", contents)
        self.assertNotIn("alpha", contents)

        facade.write_working("budget token " * 40, priority=0.8)
        bundle = facade.retrieve("budget", tiers=(0,), token_budget=5)
        self.assertLessEqual(len(bundle.hits), 1)
        self.assertIsNotNone(bundle.token_budget)

    def test_high_trust_write_and_refuse_model_output(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = MemoryStore(Path(tmp) / "m.db")
            store.initialize()
            facade = NeuroMemoryFacade(enabled=True, memory_store=store)
            record = facade.write_high_trust(
                "verification confirmed gateway path",
                source="verification",
                kind=MemoryKind.DECISION,
            )
            self.assertEqual(record.trust, "explicit")
            with self.assertRaises(ValueError):
                facade.write_high_trust("bad", source="model_self_score")
            with self.assertRaises(ValueError):
                facade.write_episodic("hallucination", trust="model_output")

    def test_snapshot_restore_under_concurrent_writes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            snaps = NeuroSnapshotStore(Path(tmp) / "lev.db")
            snaps.initialize()
            facade = NeuroMemoryFacade(enabled=True, snapshot_store=snaps, working_capacity=32)

            def writer(i: int) -> None:
                facade.write_working(f"concurrent slot {i}", priority=0.5)

            threads = [threading.Thread(target=writer, args=(i,)) for i in range(8)]
            for t in threads:
                t.start()
            for t in threads:
                t.join()
            snap = facade.snapshot(0, "concurrent")
            facade.working.clear()
            facade.restore(snap.snapshot_id)
            self.assertGreaterEqual(len(facade.working.snapshot()), 1)

    def test_contrastive_with_and_without_embeddings(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            mem = MemoryStore(Path(tmp) / "m.db")
            mem.initialize()
            facade = NeuroMemoryFacade(enabled=True, memory_store=mem)
            facade.write_episodic("gateway evidence link", kind=MemoryKind.DECISION)
            lexical = ContrastiveRetrievalHead(facade, embeddings_available=False)
            report = lexical.retrieve("gateway")
            self.assertEqual(report.method, "lexical")
            self.assertFalse(report.measured)

            vector = ContrastiveRetrievalHead(
                facade,
                embedding_provider=_FakeEmbeddingProvider(),
            )
            vreport = vector.retrieve("gateway")
            self.assertEqual(vreport.method, "embedding")
            self.assertTrue(vreport.measured)
            self.assertTrue(vreport.available)


class Phase52TrainingTests(unittest.TestCase):
    def test_recipe_execute_without_trainer_fails_honestly(self) -> None:
        registry = TrainingRecipeRegistry(trainer=None)
        run = registry.execute("pref_dpo_v1", samples=[{"verification_passed": True}])
        self.assertEqual(run.status, RecipeRunStatus.FAILED)
        self.assertEqual(run.metrics, {})
        self.assertIn("registered", (run.error or "").lower())

    def test_fixture_trainer_completes_with_real_metrics(self) -> None:
        registry = TrainingRecipeRegistry(trainer=FixtureRecipeTrainer())
        run = registry.execute(
            "proc_supervision_v1",
            samples=[
                {"critic_approved": True, "step": "s1"},
                {"critic_approved": False, "step": "s2"},
            ],
        )
        self.assertEqual(run.status, RecipeRunStatus.COMPLETED)
        self.assertIn("loss", run.metrics)
        self.assertTrue(run.metrics.get("fixture"))

    def test_no_fabricated_completed_empty_metrics(self) -> None:
        class EmptyTrainer:
            backend_id = "empty"

            def available(self) -> bool:
                return True

            def execute(self, recipe, *, samples, config=None):
                return {}

        registry = TrainingRecipeRegistry(trainer=EmptyTrainer())  # type: ignore[arg-type]
        run = registry.execute("contrastive_memory_v1", samples=[{"x": 1}])
        self.assertEqual(run.status, RecipeRunStatus.FAILED)
        self.assertEqual(run.metrics, {})

    def test_human_preference_bridge(self) -> None:
        bridge = PreferenceBridge(TrainingRegistry())
        job = bridge.register_human_preference(preferred_id="a", rejected_id="b")
        self.assertIn("human_preference", job.objective)
        self.assertTrue(job.public_dict()["truth"]["registered_is_not_trained"])


class Phase52IntegrationTests(unittest.TestCase):
    def test_advisor_emits_depth_and_telemetry(self) -> None:
        hub = ObservabilityHub()
        runtime = DeterministicResidualRuntime(n_layers=4, hidden_size=8)
        advisor = NeuroAdvisor(
            enabled=True,
            process_critic=True,
            residual_injection=True,
            cortex_enabled=True,
            memory_tiers_enabled=True,
            residual_port=runtime,
            memory_facade=NeuroMemoryFacade(enabled=True),
            cortex_planner=CortexPlanner(enabled=True),
            critic=ProcessCritic(enabled=True),
            observability=hub,
        )
        advisor.memory_facade.write_working("reactor coolant protocol", priority=0.8)
        assessment = advisor.assess(
            "research the reactor coolant failure modes carefully",
            plan=ReasoningPlan(
                intent="research",
                complexity="high",
                use_knowledge=True,
                steps=("search", "verify"),
            ),
            knowledge_ids=("doc-1",),
            evidence_ids=("evid-1",),
        )
        kinds = {s.kind for s in assessment.signals}
        self.assertIn("cortex_engagement", kinds)
        self.assertIn("depth_metadata", kinds)
        self.assertIn("process_critic", kinds)
        events = hub.recent(category="neuro", limit=20)
        names = {e.name for e in events}
        self.assertIn("assess", names)
        self.assertIn("cortex_engagement", names)

    def test_build_residual_factory_load_weights_flag(self) -> None:
        toy = build_residual_runtime(kind="deterministic")
        self.assertTrue(toy.supports_residuals())
        hf = build_residual_runtime(kind="hf", model_id=None, load_weights=True)
        self.assertFalse(hf.supports_residuals())
        self.assertIsInstance(hf, HFTransformersResidualAdapter)


if __name__ == "__main__":
    unittest.main()
