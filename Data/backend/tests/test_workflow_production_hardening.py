"""Workflow production hardening — delay wake-up, approval, idempotency, concurrency, secrets."""

from __future__ import annotations

import tempfile
import threading
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import MagicMock

from Data.modules.approvals import ApprovalService, ApprovalStore, PolicyEngine
from Data.modules.artifacts import ArtifactStore
from Data.modules.execution import (
    CapabilityRequest,
    CapabilityStatus,
    ExecutionGateway,
    SideEffect,
    build_default_catalog,
)
from Data.modules.function_runtime import FunctionRuntime, build_default_registry
from Data.modules.jobs import JobRuntime, JobStore, ResourceManager
from Data.modules.knowledge import HybridRetriever, KnowledgeStore
from Data.modules.observations import ObservationStore
from Data.modules.schedules import ScheduleRunner, ScheduleStore
from Data.modules.schedules.types import ScheduleStatus
from Data.modules.workflows import (
    WorkflowDefinitionStatus,
    WorkflowEdgeDef,
    WorkflowExecutionState,
    WorkflowGraph,
    WorkflowNodeDef,
    WorkflowNodeKind,
    WorkflowRuntime,
    WorkflowState,
    WorkflowStepDef,
    WorkflowStore,
    WorkflowVariableDef,
)


class WorkflowHardeningTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.db = root / "h.db"
        artifacts = ArtifactStore(self.db, root / "artifacts")
        artifacts.initialize()
        knowledge = KnowledgeStore(self.db, data_root=root / "c", chunk_max_chars=200, chunk_overlap=20)
        knowledge.initialize()
        (root / "c").mkdir(parents=True, exist_ok=True)
        self.fn = FunctionRuntime(build_default_registry(), max_concurrency=2, warm_cache_size=1)
        self.approvals = ApprovalService(ApprovalStore(self.db), PolicyEngine())
        self.approvals.store.initialize()
        obs = ObservationStore(self.db)
        obs.initialize()
        self.gateway = ExecutionGateway(
            catalog=build_default_catalog(),
            function_runtime=self.fn,
            knowledge_retriever=HybridRetriever(knowledge),
            artifact_store=artifacts,
            approval_checker=self.approvals,
            observation_store=obs,
        )
        self.store = WorkflowStore(self.db)
        self.store.initialize()
        self.schedules = ScheduleStore(self.db)
        self.schedules.initialize()
        self.jobs = JobRuntime(
            JobStore(self.db),
            self.gateway,
            ResourceManager(max_job_concurrency=8),
        )
        self.jobs.store.initialize()
        self.runtime = WorkflowRuntime(
            self.store,
            self.gateway,
            job_runtime=self.jobs,
            schedule_store=self.schedules,
        )
        self.root = root
        self.note = root / "n.txt"
        self.note.write_text("hello-hard", encoding="utf-8")

    def tearDown(self) -> None:
        self.fn.shutdown()
        self.tmp.cleanup()

    def _delay_graph(self, seconds: float) -> WorkflowGraph:
        return WorkflowGraph(
            nodes=[
                WorkflowNodeDef(node_id="t", kind=WorkflowNodeKind.TRIGGER, label="t", config={}),
                WorkflowNodeDef(
                    node_id="d",
                    kind=WorkflowNodeKind.DELAY,
                    label="delay",
                    config={"delay_seconds": seconds},
                ),
                WorkflowNodeDef(
                    node_id="after",
                    kind=WorkflowNodeKind.CAPABILITY,
                    label="after",
                    config={"capability_id": "file.read", "arguments": {"path": str(self.note)}},
                ),
            ],
            edges=[
                WorkflowEdgeDef(edge_id="t-d", source="t", target="d"),
                WorkflowEdgeDef(edge_id="d-a", source="d", target="after"),
            ],
        )

    def test_delay_creates_schedule_then_waiting(self) -> None:
        definition = self.store.create_definition(
            name="delay-ok",
            graph=self._delay_graph(30),
            status=WorkflowDefinitionStatus.ACTIVE,
        )
        ex = self.store.create_execution(workflow_id=definition.workflow_id)
        record = self.runtime.advance_one_step(ex.execution_id)
        # Trigger auto-continues into delay within same advance.
        execution = self.store.get_execution(ex.execution_id)
        assert execution is not None
        self.assertEqual(execution.state, WorkflowExecutionState.WAITING)
        self.assertEqual((execution.metadata or {}).get("wait_reason"), "WAITING_DELAY")
        sched_id = (execution.metadata or {}).get("delay_schedule_id")
        self.assertTrue(sched_id)
        sched = self.schedules.get(str(sched_id))
        self.assertIsNotNone(sched)
        self.assertEqual(sched.status, ScheduleStatus.ACTIVE)
        self.assertTrue((sched.metadata or {}).get("one_shot"))
        # Worker must not busy-poll: still waiting before deadline.
        again = self.runtime.advance_one_step(ex.execution_id)
        self.assertEqual(self.store.get_execution(ex.execution_id).state, WorkflowExecutionState.WAITING)

    def test_delay_schedule_store_failure_fails_execution(self) -> None:
        definition = self.store.create_definition(
            name="delay-fail",
            graph=self._delay_graph(10),
            status=WorkflowDefinitionStatus.ACTIVE,
        )
        ex = self.store.create_execution(workflow_id=definition.workflow_id)
        broken = MagicMock()
        broken.create.side_effect = RuntimeError("schedule db down")
        self.runtime.bind_schedule_store(broken)
        self.runtime.advance_one_step(ex.execution_id)
        execution = self.store.get_execution(ex.execution_id)
        assert execution is not None
        self.assertEqual(execution.state, WorkflowExecutionState.FAILED)
        self.assertIn("DELAY_WAKEUP_UNAVAILABLE", execution.error or "")
        self.assertNotEqual((execution.metadata or {}).get("wait_reason"), "WAITING_DELAY")

    def test_delay_missing_schedule_store_with_job_runtime_fails(self) -> None:
        runtime = WorkflowRuntime(self.store, self.gateway, job_runtime=self.jobs, schedule_store=None)
        definition = self.store.create_definition(
            name="delay-nosched",
            graph=self._delay_graph(5),
            status=WorkflowDefinitionStatus.ACTIVE,
        )
        ex = self.store.create_execution(workflow_id=definition.workflow_id)
        runtime.advance_one_step(ex.execution_id)
        execution = self.store.get_execution(ex.execution_id)
        self.assertEqual(execution.state, WorkflowExecutionState.FAILED)
        self.assertIn("DELAY_WAKEUP_UNAVAILABLE", execution.error or "")

    def test_delay_wakeup_after_deadline_and_duplicate_delivery(self) -> None:
        definition = self.store.create_definition(
            name="delay-wake",
            graph=self._delay_graph(60),
            status=WorkflowDefinitionStatus.ACTIVE,
        )
        ex = self.store.create_execution(workflow_id=definition.workflow_id)
        self.runtime.advance_one_step(ex.execution_id)
        execution = self.store.get_execution(ex.execution_id)
        assert execution is not None
        meta = dict(execution.metadata or {})
        meta["delay_resume_at"] = (datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat(
            timespec="seconds"
        )
        execution.metadata = meta
        self.store.save_execution(execution)

        first = self.runtime.advance_one_step(ex.execution_id)
        mid = self.store.get_execution(ex.execution_id)
        assert mid is not None
        self.assertEqual(mid.state, WorkflowExecutionState.RUNNING)
        self.assertIsNone((mid.metadata or {}).get("wait_reason"))
        # Duplicate wake-up is idempotent — no second move / no crash.
        self.runtime.advance_one_step(ex.execution_id)
        # Drain remaining capability to complete.
        while True:
            cur = self.store.get_execution(ex.execution_id)
            if cur.state in {
                WorkflowExecutionState.COMPLETED,
                WorkflowExecutionState.FAILED,
                WorkflowExecutionState.CANCELLED,
                WorkflowExecutionState.WAITING,
                WorkflowExecutionState.WAITING_APPROVAL,
            }:
                break
            self.runtime.advance_one_step(ex.execution_id)
        final = self.store.get_execution(ex.execution_id)
        self.assertEqual(final.state, WorkflowExecutionState.COMPLETED)

    def test_cancel_while_waiting_delay_disables_schedule(self) -> None:
        definition = self.store.create_definition(
            name="delay-cancel",
            graph=self._delay_graph(120),
            status=WorkflowDefinitionStatus.ACTIVE,
        )
        ex = self.store.create_execution(workflow_id=definition.workflow_id)
        self.runtime.advance_one_step(ex.execution_id)
        execution = self.store.get_execution(ex.execution_id)
        sched_id = str((execution.metadata or {}).get("delay_schedule_id"))
        self.runtime.cancel(ex.execution_id)
        cancelled = self.store.get_execution(ex.execution_id)
        self.assertEqual(cancelled.state, WorkflowExecutionState.CANCELLED)
        sched = self.schedules.get(sched_id)
        self.assertEqual(sched.status, ScheduleStatus.DISABLED)

    def test_process_restart_preserves_delay_wakeup(self) -> None:
        definition = self.store.create_definition(
            name="delay-restart",
            graph=self._delay_graph(90),
            status=WorkflowDefinitionStatus.ACTIVE,
        )
        ex = self.store.create_execution(workflow_id=definition.workflow_id)
        self.runtime.advance_one_step(ex.execution_id)
        execution = self.store.get_execution(ex.execution_id)
        sched_id = (execution.metadata or {}).get("delay_schedule_id")
        # Simulate process restart: new store/runtime, same DB.
        store2 = WorkflowStore(self.db)
        store2.initialize()
        schedules2 = ScheduleStore(self.db)
        schedules2.initialize()
        runtime2 = WorkflowRuntime(
            store2, self.gateway, job_runtime=self.jobs, schedule_store=schedules2
        )
        reloaded = store2.get_execution(ex.execution_id)
        self.assertEqual(reloaded.state, WorkflowExecutionState.WAITING)
        self.assertEqual((reloaded.metadata or {}).get("delay_schedule_id"), sched_id)
        self.assertIsNotNone(schedules2.get(str(sched_id)))

    def test_scheduler_duplicate_delivery_idempotent(self) -> None:
        definition = self.store.create_definition(
            name="delay-sched",
            graph=self._delay_graph(1),
            status=WorkflowDefinitionStatus.ACTIVE,
        )
        ex = self.store.create_execution(workflow_id=definition.workflow_id)
        self.runtime.advance_one_step(ex.execution_id)
        execution = self.store.get_execution(ex.execution_id)
        meta = dict(execution.metadata or {})
        # Force due immediately.
        sched_id = str(meta["delay_schedule_id"])
        with self.schedules.connect() as conn:
            conn.execute(
                "UPDATE schedules SET next_run_at = ? WHERE schedule_id = ?",
                (
                    (datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat(timespec="seconds"),
                    sched_id,
                ),
            )
        meta["delay_resume_at"] = (datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat(
            timespec="seconds"
        )
        execution.metadata = meta
        self.store.save_execution(execution)

        runner = ScheduleRunner(self.schedules, jobs=self.jobs, workflows=self.runtime)
        first = runner.tick_enqueue_only()
        self.assertTrue(any(r.get("ok") for r in first if r.get("schedule_id") == sched_id))
        # Second tick: schedule disabled after one-shot — no busy re-fire.
        second = runner.tick_enqueue_only()
        self.assertFalse(any(r.get("schedule_id") == sched_id and r.get("ok") for r in second))

    def test_approval_wait_resume_and_reject(self) -> None:
        graph = WorkflowGraph(
            nodes=[
                WorkflowNodeDef(node_id="t", kind=WorkflowNodeKind.TRIGGER, label="t", config={}),
                WorkflowNodeDef(
                    node_id="write",
                    kind=WorkflowNodeKind.CAPABILITY,
                    label="write",
                    config={
                        "capability_id": "artifact.create_text",
                        "arguments": {"content": "needs-appr", "filename": "w.txt"},
                    },
                ),
            ],
            edges=[WorkflowEdgeDef(edge_id="t-w", source="t", target="write")],
        )
        definition = self.store.create_definition(
            name="appr", graph=graph, status=WorkflowDefinitionStatus.ACTIVE
        )
        ex = self.store.create_execution(workflow_id=definition.workflow_id)
        self.runtime.advance_one_step(ex.execution_id)
        waiting = self.store.get_execution(ex.execution_id)
        self.assertEqual(waiting.state, WorkflowExecutionState.WAITING_APPROVAL)
        pending = (waiting.metadata or {}).get("pending_approval") or {}
        self.assertEqual(pending.get("node_id"), "write")
        self.assertEqual(pending.get("capability_id"), "artifact.create_text")
        self.assertTrue(pending.get("args_fingerprint"))
        # Advance while waiting must not rerun / busy-poll.
        self.runtime.advance_one_step(ex.execution_id)
        self.assertEqual(
            self.store.get_execution(ex.execution_id).state,
            WorkflowExecutionState.WAITING_APPROVAL,
        )

        # Reject path
        rejected = self.runtime.resume_with_approval(ex.execution_id, decision="rejected")
        self.assertEqual(rejected.state, WorkflowState.FAILED)
        self.assertEqual(self.store.get_execution(ex.execution_id).error, "APPROVAL_REJECTED")

        # Fresh execution for approve path
        ex2 = self.store.create_execution(workflow_id=definition.workflow_id)
        self.runtime.advance_one_step(ex2.execution_id)
        pending_req = self.approvals.request(
            capability_id="artifact.create_text",
            side_effects=(SideEffect.WRITE,),
            requested_by="test",
        )
        approved = self.approvals.approve(pending_req.approval_id, decided_by="operator")
        before_nodes = list(self.store.get_execution(ex2.execution_id).node_results or [])
        record = self.runtime.resume_with_approval(
            ex2.execution_id, approval_id=approved.approval_id, decision="approved"
        )
        after = self.store.get_execution(ex2.execution_id)
        self.assertEqual(after.state, WorkflowExecutionState.COMPLETED)
        # Trigger receipt preserved; write completed — no rewind of earlier nodes.
        self.assertGreaterEqual(len(after.node_results), len(before_nodes))
        write_statuses = [r.get("status") for r in after.node_results if r.get("node_id") == "write"]
        self.assertIn("COMPLETED", write_statuses)
        self.assertIn("WAITING_APPROVAL", write_statuses)

    def test_gateway_returns_approval_required_status(self) -> None:
        result = self.gateway.execute(
            CapabilityRequest(
                capability_id="artifact.create_text",
                arguments={"content": "x", "filename": "x.txt"},
            )
        )
        self.assertEqual(result.status, CapabilityStatus.APPROVAL_REQUIRED)
        self.assertEqual(result.telemetry.get("reason"), "approval_required")

    def test_idempotency_key_reuses_across_history(self) -> None:
        definition = self.store.create_definition(
            name="idem",
            steps=[
                WorkflowStepDef(
                    step_id="s1",
                    capability_id="file.read",
                    arguments={"path": str(self.note)},
                )
            ],
            status=WorkflowDefinitionStatus.ACTIVE,
        )
        # Seed >20 historical terminal executions (same key allowed after terminal).
        for i in range(22):
            past = self.store.create_execution(
                workflow_id=definition.workflow_id,
                idempotency_key=f"hist-{i}",
            )
            past.state = WorkflowExecutionState.COMPLETED
            self.store.save_execution(past)

        e1, _ = self.runtime.run_definition(definition.workflow_id, idempotency_key="live-key")
        e2, _ = self.runtime.run_definition(definition.workflow_id, idempotency_key="live-key")
        self.assertEqual(e1.execution_id, e2.execution_id)
        self.assertEqual(e1.idempotency_key, "live-key")
        # New key creates a distinct execution.
        e3, _ = self.runtime.run_definition(definition.workflow_id, idempotency_key="other-key")
        self.assertNotEqual(e1.execution_id, e3.execution_id)

    def test_idempotency_concurrent_starts(self) -> None:
        definition = self.store.create_definition(
            name="idem-race",
            steps=[
                WorkflowStepDef(
                    step_id="s1",
                    capability_id="file.read",
                    arguments={"path": str(self.note)},
                )
            ],
            status=WorkflowDefinitionStatus.ACTIVE,
            config={"max_concurrent_executions": 0},
        )
        results: list[str] = []
        errors: list[BaseException] = []

        def starter() -> None:
            try:
                ex, _ = self.runtime.run_definition(
                    definition.workflow_id, idempotency_key="race-key"
                )
                results.append(ex.execution_id)
            except BaseException as exc:  # noqa: BLE001
                errors.append(exc)

        threads = [threading.Thread(target=starter) for _ in range(8)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        self.assertFalse(errors)
        self.assertEqual(len(set(results)), 1)
        active = self.store.count_executions(
            workflow_id=definition.workflow_id,
            states=[
                WorkflowExecutionState.QUEUED.value,
                WorkflowExecutionState.STARTING.value,
                WorkflowExecutionState.RUNNING.value,
                WorkflowExecutionState.WAITING.value,
                WorkflowExecutionState.WAITING_APPROVAL.value,
            ],
        )
        self.assertEqual(active, 1)

    def test_concurrency_limit_transactional(self) -> None:
        definition = self.store.create_definition(
            name="conc",
            steps=[
                WorkflowStepDef(
                    step_id="s1",
                    capability_id="file.read",
                    arguments={"path": str(self.note)},
                )
            ],
            status=WorkflowDefinitionStatus.ACTIVE,
            config={"max_concurrent_executions": 2},
        )
        a, _ = self.runtime.run_definition(definition.workflow_id)
        b, _ = self.runtime.run_definition(definition.workflow_id)
        self.assertNotEqual(a.execution_id, b.execution_id)
        with self.assertRaises(ValueError) as ctx:
            self.runtime.run_definition(definition.workflow_id)
        self.assertIn("max concurrent", str(ctx.exception))

        # Race: many threads against limit=1
        definition2 = self.store.create_definition(
            name="conc-race",
            steps=[
                WorkflowStepDef(
                    step_id="s1",
                    capability_id="file.read",
                    arguments={"path": str(self.note)},
                )
            ],
            status=WorkflowDefinitionStatus.ACTIVE,
            config={"max_concurrent_executions": 1},
        )
        wins: list[str] = []
        rejects = 0
        lock = threading.Lock()

        def try_start() -> None:
            nonlocal rejects
            try:
                ex, _ = self.runtime.run_definition(definition2.workflow_id)
                with lock:
                    wins.append(ex.execution_id)
            except ValueError:
                with lock:
                    rejects += 1

        threads = [threading.Thread(target=try_start) for _ in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        self.assertEqual(len(set(wins)), 1)
        self.assertEqual(rejects, 9)

    def test_secret_variables_reject_plaintext(self) -> None:
        definition = self.store.create_definition(
            name="secrets",
            steps=[
                WorkflowStepDef(
                    step_id="s1",
                    capability_id="file.read",
                    arguments={"path": str(self.note)},
                )
            ],
            status=WorkflowDefinitionStatus.ACTIVE,
            variables=[
                WorkflowVariableDef(
                    name="api_token",
                    var_type="secret_ref",
                    required=True,
                    secret=True,
                    default="plaintext-not-allowed",
                )
            ],
        )
        with self.assertRaises(ValueError) as ctx:
            self.runtime.run_definition(definition.workflow_id)
        self.assertIn("VARIABLE_VALIDATION_FAILED", str(ctx.exception))

        # Resolvable secret ref is accepted.
        ok_def = self.store.create_definition(
            name="secrets-ok",
            steps=[
                WorkflowStepDef(
                    step_id="s1",
                    capability_id="file.read",
                    arguments={"path": str(self.note)},
                )
            ],
            status=WorkflowDefinitionStatus.ACTIVE,
            variables=[
                WorkflowVariableDef(
                    name="api_token",
                    var_type="secret_ref",
                    required=True,
                    secret=True,
                    default="secret:LEVIATHAN_TEST_TOKEN",
                )
            ],
        )
        ex, _ = self.runtime.run_definition(ok_def.workflow_id)
        snap = ex.input_snapshot.get("api_token")
        self.assertTrue(isinstance(snap, dict) and snap.get("secret"))


if __name__ == "__main__":
    unittest.main()
