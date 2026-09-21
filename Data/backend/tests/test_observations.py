from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from Data.modules.approvals import ApprovalService, ApprovalStore, PolicyEngine
from Data.modules.artifacts import ArtifactStore
from Data.modules.execution import CapabilityRequest, CapabilityStatus, ExecutionGateway, build_default_catalog
from Data.modules.function_runtime import FunctionRuntime, build_default_registry
from Data.modules.knowledge import HybridRetriever, KnowledgeStore
from Data.modules.observations import ObservationStore


class ObservationStoreTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.db_path = self.root / "obs.db"
        self.store = ObservationStore(self.db_path)
        self.store.initialize()
        self.artifacts = ArtifactStore(self.db_path, self.root / "artifacts")
        self.artifacts.initialize()
        self.knowledge = KnowledgeStore(
            self.db_path,
            data_root=self.root / "corpus",
            chunk_max_chars=200,
            chunk_overlap=20,
        )
        self.knowledge.initialize()
        (self.root / "corpus").mkdir(parents=True, exist_ok=True)
        self.fn = FunctionRuntime(build_default_registry(), max_concurrency=2, warm_cache_size=1)
        self.approvals = ApprovalService(ApprovalStore(self.db_path), PolicyEngine())
        self.approvals.store.initialize()
        self.gateway = ExecutionGateway(
            catalog=build_default_catalog(),
            function_runtime=self.fn,
            knowledge_retriever=HybridRetriever(self.knowledge),
            artifact_store=self.artifacts,
            approval_checker=self.approvals,
            observation_store=self.store,
        )

    def tearDown(self) -> None:
        self.fn.shutdown()
        self.tmp.cleanup()

    def test_gateway_persists_observation_and_effect(self) -> None:
        path = self.root / "a.txt"
        path.write_text("obs-hello", encoding="utf-8")
        result = self.gateway.execute(
            CapabilityRequest(capability_id="file.read", arguments={"path": str(path)})
        )
        self.assertEqual(result.status, CapabilityStatus.COMPLETED)
        self.assertIn("observation_id", result.telemetry)
        obs_id = result.telemetry["observation_id"]
        loaded = self.store.get_observation(obs_id)
        assert loaded is not None
        self.assertEqual(loaded.capability_id, "file.read")
        self.assertEqual(loaded.status, "COMPLETED")
        self.assertTrue(loaded.public_dict()["truth"]["observation_is_not_evidence"])
        effects = self.store.list_effects(limit=10)
        self.assertGreaterEqual(len(effects), 1)
        self.assertEqual(effects[0].observation_id, obs_id)

    def test_record_survives_new_store_instance(self) -> None:
        path = self.root / "b.txt"
        path.write_text("durable", encoding="utf-8")
        result = self.gateway.execute(
            CapabilityRequest(capability_id="file.read", arguments={"path": str(path)})
        )
        reopened = ObservationStore(self.db_path)
        items = reopened.list_observations(capability_id="file.read", limit=10)
        self.assertTrue(any(item.observation_id == result.telemetry["observation_id"] for item in items))


if __name__ == "__main__":
    unittest.main()
