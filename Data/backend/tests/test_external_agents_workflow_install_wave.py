"""Architecture regression tests — agents / workflow / install / scheduler externalization wave."""

from __future__ import annotations

import inspect
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from Data.modules.agents.execution_gate import (
    allow_inprocess_mission_execution,
    runners_externalized,
)
from Data.modules.agents.runtime import AgentRuntime
from Data.modules.agents.types import AgentKind
from Data.modules.approvals import ApprovalService, ApprovalStore, PolicyEngine
from Data.modules.artifacts import ArtifactStore
from Data.modules.execution import ExecutionGateway, build_default_catalog
from Data.modules.execution.workload import (
    ExecutionWorkloadClass,
    classify_capability,
)
from Data.modules.function_runtime import FunctionRuntime, build_default_registry
from Data.modules.jobs import JobRuntime, JobStore, ResourceManager
from Data.modules.jobs.runtime import EXTERNAL_WORKER_CAPABILITIES
from Data.modules.knowledge import HybridRetriever, KnowledgeStore
from Data.modules.module_manager.external.catalog_register import (
    register_external_control_capabilities,
)
from Data.modules.module_manager.external.install_gate import allow_sync_install_for_tests
from Data.modules.observations import ObservationStore
from Data.modules.schedules import ScheduleRunner, ScheduleStore, ScheduleTargetKind
from Data.modules.workers.pools import POOL_CATALOG, pool_for_capability
from Data.modules.workflows import WorkflowRuntime, WorkflowState, WorkflowStepDef, WorkflowStore


class ModuleRuntimeRoutingTests(unittest.TestCase):
    def test_module_runtime_pool_exists(self) -> None:
        self.assertIn("module_runtime", POOL_CATALOG)
        defn = POOL_CATALOG["module_runtime"]
        self.assertIn("external.module.install", defn.job_kinds)
        self.assertIn("external.module.invoke", defn.job_kinds)
        self.assertEqual(defn.default_count, 1)
        self.assertEqual(defn.max_count, 1)

    def test_install_routes_to_module_runtime(self) -> None:
        self.assertEqual(pool_for_capability("external.module.install"), "module_runtime")
        self.assertNotEqual(pool_for_capability("external.module.install"), "general")

    def test_install_is_external_required(self) -> None:
        catalog = build_default_catalog()
        register_external_control_capabilities(catalog)
        definition = catalog.get("external.module.install")
        self.assertIsNotNone(definition)
        assert definition is not None
        cls = classify_capability(
            "external.module.install",
            metadata=definition.metadata,
        )
        self.assertEqual(cls, ExecutionWorkloadClass.EXTERNAL_REQUIRED)
        self.assertIn("external.module.install", EXTERNAL_WORKER_CAPABILITIES)

    def test_sync_install_gate_off_outside_pytest_env(self) -> None:
        with mock.patch(
            "Data.modules.module_manager.external.install_gate.pytest_session_active",
            return_value=False,
        ):
            self.assertFalse(allow_sync_install_for_tests())

    def test_sync_install_gate_on_under_pytest(self) -> None:
        self.assertTrue(allow_sync_install_for_tests())


