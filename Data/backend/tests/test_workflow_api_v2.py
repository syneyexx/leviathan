"""API coverage for workflows overview / definitions / run-new-execution."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

from Data.backend.routes.workflows import build_workflows_router
from Data.modules.approvals import ApprovalService, ApprovalStore, PolicyEngine
from Data.modules.artifacts import ArtifactStore
from Data.modules.execution import ExecutionGateway, build_default_catalog
from Data.modules.function_runtime import FunctionRuntime, build_default_registry
from Data.modules.jobs import JobRuntime, JobStore, ResourceManager
from Data.modules.knowledge import HybridRetriever, KnowledgeStore
from Data.modules.workflows import WorkflowRuntime, WorkflowStepDef, WorkflowStore
from Data.modules.workflows.types import WorkflowDefinitionStatus


class WorkflowApiTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.db = root / "api.db"
        artifacts = ArtifactStore(self.db, root / "artifacts")
        artifacts.initialize()
        knowledge = KnowledgeStore(self.db, data_root=root / "c", chunk_max_chars=200)
        knowledge.initialize()
        (root / "c").mkdir(parents=True, exist_ok=True)
        self.fn = FunctionRuntime(build_default_registry(), max_concurrency=2, warm_cache_size=1)
        approvals = ApprovalService(ApprovalStore(self.db), PolicyEngine())
        approvals.store.initialize()
        self.catalog = build_default_catalog()
        self.gateway = ExecutionGateway(
            catalog=self.catalog,
            function_runtime=self.fn,
            knowledge_retriever=HybridRetriever(knowledge),
            artifact_store=artifacts,
            approval_checker=approvals,
        )
        self.jobs = JobRuntime(JobStore(self.db), self.gateway, ResourceManager(2))
        self.jobs.store.initialize()
        self.store = WorkflowStore(self.db)
        self.store.initialize()
        self.runtime = WorkflowRuntime(self.store, self.gateway, job_runtime=self.jobs)
        app = FastAPI()
        app.include_router(
            build_workflows_router(
                workflow_store=self.store,
                workflow_runtime=self.runtime,
                capability_catalog=self.catalog,
            )
        )
        self.client = TestClient(app)
        self.note = root / "n.txt"
        self.note.write_text("api", encoding="utf-8")

    def tearDown(self) -> None:
        self.fn.shutdown()
        self.tmp.cleanup()

    def test_create_list_overview_run(self) -> None:
        created = self.client.post(
            "/api/workflows",
            json={
                "name": "Research Pipeline",
                "description": "demo",
                "category": "Research",
                "status": "ACTIVE",
                "steps": [
                    {
                        "step_id": "s1",
                        "capability_id": "file.read",
                        "arguments": {"path": str(self.note)},
                    }
                ],
            },
        )
        self.assertEqual(created.status_code, 200)
        wf = created.json()["workflow"]
        wf_id = wf["workflow_id"]
        listed = self.client.get("/api/workflows")
        self.assertEqual(listed.status_code, 200)
        self.assertTrue(any(item["workflow_id"] == wf_id for item in listed.json()["workflows"]))
        overview = self.client.get("/api/workflows/overview")
        self.assertEqual(overview.status_code, 200)
        body = overview.json()["overview"]
        self.assertGreaterEqual(body["counts"]["total_definitions"], 1)
        self.assertEqual(len(body["kpis"]), 5)
        run1 = self.client.post(f"/api/workflows/{wf_id}/run", json={})
        self.assertEqual(run1.status_code, 200)
        run2 = self.client.post(f"/api/workflows/{wf_id}/run", json={})
        self.assertEqual(run2.status_code, 200)
        self.assertNotEqual(run1.json()["execution"]["execution_id"], run2.json()["execution"]["execution_id"])
        hist = self.client.get(f"/api/workflows/{wf_id}/executions")
        self.assertEqual(hist.status_code, 200)
        self.assertGreaterEqual(len(hist.json()["executions"]), 2)

    def test_duplicate_and_template_list(self) -> None:
        definition = self.store.create_definition(
            name="T",
            steps=[WorkflowStepDef(step_id="s1", capability_id="file.read", arguments={"path": str(self.note)})],
            status=WorkflowDefinitionStatus.TEMPLATE,
        )
        templates = self.client.get("/api/workflows/templates")
        self.assertEqual(templates.status_code, 200)
        self.assertTrue(any(t["workflow_id"] == definition.workflow_id for t in templates.json()["templates"]))
        dup = self.client.post(f"/api/workflows/{definition.workflow_id}/duplicate", json={})
        self.assertEqual(dup.status_code, 200)
        self.assertEqual(dup.json()["workflow"]["status"], "DRAFT")


if __name__ == "__main__":
    unittest.main()
