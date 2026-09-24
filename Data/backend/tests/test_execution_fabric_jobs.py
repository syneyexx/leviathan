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

    def test_heartbeat_extends_lease(self) -> None:
        job = self.store.create(capability_id="noop", arguments={})
        self.store.transition(job.job_id, JobState.QUEUED)
        claimed = self.store.claim_next_queued(worker_id="w1", lease_ttl_seconds=2.0)
        assert claimed is not None
        before = claimed.lease_expires_at
        assert before is not None
        extended = self.store.heartbeat_lease(job.job_id, worker_id="w1", ttl_seconds=30.0)
        self.assertEqual(extended.worker_id, "w1")
        self.assertGreater(extended.expires_at or "", before)
        with self.assertRaises(ValueError):
            self.store.heartbeat_lease(job.job_id, worker_id="w2", ttl_seconds=30.0)

    def test_expired_lease_recovery(self) -> None:
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
        # Ready for reclaim (next_attempt_at <= now)
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

    def test_cancel_queued_vs_running(self) -> None:
        queued = self.store.create(capability_id="noop", arguments={})
        self.store.transition(queued.job_id, JobState.QUEUED)
        cancelled = self.store.request_cancel(queued.job_id, reason="stop-queued")
        self.assertEqual(cancelled.state, JobState.CANCELLED)

        running = self.store.create(capability_id="noop", arguments={})
        self.store.transition(running.job_id, JobState.QUEUED)
        claimed = self.store.claim_next_queued(worker_id="w1")
        assert claimed is not None
        pending = self.store.request_cancel(running.job_id, reason="stop-running")
        self.assertEqual(pending.state, JobState.CANCEL_REQUESTED)
        self.assertEqual(pending.cancel_reason, "stop-running")
        acked = self.store.ack_cancel(running.job_id)
        self.assertEqual(acked.state, JobState.CANCELLED)


class RetryBackoffTests(unittest.TestCase):
    def test_retry_backoff_bounded(self) -> None:
        policy = RetryPolicy(
            max_attempts=5,
            base_delay=2.0,
            max_delay=10.0,
            backoff="exponential",
            jitter=0.0,
        )
        delays = [policy.delay_for_attempt(i) for i in range(1, 6)]
        self.assertEqual(delays[0], 2.0)
        self.assertEqual(delays[1], 4.0)
        self.assertEqual(delays[2], 8.0)
        self.assertEqual(delays[3], 10.0)
        self.assertEqual(delays[4], 10.0)
        self.assertTrue(all(d <= 10.0 for d in delays))
        self.assertFalse(policy.classify_retryable(error_code="REJECTED"))
        self.assertTrue(policy.classify_retryable(error_code="TIMEOUT"))


class PriorityOrderingTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.store = JobStore(Path(self.tmp.name) / "jobs.db")
        self.store.initialize()

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_priority_ordering_and_aging(self) -> None:
        self.assertEqual(priority_for_latency_class(LatencyClass.INTERACTIVE), PRIORITY_INTERACTIVE)
        self.assertEqual(priority_for_latency_class("background"), PRIORITY_BACKGROUND)

        low = self.store.create(capability_id="noop", arguments={}, priority=200)
        high = self.store.create(capability_id="noop", arguments={}, priority=10)
        self.store.transition(low.job_id, JobState.QUEUED)
        self.store.transition(high.job_id, JobState.QUEUED)
        # Force low to be older so aging matters for equal-priority cases later
        past = (datetime.now(timezone.utc) - timedelta(hours=2)).isoformat(timespec="seconds")
        with self.store.connect() as conn:
            conn.execute(
                "UPDATE jobs SET created_at = ? WHERE job_id = ?",
                (past, low.job_id),
            )

        first = self.store.claim_next_queued(worker_id="w1")
        assert first is not None
        self.assertEqual(first.job_id, high.job_id)

        # Aging helper: older job gets boosted (lower effective priority number)
        aged = aged_priority(200, created_at=past, aging_seconds=60.0, max_boost=50)
        self.assertLess(aged, 200.0)


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
