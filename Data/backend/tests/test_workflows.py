from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from Data.modules.approvals import ApprovalService, ApprovalStore, PolicyEngine
from Data.modules.artifacts import ArtifactStore
from Data.modules.execution import ExecutionGateway, build_default_catalog
from Data.modules.function_runtime import FunctionRuntime, build_default_registry
from Data.modules.knowledge import HybridRetriever, KnowledgeStore
from Data.modules.observations import ObservationStore
from Data.modules.workflows import WorkflowRuntime, WorkflowState, WorkflowStepDef, WorkflowStore


class WorkflowRuntimeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        db = root / "w.db"
        artifacts = ArtifactStore(db, root / "artifacts")
        artifacts.initialize()
        knowledge = KnowledgeStore(db, data_root=root / "c", chunk_max_chars=200, chunk_overlap=20)
        knowledge.initialize()
        (root / "c").mkdir(parents=True, exist_ok=True)
        knowledge.upsert_document(title="W", content="workflow knowledge search needle", source="t")
        self.fn = FunctionRuntime(build_default_registry(), max_concurrency=2, warm_cache_size=1)
        approvals = ApprovalService(ApprovalStore(db), PolicyEngine())
        approvals.store.initialize()
        obs = ObservationStore(db)
        obs.initialize()
        gateway = ExecutionGateway(
            catalog=build_default_catalog(),
            function_runtime=self.fn,
            knowledge_retriever=HybridRetriever(knowledge),
            artifact_store=artifacts,
            approval_checker=approvals,
            observation_store=obs,
        )
        store = WorkflowStore(db)
        store.initialize()
        self.runtime = WorkflowRuntime(store, gateway)
        self.root = root

    def tearDown(self) -> None:
        self.fn.shutdown()
        self.tmp.cleanup()

    def test_runs_capability_steps(self) -> None:
        path = self.root / "n.txt"
        path.write_text("workflow-hello", encoding="utf-8")
        wf = self.runtime.create(
            name="demo",
            steps=[
                WorkflowStepDef(
                    step_id="s1",
                    capability_id="file.read",
                    arguments={"path": str(path)},
                ),
                WorkflowStepDef(
                    step_id="s2",
                    capability_id="knowledge.search",
                    arguments={"query": "workflow knowledge", "limit": 3},
                ),
            ],
        )
        done = self.runtime.run(wf.workflow_id)
        self.assertEqual(done.state, WorkflowState.COMPLETED)
        self.assertEqual(len(done.step_results), 2)
        self.assertEqual(done.step_results[0]["status"], "COMPLETED")

    def test_stops_on_failure(self) -> None:
        wf = self.runtime.create(
            name="fail",
            steps=[
                WorkflowStepDef(
                    step_id="s1",
                    capability_id="file.read",
                    arguments={"path": str(self.root / "missing.txt")},
                ),
                WorkflowStepDef(
                    step_id="s2",
                    capability_id="knowledge.search",
                    arguments={"query": "x"},
                ),
            ],
        )
        done = self.runtime.run(wf.workflow_id)
        self.assertEqual(done.state, WorkflowState.FAILED)
        self.assertEqual(len(done.step_results), 1)


if __name__ == "__main__":
    unittest.main()
