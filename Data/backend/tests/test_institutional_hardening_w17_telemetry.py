"""Wave 17 — durable autonomous action telemetry receipts."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from Data.modules.jobs.states import JobState
from Data.modules.jobs.store import JobStore
from Data.modules.observability import ObservabilityHub
from Data.modules.observability.action_receipts import (
    REQUIRED_RECEIPT_FIELDS,
    emit_action_receipt,
    receipt_from_job,
)


class ActionTelemetryReceiptTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.hub = ObservabilityHub(db_path=root / "obs.db", capacity=50)
        self.jobs = JobStore(root / "jobs.db")
        self.jobs.initialize()

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_receipt_fields_from_job(self) -> None:
        job = self.jobs.create(
            capability_id="market_sim.autonomous_step",
            arguments={"symbol": "BTCUSDT"},
            trace_id="trace-17",
            domain="market_sim",
            domain_entity_type="paper_deployment",
            domain_entity_id="dep-1",
            worker_pool="market_sim",
            resource_class="CPU_LIGHT",
            root_job_id="root-17",
        )
        job = self.jobs.transition(job.job_id, JobState.QUEUED)
        # Simulate claim/start/finish timestamps for latency.
        with self.jobs.connect() as conn:
            conn.execute(
                """
                UPDATE jobs
                SET queued_at = ?, claimed_at = ?, started_at = ?, finished_at = ?,
                    state = ?, artifact_refs_json = ?
                WHERE job_id = ?
                """,
                (
                    "2026-01-01T00:00:00+00:00",
                    "2026-01-01T00:00:05+00:00",
                    "2026-01-01T00:00:05+00:00",
                    "2026-01-01T00:00:15+00:00",
                    JobState.COMPLETED.value,
                    '["artifact://paper/1"]',
                    job.job_id,
                ),
            )
        job = self.jobs.get(job.job_id)
        assert job is not None
        receipt = receipt_from_job(job)
        payload = receipt.public_dict()
        for key in REQUIRED_RECEIPT_FIELDS:
            self.assertIn(key, payload)
        self.assertEqual(payload["trace_id"], "trace-17")
        self.assertEqual(payload["root_job_id"], "root-17")
        self.assertEqual(payload["domain_entity_type"], "paper_deployment")
        self.assertEqual(payload["worker_pool"], "market_sim")
        self.assertEqual(payload["resource_class"], "CPU_LIGHT")
        self.assertEqual(payload["queue_latency_ms"], 5000.0)
        self.assertEqual(payload["runtime_ms"], 10000.0)
        self.assertEqual(payload["result_state"], "COMPLETED")
        self.assertIn("artifact://paper/1", payload["artifact_refs"])

    def test_emit_to_observability_hub(self) -> None:
        job = self.jobs.create(
            capability_id="market_sim.research.cycle",
            arguments={},
            trace_id="t2",
            worker_pool="market_sim",
            resource_class="CPU_HEAVY",
            domain_entity_type="research_run",
            domain_entity_id="run-1",
        )
        job = self.jobs.transition(job.job_id, JobState.QUEUED)
        # Force completed without lease for unit test via direct update.
        with self.jobs.connect() as conn:
            conn.execute(
                "UPDATE jobs SET state = ?, finished_at = ?, queued_at = ?, claimed_at = ?, started_at = ? WHERE job_id = ?",
                (
                    JobState.COMPLETED.value,
                    "2026-01-01T00:01:00+00:00",
                    "2026-01-01T00:00:00+00:00",
                    "2026-01-01T00:00:10+00:00",
                    "2026-01-01T00:00:10+00:00",
                    job.job_id,
                ),
            )
        job = self.jobs.get(job.job_id)
        assert job is not None
        payload = emit_action_receipt(self.hub, job, runtime_ms=123.0)
        self.assertEqual(payload["runtime_ms"], 123.0)
        events = self.hub.recent(limit=20, category="workers")
        names = [e.name for e in events]
        self.assertIn("autonomous_action_receipt", names)


if __name__ == "__main__":
    unittest.main()
