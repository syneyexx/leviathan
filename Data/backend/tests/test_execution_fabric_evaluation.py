"""Evaluation worker: durable suite execution; UNMEASURED ≠ PASS."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest import mock

from Data.modules.execution import ExecutionGateway, build_default_catalog
from Data.modules.jobs import JobRuntime, JobState, JobStore, ResourceManager
from Data.modules.workers.entrypoints.evaluation import _handler


class EvaluationWorkerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.db = Path(self.tmp.name) / "e.db"
        self.store = JobStore(self.db)
        self.store.initialize()
        self.runtime = JobRuntime(
            self.store,
            ExecutionGateway(catalog=build_default_catalog()),
            ResourceManager(1),
        )

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_unknown_suite_is_unmeasured_not_pass(self) -> None:
        job = self.runtime.enqueue(
            capability_id="evaluation.run",
            arguments={"suite_id": "no_such_suite_xyz"},
            worker_pool="evaluation",
        )
        # claim so state is RUNNING for handler
        claimed = self.store.claim_next_queued(
            worker_id="eval-test",
            capability_ids={"evaluation.run"},
        )
        assert claimed is not None
        ctx = {
            "settings": mock.Mock(
                database_path=self.db,
                features=mock.Mock(
                    eval_platform=False,
                    neuro_cortex=False,
                    neuro_memory_tiers=False,
                    neuro_process_critic=False,
                ),
            ),
            "job_store": self.store,
            "job_runtime": self.runtime,
        }
        result = _handler(ctx, claimed)
        self.assertEqual(result.get("measurement"), "UNMEASURED")
        final = self.store.get(claimed.job_id)
        assert final is not None
        self.assertEqual(final.state, JobState.COMPLETED)
        self.assertEqual((final.result or {}).get("measurement"), "UNMEASURED")
        # Must not claim PASS
        self.assertNotEqual((final.result or {}).get("measurement"), "PASS")


if __name__ == "__main__":
    unittest.main()
