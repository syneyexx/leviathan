from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from Data.modules.evaluation import EvaluationHarness
from Data.modules.execution import build_default_catalog, ExecutionGateway, CapabilityRequest
from Data.modules.knowledge import KnowledgeStore
from Data.modules.memory import MemoryKind, MemoryStore
from Data.modules.module_manager import ModuleContext, ModuleManager, ModuleIsolation, ModuleManifest, ModuleStatus
from Data.modules.module_manager.types import ModuleHealth, ModuleResult
from Data.modules.neuro import (
    ContrastiveRetrievalHead,
    CortexRuntime,
    DeterministicResidualRuntime,
    NeuroAbsorbService,
    NeuroMemoryFacade,
    NeuroSnapshotStore,
    ProcessCritic,
    build_residual_runtime,
)
from Data.modules.neuro.residual import ResidualHookPoint, ResidualInjectRequest, ResidualReadRequest
from Data.modules.training import TrainingRecipeRegistry


class Phase47ResidualTests(unittest.TestCase):
    def test_deterministic_residual_read_inject_forward(self) -> None:
        runtime = DeterministicResidualRuntime(n_layers=4, hidden_size=16)
        self.assertTrue(runtime.supports_residuals())
        hooks = list(runtime.list_hook_points())
        self.assertGreaterEqual(len(hooks), 1)
        tensor = runtime.read(ResidualReadRequest(hook=hooks[0]))
        self.assertTrue(tensor.available)
        receipt = runtime.inject(
            ResidualInjectRequest(hook=hooks[0], mode="ADDITIVE", scale=0.2, source="test", payload_ref="a")
        )
        self.assertTrue(receipt.implemented)
        self.assertTrue(receipt.applied)
        self.assertFalse(runtime.runtime_info()["production_grade"])

    def test_build_residual_factory(self) -> None:
        unsupported = build_residual_runtime(kind="unsupported")
        self.assertFalse(unsupported.supports_residuals())
        toy = build_residual_runtime(kind="deterministic")
        self.assertTrue(toy.supports_residuals())

    def test_critic_on_residual(self) -> None:
        runtime = DeterministicResidualRuntime(n_layers=4, hidden_size=16)
        critic = ProcessCritic(enabled=True)
        hook = list(runtime.list_hook_points())[0]
        tensor = runtime.read(ResidualReadRequest(hook=hook))
        score = critic.score_residual(tensor, knowledge_ids=("doc-1",))
        self.assertEqual(score.method, "residual_stats_with_knowledge_context")
        self.assertGreater(score.aggregate, 0.0)

    def test_cortex_runtime_against_deterministic(self) -> None:
        runtime = DeterministicResidualRuntime(n_layers=6, hidden_size=16)
        cortex = CortexRuntime(residual_port=runtime, critic=ProcessCritic(enabled=True))
        report = cortex.run(
            messages=[{"role": "user", "content": "analyze the reactor plan"}],
            depth=2,
            critic_rounds=1,
            knowledge_ids=("k1",),
        )
        self.assertTrue(report.engaged)
        self.assertFalse(report.degraded)
        self.assertTrue(report.public_dict()["truth"]["cortex_run_is_not_completion_authority"])

    def test_neuro_ablation_unmeasured_without_residual(self) -> None:
        harness = EvaluationHarness()
        report = harness.run_suite(
            "neuro_ablation",
            harness.neuro_ablation_suite(
                residual_supported=False,
                cortex_enabled=False,
                memory_tiers_enabled=False,
                critic_enabled=False,
            ),
        )
        residual_case = next(r for r in report.results if r.case_id == "neuro-residual-port")
        self.assertEqual(residual_case.outcome.value, "UNMEASURED")