class AgentExternalizationFenceTests(unittest.TestCase):
    def test_runners_externalized_default(self) -> None:
        with mock.patch.dict(
            os.environ,
            {"LEVIATHAN_WORKERS_EXTERNALIZE_API": "1"},
            clear=False,
        ):
            self.assertTrue(runners_externalized())
            self.assertFalse(allow_inprocess_mission_execution())

    def test_agent_runtime_source_has_no_process_next(self) -> None:
        source = inspect.getsource(AgentRuntime.execute)
        # Forbid the forbidden escape hatch call site.
        self.assertNotIn("self.jobs.process_next(", source)
        self.assertNotIn("jobs.process_next(", source)

    def test_fleet_source_has_no_thread_pool_executor(self) -> None:
        from Data.modules.agents import fleet as fleet_mod

        source = inspect.getsource(fleet_mod)
        self.assertNotIn("concurrent.futures.ThreadPoolExecutor", source)
        self.assertNotIn("ThreadPoolExecutor(", source)

    def test_agent_runtime_delegates_external_required(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name)
        db = root / "a.db"
        artifacts = ArtifactStore(db, root / "artifacts")
        artifacts.initialize()
        knowledge = KnowledgeStore(db, data_root=root / "c", chunk_max_chars=200, chunk_overlap=20)
        knowledge.initialize()
        fn = FunctionRuntime(build_default_registry(), max_concurrency=2, warm_cache_size=1)
        self.addCleanup(fn.shutdown)
        approvals = ApprovalService(ApprovalStore(db), PolicyEngine())
        approvals.store.initialize()
        obs = ObservationStore(db)
        obs.initialize()
        catalog = build_default_catalog()
        gateway = ExecutionGateway(
            catalog=catalog,
            function_runtime=fn,
            knowledge_retriever=HybridRetriever(knowledge),
            artifact_store=artifacts,
            approval_checker=approvals,
            observation_store=obs,
        )
        jobs = JobRuntime(JobStore(db), gateway, ResourceManager(1))
        jobs.store.initialize()
        runtime = AgentRuntime(gateway=gateway, jobs=jobs, agents_enabled=True)

        # Force a plan with an EXTERNAL_REQUIRED capability via overrides/steps.
        from Data.modules.agents.types import AgentStep, AgentStepKind

        result = runtime.execute(
            "research something",
            kind=AgentKind.GENERIC,
            steps=[
                AgentStep(
                    kind=AgentStepKind.CAPABILITY,
                    capability_id="research.advance",
                    arguments={"project_id": "p1"},
                )
            ],
            idempotency_key="test-mission-1",
        )
        self.assertEqual(result.status, "WAITING_CHILD")
        self.assertTrue(result.job_ids)
        # Critical: process_next must not have been called (job still QUEUED).
        job = jobs.store.get(result.job_ids[0])
        self.assertIsNotNone(job)
        assert job is not None
        self.assertEqual(job.state.value, "QUEUED")
        self.assertEqual(job.worker_pool, "research")


class WorkflowChildDelegationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        db = root / "w.db"
        artifacts = ArtifactStore(db, root / "artifacts")
        artifacts.initialize()
        knowledge = KnowledgeStore(db, data_root=root / "c", chunk_max_chars=200, chunk_overlap=20)
        knowledge.initialize()
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
        self.jobs = JobRuntime(JobStore(db), gateway, ResourceManager(1))
        self.jobs.store.initialize()
        self.runtime = WorkflowRuntime(store, gateway, job_runtime=self.jobs)

    def tearDown(self) -> None:
        self.fn.shutdown()
        self.tmp.cleanup()

    def test_external_required_step_enqueues_child_and_yields(self) -> None:
        wf = self.runtime.create(
            name="ext",
            steps=[
                WorkflowStepDef(
                    step_id="s1",
                    capability_id="research.advance",
                    arguments={"project_id": "p1"},
                )
            ],
        )
        record = self.runtime.store.get(wf.workflow_id)
        assert record is not None
        record.state = WorkflowState.RUNNING
        self.runtime.store.save(record)
        out = self.runtime.advance_one_step(wf.workflow_id)
        self.assertEqual(out.state, WorkflowState.RUNNING)
        self.assertEqual((out.metadata or {}).get("wait_reason"), "WAITING_CHILD")
        pending = (out.metadata or {}).get("pending_child_job_id")
        self.assertTrue(pending)
        job = self.jobs.store.get(str(pending))
        self.assertIsNotNone(job)
        assert job is not None
        self.assertEqual(job.worker_pool, "research")
        # Retry advance must not duplicate child.
        out2 = self.runtime.advance_one_step(wf.workflow_id)
        self.assertEqual((out2.metadata or {}).get("pending_child_job_id"), pending)

    def test_inline_safe_steps_still_run(self) -> None:
        path = Path(self.tmp.name) / "n.txt"
        path.write_text("hello", encoding="utf-8")
        wf = self.runtime.create(
            name="inline",
            steps=[
                WorkflowStepDef(
                    step_id="s1",
                    capability_id="file.read",
                    arguments={"path": str(path)},
                )
            ],
        )
        done = self.runtime.run(wf.workflow_id)
        self.assertEqual(done.state, WorkflowState.COMPLETED)

    def test_workflow_runtime_source_no_process_next(self) -> None:
        source = inspect.getsource(WorkflowRuntime)
        self.assertNotIn("self.job_runtime.process_next(", source)
        self.assertNotIn("jobs.process_next(", source)
        self.assertNotIn("self.jobs.process_next(", source)


class SchedulerEnqueueOnlyTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        db = root / "s.db"
        artifacts = ArtifactStore(db, root / "artifacts")
        artifacts.initialize()
        knowledge = KnowledgeStore(db, data_root=root / "c", chunk_max_chars=200, chunk_overlap=20)
        knowledge.initialize()
        (root / "c").mkdir(parents=True, exist_ok=True)
        knowledge.upsert_document(title="S", content="needle", source="t")
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
        self.jobs = JobRuntime(JobStore(db), gateway, ResourceManager(1))
        self.jobs.store.initialize()
        workflows = WorkflowRuntime(WorkflowStore(db), gateway, job_runtime=self.jobs)
        workflows.store.initialize()
        self.store = ScheduleStore(db)
        self.store.initialize()
        self.runner = ScheduleRunner(self.store, jobs=self.jobs, workflows=workflows)

    def tearDown(self) -> None:
        self.fn.shutdown()
        self.tmp.cleanup()

    def test_tick_never_calls_process_next(self) -> None:
        self.store.create(
            name="research",
            target_kind=ScheduleTargetKind.JOB,
            target_ref="research.advance",
            interval_seconds=60,
            target_payload={"arguments": {"project_id": "p1"}},
            start_after_seconds=0,
        )
        with mock.patch.object(
            self.jobs, "process_next", side_effect=AssertionError("process_next forbidden")
        ):
            fired = self.runner.tick_enqueue_only()
        self.assertEqual(len(fired), 1)
        self.assertTrue(fired[0]["ok"])
        self.assertFalse(fired[0].get("executed_inline"))
        self.assertEqual(fired[0].get("worker_pool"), "research")

    def test_specialist_routing_matrix(self) -> None:
        cases = [
            ("agent.advance", "agents"),
            ("research.advance", "research"),
            ("dataset.process", "dataset"),
            ("workflow.advance", "workflow"),
            ("external.module.install", "module_runtime"),
        ]
        for cap, pool in cases:
            self.assertEqual(pool_for_capability(cap), pool, cap)

    def test_scheduler_entrypoint_no_monkeypatch(self) -> None:
        from Data.modules.workers.entrypoints import scheduler as sched_mod

        source = inspect.getsource(sched_mod)
        self.assertNotIn("process_next =", source)
        self.assertNotIn("monkey", source.lower())

    def test_occurrence_idempotent_across_crash_window(self) -> None:
        schedule = self.store.create(
            name="once",
            target_kind=ScheduleTargetKind.JOB,
            target_ref="knowledge.search",
            interval_seconds=3600,
            target_payload={"arguments": {"query": "x", "limit": 1}},
            start_after_seconds=0,
        )
        fired1 = self.runner.tick_enqueue_only()
        self.assertEqual(len(fired1), 1)
        job_id = fired1[0]["job_id"]
        # Simulate crash after enqueue before mark_ran by resetting next_run_at.
        # After successful mark_ran, force due again with same occurrence key via payload.
        refreshed = self.store.get(schedule.schedule_id)
        assert refreshed is not None
        # Second fire uses new next_run_at → new occurrence → new job is OK.
        # Crash window: enqueue succeeded, mark_ran crashed — re-tick with same next_run.
        # Recreate due state with identical occurrence in payload.
        self.store.create(
            name="dup",
            target_kind=ScheduleTargetKind.JOB,
            target_ref="knowledge.search",
            interval_seconds=3600,
            target_payload={
                "arguments": {"query": "x", "limit": 1},
                "occurrence": "fixed-occurrence-1",
            },
            start_after_seconds=0,
        )
        # Manually fire twice with same occurrence via _fire
        due = [s for s in self.store.due() if s.name == "dup"]
        self.assertTrue(due)
        r1 = self.runner._fire(due[0], execute=False)
        r2 = self.runner._fire(due[0], execute=False)
        self.assertEqual(r1["job_id"], r2["job_id"])


class SignalAndSchedulerSourceFences(unittest.TestCase):
    def test_signal_service_no_inline_fallback(self) -> None:
        from Data.modules.agents.signals import service as sig_mod

        source = inspect.getsource(sig_mod.SignalFabricService._enqueue_delivery_job)
        self.assertNotIn('worker_id="inline-fallback"', source)
        self.assertNotIn('worker_id="inline"', source)

    def test_fleet_no_inline_enqueue_fallback(self) -> None:
        from Data.modules.agents import fleet as fleet_mod

        source = inspect.getsource(fleet_mod.AgentFleetService.launch_mission)
        self.assertNotIn("executing inline", source.lower())
        self.assertIn("MISSION_WORKER_UNAVAILABLE", source)


if __name__ == "__main__":
    unittest.main()
