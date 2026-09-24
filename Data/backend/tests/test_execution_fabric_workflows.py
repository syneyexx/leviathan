"""Durable workflow continuation tests."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from Data.modules.approvals import ApprovalService, ApprovalStore, PolicyEngine
from Data.modules.artifacts import ArtifactStore
from Data.modules.execution import ExecutionGateway, SideEffect, build_default_catalog
from Data.modules.function_runtime import FunctionRuntime, build_default_registry
from Data.modules.knowledge import HybridRetriever, KnowledgeStore
from Data.modules.workflows import WorkflowRuntime, WorkflowStepDef
from Data.modules.workflows.store import WorkflowStore
from Data.modules.workflows.types import WorkflowState


class WorkflowAdvanceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.db = root / "wf.db"
        self.artifacts = ArtifactStore(self.db, root / "artifacts")
        self.artifacts.initialize()
        self.knowledge = KnowledgeStore(self.db, data_root=root / "corpus", chunk_max_chars=200)
        self.knowledge.initialize()
        (root / "corpus").mkdir(parents=True, exist_ok=True)
        note = root / "corpus" / "n.txt"
        note.write_text("hello workflow", encoding="utf-8")
        self.fn = FunctionRuntime(build_default_registry(), max_concurrency=2, warm_cache_size=1)
        self.approvals = ApprovalService(ApprovalStore(self.db), PolicyEngine())
        self.approvals.store.initialize()
        self.gateway = ExecutionGateway(
            catalog=build_default_catalog(),
            function_runtime=self.fn,
            knowledge_retriever=HybridRetriever(self.knowledge),
            artifact_store=self.artifacts,
            approval_checker=self.approvals,
        )
        self.store = WorkflowStore(self.db)
        self.store.initialize()
        self.runtime = WorkflowRuntime(self.store, self.gateway)
        self.note = note

    def tearDown(self) -> None:
        self.fn.shutdown()
        self.tmp.cleanup()

    def test_advance_one_step_then_continue(self) -> None:
        wf = self.runtime.create(
            name="t",
            steps=[
                WorkflowStepDef(
                    step_id="s0",
                    capability_id="file.read",
                    arguments={"path": str(self.note)},
                ),
                WorkflowStepDef(
                    step_id="s1",
                    capability_id="file.read",
                    arguments={"path": str(self.note)},
                ),
            ],
        )
        mid = self.runtime.advance_one_step(wf.workflow_id)
        self.assertEqual(mid.state, WorkflowState.RUNNING)
        self.assertEqual(mid.current_step, 1)
        done = self.runtime.advance_one_step(wf.workflow_id)
        self.assertEqual(done.state, WorkflowState.COMPLETED)
        self.assertEqual(done.current_step, 2)

    def test_run_still_completes_all(self) -> None:
        wf = self.runtime.create(
            name="all",
            steps=[
                WorkflowStepDef(
                    step_id="s0",
                    capability_id="file.read",
                    arguments={"path": str(self.note)},
                ),
            ],
        )
        done = self.runtime.run(wf.workflow_id)
        self.assertEqual(done.state, WorkflowState.COMPLETED)


if __name__ == "__main__":
    unittest.main()