class Phase48MemoryAbsorbTests(unittest.TestCase):
    def test_snapshot_restore_tier0(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "lev.db"
            snaps = NeuroSnapshotStore(db)
            snaps.initialize()
            facade = NeuroMemoryFacade(enabled=True, snapshot_store=snaps)
            facade.write_working("hot token about alpha")
            snap = facade.snapshot(0, "t0")
            facade.working.clear()
            self.assertEqual(facade.working.snapshot(), [])
            restored = facade.restore(snap.snapshot_id)
            self.assertEqual(restored.snapshot_id, snap.snapshot_id)
            self.assertTrue(any("alpha" in s["content"] for s in facade.working.snapshot()))

    def test_absorb_uses_knowledge_scan(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "ModelData"
            root.mkdir()
            (root / "note.txt").write_text("leviathan absorb test content", encoding="utf-8")
            store = KnowledgeStore(Path(tmp) / "k.db", data_root=root)
            store.initialize()
            absorb = NeuroAbsorbService(store)
            result = absorb.scan_once(limit=10)
            self.assertGreaterEqual(result["ingested"], 1)
            self.assertTrue(result["truth"]["uses_knowledge_v2_ingest"])

    def test_contrastive_lexical_proxy(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            mem = MemoryStore(Path(tmp) / "m.db")
            mem.initialize()
            facade = NeuroMemoryFacade(enabled=True, memory_store=mem)
            facade.write_episodic("decision gateway only", kind=MemoryKind.DECISION)
            head = ContrastiveRetrievalHead(facade, embeddings_available=False)
            report = head.retrieve("gateway")
            self.assertEqual(report.method, "lexical")
            self.assertFalse(report.measured)
            self.assertTrue(report.public_dict()["truth"]["unmeasured_embeddings_are_not_passed"])
            self.assertTrue(report.public_dict()["truth"]["unmeasured_is_not_passed"])

    def test_knowledge_ingest_scan_capability_requires_approval(self) -> None:
        catalog = build_default_catalog()
        self.assertIn("knowledge.ingest_scan", catalog)
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "ModelData"
            root.mkdir()
            store = KnowledgeStore(Path(tmp) / "k.db", data_root=root)
            store.initialize()
            gateway = ExecutionGateway(catalog=catalog, knowledge_store=store)
            rejected = gateway.execute(CapabilityRequest(capability_id="knowledge.ingest_scan", arguments={"limit": 1}))
            self.assertEqual(rejected.status.value, "REJECTED")


class Phase49TrainingCortexTests(unittest.TestCase):
    def test_training_recipes_registered(self) -> None:
        registry = TrainingRecipeRegistry()
        recipes = registry.list()
        self.assertGreaterEqual(len(recipes), 5)
        ids = {r.recipe_id for r in recipes}
        self.assertIn("proc_supervision_v1", ids)
        self.assertTrue(all(r.public_dict()["truth"]["recipe_registered_is_not_trained"] for r in recipes))


class _SubprocModule:
    def __init__(self) -> None:
        self._manifest = ModuleManifest(
            module_id="test.subproc",
            name="Subproc",
            version="0.0.1",
            entrypoint="Data.modules.neuro.echo_module:create_echo_module",
            isolation=ModuleIsolation.SUBPROCESS,
            hot_reload=False,
        )
        self._ready = False

    @property
    def manifest(self) -> ModuleManifest:
        return self._manifest

    def initialize(self, ctx) -> None:
        self._ready = True

    def execute(self, operation: str, arguments):
        # In-process path unused when subprocess isolation is on.
        return ModuleResult(module_id="test.subproc", operation=operation, status="COMPLETED", output={"echo": "inproc"})

    def shutdown(self) -> None:
        self._ready = False

    def health(self) -> ModuleHealth:
        return ModuleHealth(module_id="test.subproc", status=ModuleStatus.READY if self._ready else ModuleStatus.LOADED)


class Phase50IsolationTests(unittest.TestCase):
    def test_subprocess_execute_echo_module(self) -> None:
        manager = ModuleManager(
            discovery_roots=(),
            enabled=True,
            allow_subprocess_isolation=True,
            execute_timeout_seconds=60.0,
        )
        # Use real echo module with SUBPROCESS isolation via register + mutate manifest is frozen.
        # Register echo then execute via SubprocessModuleExecutor by temporarily wrapping.
        from Data.modules.neuro.echo_module import create_echo_module

        echo = create_echo_module()
        # Build a managed module with subprocess isolation by custom register.
        managed = manager.register_instance(echo, ready=True)
        # Force isolation by replacing managed manifest through rediscovery isn't possible —
        # call SubprocessModuleExecutor directly for contract proof.
        from Data.modules.module_manager.subprocess_exec import SubprocessModuleExecutor

        executor = SubprocessModuleExecutor(timeout_seconds=60.0)
        raw = executor.execute(
            entrypoint="Data.modules.neuro.echo_module:create_echo_module",
            operation="ping",
            arguments={"message": "isolated"},
            context={"feature_flags": {"module_manager_subprocess": True}},
        )
        self.assertEqual(raw.get("status"), "COMPLETED")
        self.assertEqual((raw.get("output") or {}).get("echo"), "isolated")


if __name__ == "__main__":
    unittest.main()
