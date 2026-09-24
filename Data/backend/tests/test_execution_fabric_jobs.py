from __future__ import annotations

import tempfile
import threading
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from Data.backend.migrations import MigrationRunner
from Data.modules.jobs import (
    JobState,
    JobStore,
    LatencyClass,
    PRIORITY_BACKGROUND,
    PRIORITY_INTERACTIVE,
    RetryPolicy,
    aged_priority,
    priority_for_latency_class,
    validate_job_transition,
)
from Data.modules.jobs.states import InvalidJobTransition


class ExecutionFabricStateTests(unittest.TestCase):
    def test_cancel_requested_and_retry_wait_transitions(self) -> None:
        validate_job_transition(JobState.RUNNING, JobState.CANCEL_REQUESTED)
        validate_job_transition(JobState.CANCEL_REQUESTED, JobState.CANCELLED)
        validate_job_transition(JobState.RUNNING, JobState.RETRY_WAIT)
        validate_job_transition(JobState.RETRY_WAIT, JobState.RUNNING)
        with self.assertRaises(InvalidJobTransition):
            validate_job_transition(JobState.RUNNING, JobState.CANCELLED)


class ConcurrentClaimTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.store = JobStore(Path(self.tmp.name) / "jobs.db")
        self.store.initialize()
        job = self.store.create(capability_id="noop", arguments={})
        self.store.transition(job.job_id, JobState.QUEUED)
        self.job_id = job.job_id

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_concurrent_claim_single_owner(self) -> None:
        results: list[str | None] = []
        barrier = threading.Barrier(2)
        lock = threading.Lock()

        def worker(worker_id: str) -> None:
            barrier.wait()
            claimed = self.store.claim_next_queued(worker_id=worker_id, lease_ttl_seconds=30.0)
            with lock:
                results.append(None if claimed is None else claimed.lease_owner)

        t1 = threading.Thread(target=worker, args=("w-a",))
        t2 = threading.Thread(target=worker, args=("w-b",))
        t1.start()
        t2.start()
        t1.join()
        t2.join()
        owners = [r for r in results if r is not None]
        self.assertEqual(len(owners), 1)
        self.assertIn(owners[0], {"w-a", "w-b"})
        job = self.store.get(self.job_id)
        assert job is not None
        self.assertEqual(job.state, JobState.RUNNING)
        self.assertEqual(job.lease_owner, owners[0])


class LeaseHeartbeatRecoveryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.store = JobStore(Path(self.tmp.name) / "jobs.db")
        self.store.initialize()

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_heartbeat_extends_lease_and_protects_live_job(self) -> None:
        job = self.store.create(capability_id="noop", arguments={})
        self.store.transition(job.job_id, JobState.QUEUED)
        claimed = self.store.claim_next_queued(worker_id="w1", lease_ttl_seconds=2.0)
        assert claimed is not None
        before = claimed.lease_expires_at
        assert before is not None
        extended = self.store.heartbeat_lease(job.job_id, worker_id="w1", ttl_seconds=60.0)
        self.assertEqual(extended.worker_id, "w1")
        self.assertGreater(extended.expires_at or "", before)
        with self.assertRaises(ValueError):
            self.store.heartbeat_lease(job.job_id, worker_id="w2", ttl_seconds=30.0)

        # Live (non-expired) lease must not be stolen by recovery.
        recovered = self.store.recover_expired_leases()
        self.assertEqual(recovered, [])
        live = self.store.get(job.job_id)
        assert live is not None
        self.assertEqual(live.state, JobState.RUNNING)
        self.assertEqual(live.lease_owner, "w1")

    def test_expired_lease_recovery_requeues(self) -> None:
        job = self.store.create(capability_id="noop", arguments={})
        self.store.transition(job.job_id, JobState.QUEUED)
        claimed = self.store.claim_next_queued(worker_id="w1", lease_ttl_seconds=1.0)
        assert claimed is not None
        past = (datetime.now(timezone.utc) - timedelta(seconds=5)).isoformat(timespec="seconds")
        with self.store.connect() as conn:
            conn.execute(
                "UPDATE jobs SET lease_expires_at = ? WHERE job_id = ?",
                (past, job.job_id),
            )
        expired = self.store.list_expired_leases()
        self.assertEqual(len(expired), 1)
        recovered = self.store.recover_expired_leases()
        self.assertEqual(len(recovered), 1)
        self.assertEqual(recovered[0].state, JobState.RETRY_WAIT)
        self.assertIsNone(recovered[0].lease_owner)
        self.assertEqual(recovered[0].error_code, "LEASE_EXPIRED")
        reclaimed = self.store.claim_next_queued(worker_id="w2", lease_ttl_seconds=30.0)
        assert reclaimed is not None
        self.assertEqual(reclaimed.lease_owner, "w2")
        self.assertEqual(reclaimed.attempt_number, 2)


class CancelPathTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.store = JobStore(Path(self.tmp.name) / "jobs.db")
        self.store.initialize()

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_cancel_queued_immediate_cancelled(self) -> None:
        queued = self.store.create(capability_id="noop", arguments={})
        self.store.transition(queued.job_id, JobState.QUEUED)
        cancelled = self.store.request_cancel(queued.job_id, reason="stop-queued")
        self.assertEqual(cancelled.state, JobState.CANCELLED)
        self.assertEqual(cancelled.cancel_reason, "stop-queued")

    def test_cancel_running_then_ack(self) -> None:
        running = self.store.create(capability_id="noop", arguments={})
        self.store.transition(running.job_id, JobState.QUEUED)
        claimed = self.store.claim_next_queued(worker_id="w1")
        assert claimed is not None
        pending = self.store.request_cancel(running.job_id, reason="stop-running")
        self.assertEqual(pending.state, JobState.CANCEL_REQUESTED)
        self.assertEqual(pending.cancel_reason, "stop-running")
        self.assertIsNotNone(pending.cancel_requested_at)
        acked = self.store.ack_cancel(running.job_id)
        self.assertEqual(acked.state, JobState.CANCELLED)


class RetryBackoffTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.store = JobStore(Path(self.tmp.name) / "jobs.db")
        self.store.initialize()
        self.policy = RetryPolicy(
            max_attempts=5,
            base_delay=2.0,
            max_delay=10.0,
            backoff="exponential",
            jitter=0.0,
        )

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_retry_backoff_bounded(self) -> None:
        delays = [self.policy.delay_for_attempt(i) for i in range(1, 6)]
        self.assertEqual(delays[0], 2.0)
        self.assertEqual(delays[1], 4.0)
        self.assertEqual(delays[2], 8.0)
        self.assertEqual(delays[3], 10.0)
        self.assertEqual(delays[4], 10.0)
        self.assertTrue(all(d <= 10.0 for d in delays))

    def test_retryable_failure_goes_to_retry_wait(self) -> None:
        self.assertTrue(self.policy.classify_retryable(error_code="TIMEOUT"))
        job = self.store.create(capability_id="noop", arguments={}, max_attempts=5)
        self.store.transition(job.job_id, JobState.QUEUED)
        claimed = self.store.claim_next_queued(worker_id="w1")
        assert claimed is not None
        delay = self.policy.delay_for_attempt(claimed.attempt_number)
        retried = self.store.schedule_retry(
            claimed.job_id,
            delay_seconds=delay,
            error="transient timeout",
            error_code="TIMEOUT",
            retryable=True,
        )
        self.assertEqual(retried.state, JobState.RETRY_WAIT)
        self.assertTrue(retried.retryable)
        self.assertEqual(retried.error_code, "TIMEOUT")
        self.assertIsNotNone(retried.next_attempt_at)
        assert retried.next_attempt_at is not None
        next_at = datetime.fromisoformat(retried.next_attempt_at.replace("Z", "+00:00"))
        if next_at.tzinfo is None:
            next_at = next_at.replace(tzinfo=timezone.utc)
        self.assertGreaterEqual(
            (next_at - datetime.now(timezone.utc)).total_seconds(),
            delay - 1.0,
        )

    def test_non_retryable_failure_goes_to_failed(self) -> None:
        self.assertFalse(self.policy.classify_retryable(error_code="REJECTED"))
        job = self.store.create(capability_id="noop", arguments={})
        self.store.transition(job.job_id, JobState.QUEUED)
        claimed = self.store.claim_next_queued(worker_id="w1")
        assert claimed is not None
        failed = self.store.transition(
            claimed.job_id,
            JobState.FAILED,
            error="policy rejected",
            error_code="REJECTED",
            retryable=False,
        )
        self.assertEqual(failed.state, JobState.FAILED)
        self.assertFalse(failed.retryable)
        self.assertEqual(failed.error_code, "REJECTED")


class PriorityOrderingTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.store = JobStore(Path(self.tmp.name) / "jobs.db")
        self.store.initialize()

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_lower_priority_number_claimed_first(self) -> None:
        self.assertEqual(priority_for_latency_class(LatencyClass.INTERACTIVE), PRIORITY_INTERACTIVE)
        self.assertEqual(priority_for_latency_class("background"), PRIORITY_BACKGROUND)

        low = self.store.create(capability_id="noop", arguments={}, priority=200)
        high = self.store.create(capability_id="noop", arguments={}, priority=10)
        self.store.transition(low.job_id, JobState.QUEUED)
        self.store.transition(high.job_id, JobState.QUEUED)

        first = self.store.claim_next_queued(worker_id="w1")
        assert first is not None
        self.assertEqual(first.job_id, high.job_id)

    def test_aging_eventually_runs_low_priority(self) -> None:
        # Medium-priority new job vs aged low-priority that has been boosted.
        medium = self.store.create(capability_id="noop", arguments={}, priority=80)
        low = self.store.create(capability_id="noop", arguments={}, priority=100)
        self.store.transition(medium.job_id, JobState.QUEUED)
        self.store.transition(low.job_id, JobState.QUEUED)

        past = (datetime.now(timezone.utc) - timedelta(hours=2)).isoformat(timespec="seconds")
        with self.store.connect() as conn:
            conn.execute(
                "UPDATE jobs SET created_at = ? WHERE job_id = ?",
                (past, low.job_id),
            )

        aged = aged_priority(100, created_at=past, aging_seconds=60.0, max_boost=50)
        self.assertLess(aged, 80.0)

        # Persist effective (aged) priority so claim ordering reflects starvation relief.
        with self.store.connect() as conn:
            conn.execute(
                "UPDATE jobs SET priority = ? WHERE job_id = ?",
                (int(aged), low.job_id),
            )

        first = self.store.claim_next_queued(worker_id="w-age")
        assert first is not None
        self.assertEqual(first.job_id, low.job_id)


class ParentChildIdempotencyTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.store = JobStore(Path(self.tmp.name) / "jobs.db")
        self.store.initialize()

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_parent_child_and_idempotency_key_reuse(self) -> None:
        parent = self.store.create(
            capability_id="parent.op",
            arguments={},
            idempotency_key="parent-idem-1",
        )
        self.store.transition(parent.job_id, JobState.QUEUED)

        child_a = self.store.create(
            capability_id="child.op",
            arguments={"step": 1},
            parent_job_id=parent.job_id,
            root_job_id=parent.job_id,
            idempotency_key="child-idem-1",
        )
        child_b = self.store.create(
            capability_id="child.op",
            arguments={"step": 1},
            parent_job_id=parent.job_id,
            root_job_id=parent.job_id,
            idempotency_key="child-idem-1",
        )
        self.assertEqual(child_a.job_id, child_b.job_id)
        self.assertEqual(child_a.parent_job_id, parent.job_id)
        self.assertEqual(child_a.root_job_id, parent.job_id)

        self.store.transition(child_a.job_id, JobState.QUEUED)
        children = self.store.list_children(parent.job_id)
        self.assertEqual(len(children), 1)
        self.assertEqual(children[0].job_id, child_a.job_id)

        again = self.store.create(
            capability_id="parent.op",
            arguments={},
            idempotency_key="parent-idem-1",
        )
        self.assertEqual(again.job_id, parent.job_id)


class Migration36Tests(unittest.TestCase):
    def test_migration_adds_fabric_tables_and_columns(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "m.db"
            MigrationRunner(path).apply_all()
            import sqlite3

            with sqlite3.connect(path) as conn:
                tables = {
                    row[0]
                    for row in conn.execute(
                        "SELECT name FROM sqlite_master WHERE type='table'"
                    ).fetchall()
                }
                self.assertIn("worker_pools", tables)
                self.assertIn("worker_instances", tables)
                self.assertIn("resource_reservations", tables)
                self.assertIn("supervisor_leases", tables)
                cols = {row[1] for row in conn.execute("PRAGMA table_info(jobs)").fetchall()}
                self.assertIn("priority", cols)
                self.assertIn("worker_pool", cols)
                self.assertIn("next_attempt_at", cols)
                self.assertIn("cancel_requested_at", cols)


if __name__ == "__main__":
    unittest.main()
