"""Evaluation worker: durable suite execution; UNMEASURED ≠ PASS."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest import mock

from Data.modules.execution import ExecutionGateway, build_default_catalog
from Data.modules.jobs import JobRuntime, JobState, JobStore, ResourceManager
from Data.modules.workers.entrypoints.evaluation import _handler, execute_evaluation_run
from Data.modules.workers.pools import pool_for_capability


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

    def _settings(self, *, eval_platform: bool = True) -> mock.Mock:
        return mock.Mock(
            database_path=self.db,
            features=mock.Mock(
                eval_platform=eval_platform,
                neuro_cortex=False,
                neuro_memory_tiers=False,
                neuro_process_critic=False,
                model_serving=False,
                residual_production=False,
            ),
            neuro_runtime=mock.Mock(
                residual_kind="unsupported",
                residual_model_id=None,
                residual_device="cpu",
                residual_load_weights=False,
                residual_hook_layers=None,
                residual_server_url=None,
            ),
        )

    def test_pool_maps_evaluation_run(self) -> None:
        self.assertEqual(pool_for_capability("evaluation.run"), "evaluation")

    def test_unknown_suite_is_unmeasured_not_pass(self) -> None:
        job = self.runtime.enqueue(
            capability_id="evaluation.run",
            arguments={"suite_id": "no_such_suite_xyz"},
            worker_pool="evaluation",
        )
        claimed = self.store.claim_next_queued(
            worker_id="eval-test",
            capability_ids={"evaluation.run"},
        )
        assert claimed is not None
        self.assertEqual(claimed.job_id, job.job_id)
        ctx = {
            "settings": self._settings(eval_platform=False),
            "job_store": self.store,
            "job_runtime": self.runtime,
        }
        result = _handler(ctx, claimed)
        self.assertEqual(result.get("measurement"), "UNMEASURED")
        final = self.store.get(claimed.job_id)
        assert final is not None
        self.assertEqual(final.state, JobState.COMPLETED)
        self.assertEqual((final.result or {}).get("measurement"), "UNMEASURED")
        self.assertNotEqual((final.result or {}).get("measurement"), "PASS")

    def test_foundation_keeps_unmeasured_cases(self) -> None:
        payload = execute_evaluation_run(
            self._settings(eval_platform=True),
            suite_id="foundation",
            persist=True,
        )
        self.assertEqual(payload.get("suite_id"), "foundation")
        self.assertEqual(payload.get("measurement"), "UNMEASURED")
        report = payload.get("report") or {}
        summary = report.get("summary") or {}
        self.assertGreaterEqual(int(summary.get("unmeasured") or 0), 1)
        # Embedding quality must remain UNMEASURED, never upgraded to PASS.
        results = report.get("results") or []
        embedding = next(r for r in results if r.get("case_id") == "embedding-quality")
        self.assertEqual(embedding.get("outcome"), "UNMEASURED")


if __name__ == "__main__":
    unittest.main()
