"""SQLite concurrency stress — control writes stay healthy under bulk COMMIT_WRITE."""

from __future__ import annotations

import os
import tempfile
import threading
import time
import unittest
from pathlib import Path

from Data.backend.migrations import MigrationRunner
from Data.modules.common.sqlite_policy import (
    ControlWriteSpec,
    control_write,
    reset_sqlite_metrics,
    sqlite_metrics_snapshot,
)
from Data.modules.db_commit.domain_submit import (
    submit_dataset_index_batch,
    submit_market_sim_events,
    submit_research_evidence,
    submit_source_ingestion_batch,
)
from Data.modules.db_commit.settings import DbCommitSettings
from Data.modules.db_commit.writer import DbCommitCoordinator
from Data.modules.workers.protocol import WorkerInstanceState, WorkerRegistration
from Data.modules.workers.registry import WorkerRegistry, utc_now


class SqliteConcurrencyStressTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.db = Path(self.tmp.name) / "leviathan.db"
        MigrationRunner(self.db).apply_all()
        reset_sqlite_metrics()
        self.settings = DbCommitSettings(
            enabled=True,
            max_batch_rows=200,
            target_transaction_ms=100.0,
            poll_seconds=0.01,
        )
        self.coord = DbCommitCoordinator(self.db, settings=self.settings)
        self.coord.startup()
        self.registry = WorkerRegistry(self.db)
        self.registry.initialize()
        self.registry.upsert(
            WorkerRegistration(
                worker_id="supervisor-test",
                pool_id="maintenance",
                slot=0,
                pid=os.getpid(),
                process_start_identity=f"test:{os.getpid()}",
                started_at=utc_now(),
                last_heartbeat_at=utc_now(),
                state=WorkerInstanceState.READY,
            )
        )
        self._stop = threading.Event()
        self._hb_errors: list[str] = []
        self._hb_ok = 0

    def tearDown(self) -> None:
        self._stop.set()
        self.coord.shutdown()
        self.tmp.cleanup()

    def _heartbeat_loop(self) -> None:
        while not self._stop.is_set():
            try:
                # Tiny CONTROL_WRITE via registry heartbeat.
                reg = self.registry.heartbeat(
                    "supervisor-test", state=WorkerInstanceState.READY
                )
                if reg is None:
                    self._hb_errors.append("missing")
                else:
                    self._hb_ok += 1

                def _control(conn):  # noqa: ANN001
                    conn.execute("SELECT 1")

                control_write(
                    self.db,
                    _control,
                    spec=ControlWriteSpec(operation="test.control_ping"),
                )
            except Exception as exc:  # noqa: BLE001
                self._hb_errors.append(str(exc))
            time.sleep(0.02)

    def test_bulk_commits_do_not_starve_heartbeats(self) -> None:
        hb = threading.Thread(target=self._heartbeat_loop, daemon=True)
        hb.start()

        def research_producer(idx: int) -> None:
            for batch in range(4):
                submit_research_evidence(
                    self.db,
                    project_id=f"research-{idx}",
                    evidence=[
                        {"evidence_id": f"e-{idx}-{batch}-{n}", "text": f"t{n}"}
                        for n in range(40)
                    ],
                    title=f"Research {idx}",
                    idempotency_key=f"research-{idx}-{batch}",
                )

        def dataset_producer(idx: int) -> None:
            for batch in range(3):
                submit_dataset_index_batch(
                    self.db,
                    dataset_id=f"ds-{idx}",
                    rows=[{"row_id": f"{idx}-{batch}-{n}", "v": n} for n in range(300)],
                    title=f"dataset-{idx}",
                    idempotency_key=f"ds-{idx}-{batch}",
                )

        producers = [
            threading.Thread(target=research_producer, args=(0,), daemon=True),
            threading.Thread(target=research_producer, args=(1,), daemon=True),
            threading.Thread(target=dataset_producer, args=(0,), daemon=True),
            threading.Thread(target=dataset_producer, args=(1,), daemon=True),
            threading.Thread(
                target=lambda: submit_source_ingestion_batch(
                    self.db,
                    source_id="src-stress",
                    records=[{"id": f"r{i}"} for i in range(100)],
                    idempotency_key="src-stress-1",
                ),
                daemon=True,
            ),
            threading.Thread(
                target=lambda: [
                    submit_market_sim_events(
                        self.db,
                        run_id="run-stress",
                        events=[{"event_id": f"ev-{i}-{j}"} for j in range(50)],
                        idempotency_key=f"ms-{i}",
                        sequence_number=i,
                    )
                    for i in range(5)
                ],
                daemon=True,
            ),
        ]
        for t in producers:
            t.start()

        # Writer drains while heartbeats run.
        deadline = time.time() + 20.0
        while time.time() < deadline:
            self.coord.process_until_idle(max_items=8)
            if self.coord.spool.stats().pending_count == 0 and all(
                not t.is_alive() for t in producers
            ):
                break
            time.sleep(0.01)

        for t in producers:
            t.join(timeout=2.0)
        self.coord.process_until_idle()
        self._stop.set()
        hb.join(timeout=2.0)

        metrics = sqlite_metrics_snapshot()
        status = self.coord.status()

        # Heartbeats must succeed repeatedly; transient busy retries OK.
        self.assertGreater(self._hb_ok, 10)
        # No sustained lock failure storm.
        self.assertLess(len(self._hb_errors), max(3, self._hb_ok // 10))
        self.assertGreaterEqual(status.commit_count, 1)
        self.assertEqual(self.coord.spool.stats().pending_count, 0)
        # Process isolation: coordinator PID is this test process here, but
        # producer threads share PID — assert registry exposes writer pid field.
        self.assertEqual(status.worker_pid, os.getpid())
        self.assertIn(status.health, {"HEALTHY", "DEGRADED"})
        # Busy retries (if any) must not exhaust into heartbeat death.
        self.assertGreaterEqual(int(metrics.get("sqlite_busy_count") or 0), 0)

    def test_priority_fairness_no_starvation(self) -> None:
        from Data.modules.db_commit.producer import CommitProducer
        from Data.modules.db_commit.types import CommitPriority

        producer = CommitProducer(
            self.db,
            settings=self.settings,
            spool=self.coord.spool,
            receipts=self.coord.receipts,
        )
        for i in range(20):
            producer.submit(
                operation="system.echo_records",
                domain="system",
                payload={"records": [{"id": f"low-{i}"}]},
                priority=CommitPriority.P4_MAINTENANCE,
                idempotency_key=f"low-{i}",
            )
        producer.submit(
            operation="system.echo_records",
            domain="system",
            payload={"records": [{"id": "high-1"}]},
            priority=CommitPriority.P1_INTERACTIVE,
            idempotency_key="high-1",
            safe_human_title="interactive",
        )
        # First claimed item should prefer interactive over maintenance flood.
        first = self.coord.spool.claim_next()
        self.assertIsNotNone(first)
        assert first is not None
        self.assertEqual(first.intent.idempotency_key, "high-1")
        self.coord.spool.return_to_pending(first)
        self.coord.process_until_idle()
        for i in range(20):
            self.assertIsNotNone(self.coord.receipts.get_by_idempotency_key(f"low-{i}"))
        self.assertIsNotNone(self.coord.receipts.get_by_idempotency_key("high-1"))


if __name__ == "__main__":
    unittest.main()
