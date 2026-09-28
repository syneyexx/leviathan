"""Brain / Memory / Research externalization wave — ownership & fail-closed tests."""

from __future__ import annotations

import ast
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from Data.modules.brain import BrainQueryFacade, compute_derived_snapshot
from Data.modules.brain.compute import process_brain_compute_job
from Data.modules.embedding.worker import process_embedding_job
from Data.modules.execution import ExecutionGateway, build_default_catalog
from Data.modules.execution.workload import ExecutionWorkloadClass, classify_capability
from Data.modules.jobs import JobRuntime, JobStore, ResourceManager
from Data.modules.jobs.runtime import EXTERNAL_WORKER_CAPABILITIES
from Data.modules.jobs.states import JobState
from Data.modules.knowledge.embeddings import LocalHashEmbeddingProvider
from Data.modules.memory import MemoryConsolidator, MemoryStore, MemoryTrustState
from Data.modules.memory.worker import process_memory_job
from Data.modules.rerank.worker import process_rerank_job
from Data.modules.research import ResearchService, UnconfiguredWebProvider
from Data.modules.research.store import ResearchStore
from Data.modules.research.worker import process_research_job
from Data.modules.workers.pools import POOL_CATALOG, pool_for_capability


def _runtime(db: Path) -> JobRuntime:
    store = JobStore(db)
    store.initialize()
    return JobRuntime(
        store,
        ExecutionGateway(catalog=build_default_catalog()),
        ResourceManager(4),
        lease_ttl_seconds=2.0,
    )


def _claim(runtime: JobRuntime, *, worker_id: str, worker_pool: str):
    job = runtime.store.claim_next_queued(
        worker_id=worker_id,
        worker_pool=worker_pool,
        lease_ttl_seconds=30.0,
    )
    assert job is not None, f"expected claimable job in pool {worker_pool}"
    return job


class PoolOwnershipWaveTests(unittest.TestCase):
    def test_specialist_capabilities_route_correctly(self) -> None:
        cases = {
            "research.advance": "research",
            "research.plan": "research",
            "research.web.probe": "research",
            "web.search": "research",
            "web.fetch": "research",
            "embedding.batch": "embedding",
            "rerank.batch": "rerank",
            "memory.consolidate": "memory",
            "memory.enrich": "memory",
            "memory.reconcile": "memory",
            "brain.compute.snapshot": "brain_compute",
            "brain.rebuild": "brain_compute",
            "brain.analyze": "brain_compute",
            "knowledge.reconcile": "knowledge_prepare",
            "knowledge.prepare": "knowledge_prepare",
        }
        for cap, pool in cases.items():
            self.assertEqual(pool_for_capability(cap), pool, msg=cap)
            self.assertNotEqual(pool, "general", msg=cap)

    def test_new_pools_exist_with_bounds(self) -> None:
        self.assertIn("memory", POOL_CATALOG)
        self.assertIn("brain_compute", POOL_CATALOG)
        self.assertEqual(POOL_CATALOG["memory"].default_count, 1)
        self.assertEqual(POOL_CATALOG["memory"].max_count, 2)
        self.assertEqual(POOL_CATALOG["brain_compute"].default_count, 1)
        self.assertEqual(POOL_CATALOG["brain_compute"].max_count, 2)
        self.assertEqual(POOL_CATALOG["rerank"].default_count, 0)
        self.assertEqual(POOL_CATALOG["db_commit"].default_count, 1)
        self.assertEqual(POOL_CATALOG["db_commit"].max_count, 1)

    def test_external_required_class_and_steal_fence(self) -> None:
        for cap in (
            "research.plan",
            "research.web.probe",
            "memory.consolidate",
            "brain.compute.snapshot",
            "embedding.batch",
            "rerank.batch",
            "knowledge.reconcile",
        ):
            self.assertEqual(
                classify_capability(cap),
                ExecutionWorkloadClass.EXTERNAL_REQUIRED,
                msg=cap,
            )
            self.assertIn(cap, EXTERNAL_WORKER_CAPABILITIES)


class ResearchPlanExternalizationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.db = self.root / "r.db"
        self.store = ResearchStore(self.db)
        self.store.initialize()
        self.job_runtime = _runtime(self.db)
        self.service = ResearchService(
            self.store,
            web=UnconfiguredWebProvider(),
            allow_outbound=False,
            snapshots_root=self.root / "snapshots",
            reports_root=self.root / "reports",
            sources_root=self.root / "sources",
            job_runtime=self.job_runtime,
        )

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_request_plan_enqueues_when_externalized(self) -> None:
        project = self.service.create_project(topic="Plan ownership", depth="quick")
        with mock.patch.dict(os.environ, {"LEVIATHAN_WORKERS_EXTERNALIZE_API": "1"}):
            with mock.patch.object(self.service, "plan") as plan_spy:
                out = self.service.request_plan(project.project_id, regenerate=True)
        self.assertTrue(out["queued"])
        self.assertEqual(out["job"]["capability_id"], "research.plan")
        self.assertEqual(out["job"]["worker_pool"], "research")
        plan_spy.assert_not_called()

    def test_manual_edits_remain_inline_when_plan_exists(self) -> None:
        project = self.service.create_project(topic="Edit plan", depth="quick")
        planned = self.service.plan(project.project_id)
        self.assertIsNotNone(planned.plan)
        with mock.patch.dict(os.environ, {"LEVIATHAN_WORKERS_EXTERNALIZE_API": "1"}):
            with mock.patch.object(self.service, "enqueue_plan") as enq:
                result = self.service.request_plan(
                    planned.project_id,
                    edits={"notes": "operator note"},
                    regenerate=False,
                )
        enq.assert_not_called()
        self.assertEqual(result.plan.notes, "operator note")

    def test_worker_executes_plan_action(self) -> None:
        project = self.service.create_project(topic="Worker plan", depth="quick")
        with mock.patch.dict(os.environ, {"LEVIATHAN_WORKERS_EXTERNALIZE_API": "1"}):
            queued = self.service.enqueue_plan(project.project_id)
        job = self.job_runtime.store.get(queued["job_id"])
        claimed = self.job_runtime.store.claim_next_queued(
            worker_id="research-test",
            worker_pool="research",
            lease_ttl_seconds=30.0,
        )
        self.assertIsNotNone(claimed)
        self.assertEqual(claimed.job_id, job.job_id)
        ctx = {
            "job_store": self.job_runtime.store,
            "job_runtime": self.job_runtime,
            "research_service": self.service,
            "worker_id": "research-test",
        }
        process_research_job(ctx, claimed)
        refreshed = self.service.get_project(project.project_id)
        self.assertIsNotNone(refreshed.plan)
        self.assertEqual(refreshed.status.value, "planned")

    def test_web_probe_enqueues_not_inline_network(self) -> None:
        with mock.patch.dict(os.environ, {"LEVIATHAN_WORKERS_EXTERNALIZE_API": "1"}):
            with mock.patch.object(self.service, "probe_web_research") as probe_spy:
                out = self.service.request_web_probe(query="sqlite", limit=2)
        self.assertTrue(out["queued"])
        self.assertEqual(out["job"]["capability_id"], "research.web.probe")
        probe_spy.assert_not_called()

    def test_plan_fail_closed_without_runtime(self) -> None:
        service = ResearchService(
            self.store,
            web=UnconfiguredWebProvider(),
            allow_outbound=False,
            snapshots_root=self.root / "s2",
            reports_root=self.root / "r2",
            sources_root=self.root / "src2",
            job_runtime=None,
        )
        project = service.create_project(topic="no runtime", depth="quick")
        with mock.patch.dict(os.environ, {"LEVIATHAN_WORKERS_EXTERNALIZE_API": "1"}):
            with self.assertRaises(Exception) as ctx:
                service.enqueue_plan(project.project_id)
        self.assertIn("RESEARCH_WORKER_UNAVAILABLE", str(ctx.exception.code))


class MemoryExternalizationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.db = Path(self.tmp.name) / "m.db"
        self.store = MemoryStore(self.db)
        self.store.initialize()
        self.job_runtime = _runtime(self.db)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_confidence_never_verified_via_worker(self) -> None:
        for i in range(2):
            self.store.create(
                content=f"User prefers dark mode for trading dashboards variant {i}",
                kind=__import__("Data.modules.memory", fromlist=["MemoryKind"]).MemoryKind.EPISODIC,
                source="agent",
                trust="AGENT_PROPOSED",
                conversation_id="c1",
                scope="CONVERSATION",
            )
        job = self.job_runtime.enqueue(
            capability_id="memory.consolidate",
            arguments={
                "action": "consolidate",
                "conversation_id": "c1",
                "limit": 100,
                "min_cluster_size": 2,
                "persist": True,
            },
            worker_pool="memory",
            requested_by="test",
        )
        claimed = _claim(self.job_runtime, worker_id="mem-test", worker_pool="memory")
        self.assertEqual(claimed.job_id, job.job_id)
        ctx = {
            "job_store": self.job_runtime.store,
            "memory_store": self.store,
            "worker_id": "mem-test",
        }
        process_memory_job(ctx, claimed)
        done = self.job_runtime.store.get(job.job_id)
        self.assertEqual(done.state, JobState.COMPLETED)
        for cand in (done.result or {}).get("candidates") or []:
            self.assertEqual(cand["trust_state"], MemoryTrustState.AGENT_PROPOSED.value)
            self.assertTrue(cand["truth"]["model_confidence_is_not_memory_truth"])

    def test_consolidator_unit_trust_gate(self) -> None:
        result = MemoryConsolidator().consolidate(
            [
                {
                    "memory_id": "a",
                    "kind": "EPISODIC",
                    "content": "alpha preference for dark mode screens",
                    "trust": "model_output",
                    "confidence": 0.99,
                },
                {
                    "memory_id": "b",
                    "kind": "EPISODIC",
                    "content": "alpha preference for dark mode dashboards",
                    "trust": "agent",
                    "confidence": 0.98,
                },
            ],
            min_cluster_size=2,
        )
        self.assertTrue(result.candidates)
        self.assertEqual(result.candidates[0].trust_state, MemoryTrustState.AGENT_PROPOSED)


