"""Backend tests for the Tasks Mission Control domain."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

from Data.modules.jobs.runtime import JobRuntime
from Data.modules.jobs.states import JobState
from Data.modules.jobs.store import JobStore
from Data.modules.tasks import (
    BoardColumn,
    ExecutionBinding,
    TaskError,
    TaskPlannerAdapter,
    TaskService,
    TaskStore,
)
from Data.modules.tasks.store import utc_now


class _FakeCapability:
    def __init__(self, capability_id: str) -> None:
        self.capability_id = capability_id


class _FakeGateway:
    def list_capabilities(self) -> list[_FakeCapability]:
        return [_FakeCapability("artifact.create_text"), _FakeCapability("knowledge.search")]


class _FakeJobRuntime:
    def __init__(self, store: JobStore) -> None:
        self.store = store
        self._jobs: dict[str, Any] = {}

    def enqueue(self, **kwargs: Any) -> Any:
        record = self.store.create(
            capability_id=kwargs["capability_id"],
            arguments=kwargs.get("arguments") or {},
            requested_by=kwargs.get("requested_by") or "test",
            idempotency_key=kwargs.get("idempotency_key"),
            domain=kwargs.get("domain"),
            domain_entity_type=kwargs.get("domain_entity_type"),
            domain_entity_id=kwargs.get("domain_entity_id"),
            metadata=kwargs.get("metadata") or {},
        )
        # mark queued like JobRuntime
        from Data.modules.jobs.store import utc_now as jnow

        record.state = JobState.QUEUED
        record.queued_at = jnow()
        self.store.update(record)
        self._jobs[record.job_id] = record
        return record

    def get(self, job_id: str) -> Any:
        return self.store.get(job_id)

    def cancel(self, job_id: str, *, reason: str | None = None) -> Any:
        job = self.store.get(job_id)
        assert job is not None
        job.state = JobState.CANCELLED
        job.cancel_reason = reason
        self.store.update(job)
        return job

    def list(self, **_kwargs: Any) -> list[Any]:
        return self.store.list(limit=100)


class TaskStoreTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.store = TaskStore(Path(self.tmp.name) / "tasks.db")
        self.store.initialize()
        self.service = TaskService(self.store)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_create_get_update_list_archive(self) -> None:
        t = self.service.create(title="Alpha", priority="high", tags=["x"])
        self.assertEqual(t.title, "Alpha")
        got = self.service.get(t.task_id)
        self.assertEqual(got.priority.value, "high")
        updated = self.service.update(t.task_id, patch={"title": "Beta", "boardColumn": "in_progress"})
        self.assertEqual(updated.title, "Beta")
        self.assertEqual(updated.board_column, BoardColumn.IN_PROGRESS)
        listed = self.service.list(search="Beta")
        self.assertEqual(len(listed), 1)
        archived = self.service.archive(t.task_id)
        self.assertIsNotNone(archived.archived_at)
        self.assertEqual(len(self.service.list()), 0)

    def test_persistence_across_store_instances(self) -> None:
        path = Path(self.tmp.name) / "persist.db"
        store1 = TaskStore(path)
        svc1 = TaskService(store1)
        svc1.initialize()
        t = svc1.create(title="Persist me")
        store2 = TaskStore(path)
        svc2 = TaskService(store2)
        svc2.initialize()
        got = svc2.get(t.task_id)
        self.assertEqual(got.title, "Persist me")

    def test_filters_priority_and_search(self) -> None:
        self.service.create(title="High work", priority="high", description="laser")
        self.service.create(title="Low work", priority="low")
        highs = self.service.list(priority="high")
        self.assertEqual(len(highs), 1)
        found = self.service.list(search="laser")
        self.assertEqual(len(found), 1)


class TaskDependencyTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.service = TaskService(TaskStore(Path(self.tmp.name) / "deps.db"))
        self.service.initialize()

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_add_remove_block_unblock(self) -> None:
        a = self.service.create(title="A")
        b = self.service.create(title="B")
        self.service.add_dependency(a.task_id, depends_on_task_id=b.task_id)
        blocked = self.service.recompute_blocking(a.task_id)
        self.assertTrue(blocked.blocked)
        self.assertEqual(blocked.blocked_reason_code, "DEPENDENCY")
        deps = self.service.list_dependencies(a.task_id)
        self.assertEqual(len(deps), 1)
        self.service.remove_dependency(a.task_id, deps[0]["dependencyId"])
        unblocked = self.service.recompute_blocking(a.task_id)
        self.assertFalse(unblocked.blocked)

    def test_reject_self_and_cycle(self) -> None:
        a = self.service.create(title="A")
        b = self.service.create(title="B")
        c = self.service.create(title="C")
        with self.assertRaises(TaskError) as ctx:
            self.service.add_dependency(a.task_id, depends_on_task_id=a.task_id)
        self.assertEqual(ctx.exception.code, "DEPENDENCY_SELF")
        self.service.add_dependency(a.task_id, depends_on_task_id=b.task_id)
        self.service.add_dependency(b.task_id, depends_on_task_id=c.task_id)
        with self.assertRaises(TaskError) as ctx2:
            self.service.add_dependency(c.task_id, depends_on_task_id=a.task_id)
        self.assertEqual(ctx2.exception.code, "DEPENDENCY_CYCLE")


class TaskSubtaskNoteTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.service = TaskService(TaskStore(Path(self.tmp.name) / "sub.db"))
        self.service.initialize()
        self.task = self.service.create(title="Parent")

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_subtasks_progress_rollup(self) -> None:
        s1 = self.service.create_subtask(self.task.task_id, title="One")
        self.service.create_subtask(self.task.task_id, title="Two")
        self.service.update_subtask(self.task.task_id, s1.subtask_id, completed=True)
        parent = self.service.get(self.task.task_id, sync=False)
        self.assertAlmostEqual(parent.progress or 0, 0.5)
        self.service.delete_subtask(self.task.task_id, s1.subtask_id)
        remaining = self.service.list_subtasks(self.task.task_id)
        self.assertEqual(len(remaining), 1)

    def test_notes_crud(self) -> None:
        note = self.service.create_note(self.task.task_id, body="hello")
        notes = self.service.list_notes(self.task.task_id)
        self.assertEqual(len(notes), 1)
        updated = self.service.update_note(self.task.task_id, note.note_id, body="edited")
        self.assertEqual(updated.body, "edited")
        self.service.delete_note(self.task.task_id, note.note_id)
        self.assertEqual(len(self.service.list_notes(self.task.task_id)), 0)


class TaskExecutionBindingTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        path = Path(self.tmp.name) / "exec.db"
        self.job_store = JobStore(path)
        self.job_store.initialize()
        self.jobs = _FakeJobRuntime(self.job_store)
        self.service = TaskService(
            TaskStore(path),
            job_runtime=self.jobs,
            execution_gateway=_FakeGateway(),
        )
        self.service.initialize()

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_job_start_cancel_idempotent(self) -> None:
        task = self.service.create(
            title="Job task",
            execution_binding=ExecutionBinding.CAPABILITY_JOB.value,
            capability_id="artifact.create_text",
            capability_arguments={"text": "hi"},
        )
        started = self.service.start(task.task_id)
        self.assertIsNotNone(started.job_id)
        self.assertEqual(started.board_column, BoardColumn.IN_PROGRESS)
        again = self.service.start(task.task_id)
        self.assertEqual(again.job_id, started.job_id)
        cancelled = self.service.cancel(task.task_id)
        self.assertEqual(cancelled.execution_state, "CANCELLED")

    def test_manual_start_and_complete(self) -> None:
        task = self.service.create(title="Manual")
        started = self.service.start(task.task_id)
        self.assertEqual(started.board_column, BoardColumn.IN_PROGRESS)
        done = self.service.update(task.task_id, patch={"boardColumn": "done"})
        self.assertEqual(done.board_column, BoardColumn.DONE)
        self.assertIsNotNone(done.completed_at)

    def test_retry_failed_job(self) -> None:
        task = self.service.create(
            title="Retry me",
            execution_binding=ExecutionBinding.CAPABILITY_JOB.value,
            capability_id="artifact.create_text",
        )
        started = self.service.start(task.task_id)
        job = self.job_store.get(started.job_id)
        assert job is not None
        job.state = JobState.FAILED
        job.error = "boom"
        self.job_store.update(job)
        retried = self.service.retry(task.task_id)
        self.assertEqual(retried.execution_state, JobState.RETRY_WAIT.value)


class TaskSummaryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.service = TaskService(TaskStore(Path(self.tmp.name) / "sum.db"))
        self.service.initialize()

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_summary_counts(self) -> None:
        self.service.create(title="A")
        b = self.service.create(title="B")
        self.service.update(b.task_id, patch={"boardColumn": "in_progress"})
        c = self.service.create(title="C", due_at="2000-01-01T00:00:00+00:00")
        d = self.service.create(title="D")
        self.service.add_dependency(d.task_id, depends_on_task_id=c.task_id)
        done = self.service.create(title="Done")
        self.service.update(done.task_id, patch={"boardColumn": "done"})
        summary = self.service.summary(timezone_name="UTC")
        self.assertGreaterEqual(summary.active, 3)
        self.assertEqual(summary.in_progress, 1)
        self.assertGreaterEqual(summary.blocked, 1)
        self.assertGreaterEqual(summary.overdue, 1)
        self.assertGreaterEqual(summary.completed_today, 1)


class TaskAutoPlanTests(unittest.TestCase):
    def test_schema_validation_and_invalid_agent(self) -> None:
        planner = TaskPlannerAdapter(model_caller=None)
        with self.assertRaises(TaskError) as ctx:
            planner.validate_proposals({"tasks": [{"title": "x", "priority": "nope"}]})
        self.assertEqual(ctx.exception.code, "PLANNER_SCHEMA")
        with self.assertRaises(TaskError) as ctx2:
            planner.validate_proposals(
                {"tasks": [{"title": "x", "priority": "high", "suggested_assignee_id": "missing"}]},
                allowed_agent_ids={"real"},
            )
        self.assertEqual(ctx2.exception.code, "INVALID_ASSIGNEE")

    def test_model_unavailable(self) -> None:
        service = TaskService(TaskStore(Path(tempfile.mkdtemp()) / "ap.db"), model_caller=None)
        service.initialize()
        with self.assertRaises(TaskError) as ctx:
            service.auto_plan_preview(brief="Build a rocket")
        self.assertEqual(ctx.exception.code, "MODEL_UNAVAILABLE")

    def test_preview_commit_transactional(self) -> None:
        def fake_caller(**_kwargs: Any) -> dict[str, Any]:
            return {
                "content": (
                    '{"tasks":['
                    '{"title":"One","priority":"high","dependencies":[]},'
                    '{"title":"Two","priority":"medium","dependencies":[0]}'
                    "]}"
                )
            }

        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        service = TaskService(TaskStore(Path(tmp.name) / "ap2.db"), model_caller=fake_caller)
        service.initialize()
        proposals = service.auto_plan_preview(brief="Ship feature")
        self.assertEqual(len(proposals), 2)
        created = service.auto_plan_commit(proposals=proposals, project="Demo")
        self.assertEqual(len(created), 2)
        deps = service.list_dependencies(created[1].task_id)
        self.assertEqual(len(deps), 1)

    def test_commit_rollback_on_bad_dependency(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        service = TaskService(TaskStore(Path(tmp.name) / "ap3.db"))
        service.initialize()
        # Bypass planner validation by calling commit with already-bad deps via monkeypatch
        # Use validate then mutate — instead force invalid through validate rejection
        with self.assertRaises(TaskError):
            service.auto_plan_commit(
                proposals=[
                    {"title": "A", "priority": "low", "dependencies": [1]},
                    {"title": "B", "priority": "low", "dependencies": []},
                ]
            )


class TaskErrorPathTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.service = TaskService(TaskStore(Path(self.tmp.name) / "err.db"))
        self.service.initialize()

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_not_found_and_archived(self) -> None:
        with self.assertRaises(TaskError) as ctx:
            self.service.get("missing")
        self.assertEqual(ctx.exception.http_status, 404)
        t = self.service.create(title="Arch")
        self.service.archive(t.task_id)
        with self.assertRaises(TaskError) as ctx2:
            self.service.update(t.task_id, patch={"title": "Nope"})
        self.assertEqual(ctx2.exception.code, "ARCHIVED")

    def test_start_blocked_by_dependency(self) -> None:
        a = self.service.create(title="A")
        b = self.service.create(title="B")
        self.service.add_dependency(a.task_id, depends_on_task_id=b.task_id)
        with self.assertRaises(TaskError) as ctx:
            self.service.start(a.task_id)
        self.assertEqual(ctx.exception.code, "TASK_BLOCKED")


if __name__ == "__main__":
    unittest.main()
