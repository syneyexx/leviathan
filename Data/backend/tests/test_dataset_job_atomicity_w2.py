"""Wave 2 — domain/kernel job atomicity and cancellation reconciliation."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest import mock

from Data.modules.common.corpus import CorpusLayout
from Data.modules.datasets.jobs import enqueue_kernel_for_domain_job, kernel_idempotency_key
from Data.modules.datasets.service import DatasetService
from Data.modules.datasets.store import DatasetStore
from Data.modules.datasets.types import DatasetError, DatasetJobStatus, DatasetJobType
from Data.modules.execution import build_default_catalog
from Data.modules.execution.gateway import ExecutionGateway
from Data.modules.jobs.resources import ResourceManager
from Data.modules.jobs.runtime import JobRuntime
from Data.modules.jobs.states import JobState
from Data.modules.jobs.store import JobStore


def _layout(root: Path) -> CorpusLayout:
    layout = CorpusLayout(
        root=root,
        datasets=root / "datasets",
        datasets_raw=root / "datasets" / "raw",
        datasets_materialized=root / "datasets" / "materialized",
        datasets_processed=root / "datasets" / "processed",
        datasets_exports=root / "datasets" / "exports",
        datasets_manifests=root / "datasets" / "manifests",
        training=root / "training",
        training_jobs=root / "training" / "jobs",
        training_runs=root / "training" / "runs",
        training_checkpoints=root / "training" / "checkpoints",
        training_adapters=root / "training" / "adapters",
        training_exports=root / "training" / "exports",
        training_logs=root / "training" / "logs",
        research=root / "research",
        research_projects=root / "research" / "projects",
        research_sources=root / "research" / "sources",
        research_snapshots=root / "research" / "snapshots",
        research_reports=root / "research" / "reports",
        research_exports=root / "research" / "exports",
        models_artifacts=root / "models" / "artifacts",
        models_cache=root / "models" / "cache",
        hf_cache=root / "hf_cache",
    )
    return layout.ensure()


def _settings(root: Path):
    class _RI:
        datasets_auto_index_ready_to_knowledge = False
        dataset_jobs_runner = "external"
        dataset_index_batch_size = 10
        dataset_max_relations_per_doc = 8
        dataset_extract_relations = False

    class _K:
        data_root = str(root / "knowledge")
        embedding_provider = "hash"
        hash_dimensions = 16
        embedding_model = "hash"

    class _S:
        knowledge = _K()
        research_integration = _RI()

    Path(_K.data_root).mkdir(parents=True, exist_ok=True)
    return _S()


class DomainKernelAtomicityTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.db = root / "lev.db"
        self.store = DatasetStore(self.db)
        self.store.initialize()
        self.job_store = JobStore(self.db)
        self.job_store.initialize()
        self.jobs = JobRuntime(
            self.job_store,
            ExecutionGateway(catalog=build_default_catalog()),
            ResourceManager(2),
        )
        self.corpus = _layout(root / "corpus")
        self.service = DatasetService(
            self.store,
            corpus=self.corpus,
            knowledge=None,
            settings=_settings(root),  # type: ignore[arg-type]
            allowed_import_roots=[self.corpus.root],
            job_runtime=self.jobs,
        )

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_enqueue_throw_fails_domain_not_orphan_queued(self) -> None:
        with mock.patch.object(self.jobs, "enqueue", side_effect=RuntimeError("db locked")):
            with self.assertRaises(DatasetError) as ctx:
                self.service._queue_domain_job(
                    job_type=DatasetJobType.VALIDATE,
                    dataset_id=None,
                    config={},
                )
        self.assertEqual(ctx.exception.code, "DATASET_EXECUTION_UNAVAILABLE")
        jobs = self.store.list_jobs(limit=20)
        self.assertEqual(len(jobs), 1)
        self.assertEqual(jobs[0].status, DatasetJobStatus.FAILED)
        self.assertIn("DATASET_EXECUTION_UNAVAILABLE", jobs[0].error or "")
        # No runnable kernel for a FAILED accept
        kernel = self.job_store.get_by_idempotency_key(
            kernel_idempotency_key(jobs[0].job_id)
        )
        self.assertIsNone(kernel)

    def test_job_runtime_none_still_allows_domain_only(self) -> None:
        legacy = DatasetService(
            self.store,
            corpus=self.corpus,
            knowledge=None,
            settings=_settings(Path(self.tmp.name)),  # type: ignore[arg-type]
            allowed_import_roots=[self.corpus.root],
            job_runtime=None,
        )
        domain = legacy._queue_domain_job(
            job_type=DatasetJobType.VALIDATE,
            dataset_id=None,
            config={},
        )
        self.assertEqual(domain.status, DatasetJobStatus.QUEUED)

    def test_duplicate_enqueue_reuses_kernel(self) -> None:
        domain = self.service._queue_domain_job(
            job_type=DatasetJobType.VALIDATE,
            dataset_id=None,
            config={},
        )
        first = self.job_store.get_by_idempotency_key(kernel_idempotency_key(domain.job_id))
        assert first is not None
        reused = enqueue_kernel_for_domain_job(self.jobs, domain, raise_on_error=True)
        assert reused is not None
        self.assertEqual(reused.job_id, first.job_id)

    def test_orphan_reconcile_relinks_or_fails(self) -> None:
        # Simulate legacy orphan: domain QUEUED without kernel
        orphan = self.store.create_job(
            job_type=DatasetJobType.VALIDATE,
            dataset_id=None,
            config={"orphan": True},
        )
        self.assertEqual(orphan.status, DatasetJobStatus.QUEUED)
        self.assertIsNone(
            self.job_store.get_by_idempotency_key(kernel_idempotency_key(orphan.job_id))
        )
        recovered = self.service.reconcile_orphan_queued_jobs()
        self.assertTrue(recovered)
        kernel = self.job_store.get_by_idempotency_key(
            kernel_idempotency_key(orphan.job_id)
        )
        self.assertIsNotNone(kernel)
        self.assertEqual(kernel.state, JobState.QUEUED)

    def test_orphan_reconcile_fails_when_enqueue_broken(self) -> None:
        orphan = self.store.create_job(
            job_type=DatasetJobType.VALIDATE,
            dataset_id=None,
            config={},
        )
        with mock.patch.object(self.jobs, "enqueue", side_effect=RuntimeError("boom")):
            recovered = self.service.reconcile_orphan_queued_jobs()
        self.assertEqual(len(recovered), 1)
        self.assertEqual(recovered[0].status, DatasetJobStatus.FAILED)

    def test_kernel_cancel_requested_reconciles_domain(self) -> None:
        domain = self.service._queue_domain_job(
            job_type=DatasetJobType.VALIDATE,
            dataset_id=None,
            config={},
        )
        kernel = self.job_store.get_by_idempotency_key(kernel_idempotency_key(domain.job_id))
        assert kernel is not None
        # QUEUED kernel cancel → CANCELLED immediately (not CANCEL_REQUESTED).
        self.jobs.cancel(kernel.job_id, reason="test")
        kernel2 = self.job_store.get(kernel.job_id)
        assert kernel2 is not None
        self.assertEqual(kernel2.state, JobState.CANCELLED)
        # process_next cannot claim a CANCELLED kernel; reconcile closes split-brain.
        self.service.reconcile_orphan_queued_jobs()
        refreshed = self.store.get_job(domain.job_id)
        assert refreshed is not None
        self.assertEqual(refreshed.status, DatasetJobStatus.CANCELLED)

    def test_domain_cancel_cancels_kernel(self) -> None:
        domain = self.service._queue_domain_job(
            job_type=DatasetJobType.VALIDATE,
            dataset_id=None,
            config={},
        )
        cancelled = self.service.cancel_job(domain.job_id)
        self.assertEqual(cancelled.status, DatasetJobStatus.CANCELLED)
        kernel = self.job_store.get_by_idempotency_key(kernel_idempotency_key(domain.job_id))
        assert kernel is not None
        self.assertEqual(kernel.state, JobState.CANCELLED)


if __name__ == "__main__":
    unittest.main()