class BrainComputeExternalizationTests(unittest.TestCase):
    def test_derived_snapshot_is_not_canonical_db(self) -> None:
        facade = BrainQueryFacade(
            knowledge_list=lambda: [
                {
                    "id": "d1",
                    "title": "Alpha doc",
                    "created_at": None,
                    "source": "test",
                    "status": "READY",
                    "trust_metadata": {},
                }
            ],
            max_nodes=50,
            max_edges=100,
        )
        snap = compute_derived_snapshot(facade, limit=50)
        self.assertTrue(snap["truth"]["brain_is_facade"])
        self.assertTrue(snap["truth"]["not_a_brain_database"])
        self.assertIn("algorithm_version", snap["provenance"])
        self.assertGreaterEqual(snap["provenance"]["node_count"], 1)

    def test_worker_completes_analyze(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        try:
            db = Path(tmp.name) / "b.db"
            runtime = _runtime(db)
            facade = BrainQueryFacade(max_nodes=20, max_edges=40)
            job = runtime.enqueue(
                capability_id="brain.analyze",
                arguments={"action": "analyze", "limit": 20},
                worker_pool="brain_compute",
                requested_by="test",
            )
            claimed = _claim(runtime, worker_id="brain-test", worker_pool="brain_compute")
            self.assertEqual(claimed.job_id, job.job_id)
            ctx = {
                "job_store": runtime.store,
                "brain_facade": facade,
                "worker_id": "brain-test",
            }
            process_brain_compute_job(ctx, claimed)
            done = runtime.store.get(job.job_id)
            self.assertEqual(done.state, JobState.COMPLETED)
            self.assertTrue((done.result or {})["truth"]["brain_is_facade"])
            self.assertTrue((done.result or {})["truth"]["derived_not_canonical"])
        finally:
            tmp.cleanup()


class EmbeddingRerankWorkerTests(unittest.TestCase):
    def test_embedding_batch_via_worker(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        try:
            db = Path(tmp.name) / "e.db"
            runtime = _runtime(db)
            job = runtime.enqueue(
                capability_id="embedding.batch",
                arguments={"texts": ["alpha", "beta"], "model_id": "local_hash"},
                worker_pool="embedding",
                requested_by="test",
            )
            claimed = _claim(runtime, worker_id="emb-test", worker_pool="embedding")
            ctx = {
                "job_store": runtime.store,
                "embedding_provider": LocalHashEmbeddingProvider(dimensions=32),
                "worker_id": "emb-test",
            }
            process_embedding_job(ctx, claimed)
            done = runtime.store.get(job.job_id)
            self.assertEqual(done.state, JobState.COMPLETED)
            self.assertEqual((done.result or {})["items_completed"], 2)
            self.assertTrue((done.result or {})["truth"]["no_fastapi_inference"])
        finally:
            tmp.cleanup()

    def test_rerank_unavailable_is_honest(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        try:
            db = Path(tmp.name) / "rr.db"
            runtime = _runtime(db)
            job = runtime.enqueue(
                capability_id="rerank.batch",
                arguments={"query": "q", "documents": ["a", "b"], "top_k": 2},
                worker_pool="rerank",
                requested_by="test",
            )
            claimed = _claim(runtime, worker_id="rr-test", worker_pool="rerank")
            ctx = {"job_store": runtime.store, "worker_id": "rr-test"}
            process_rerank_job(ctx, claimed)
            done = runtime.store.get(job.job_id)
            self.assertEqual(done.state, JobState.COMPLETED)
            self.assertEqual((done.result or {})["status"], "UNAVAILABLE")
            self.assertTrue((done.result or {})["truth"]["fallback_is_not_neural_reranking"])
            self.assertFalse((done.result or {})["truth"]["neural_rerank"])
        finally:
            tmp.cleanup()


class NoFastApiHeavyInlineAstTests(unittest.TestCase):
    def test_research_routes_do_not_call_probe_or_plan_directly(self) -> None:
        path = Path(__file__).resolve().parents[1] / "routes" / "research.py"
        tree = ast.parse(path.read_text(encoding="utf-8"))
        calls: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                func = node.func
                if isinstance(func, ast.Attribute):
                    calls.add(func.attr)
        self.assertIn("request_plan", calls)
        self.assertIn("request_web_probe", calls)
        self.assertNotIn("probe_web_research", calls)
        # service.plan may still appear in comments/strings only — attribute call must use request_plan.
        # Direct service.plan in route body is forbidden.
        route_plan_direct = False
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
                if node.func.attr == "plan" and isinstance(node.func.value, ast.Name):
                    if node.func.value.id == "service":
                        route_plan_direct = True
        self.assertFalse(route_plan_direct)


if __name__ == "__main__":
    unittest.main()
