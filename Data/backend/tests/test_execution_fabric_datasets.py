"""Execution fabric — dataset domain ↔ Job Kernel linkage."""

from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from Data.modules.common.corpus import CorpusLayout
from Data.modules.datasets.jobs import enqueue_kernel_for_domain_job, kernel_idempotency_key
from Data.modules.datasets.service import DatasetService
from Data.modules.datasets.store import DatasetStore
from Data.modules.datasets.types import (
    CAPABILITY_PROCESS,
    DOMAIN_ENTITY_TYPE,
    WORKER_POOL,
    DatasetJobStatus,
    DatasetJobType,
)
from Data.modules.datasets.worker import resolve_runner_mode, should_start_inprocess_runner
from Data.modules.execution import build_default_catalog
from Data.modules.execution.gateway import ExecutionGateway
from Data.modules.jobs.resources import ResourceManager
from Data.modules.jobs.runtime import EXTERNAL_WORKER_CAPABILITIES, JobRuntime
from Data.modules.jobs.states import JobState
from Data.modules.jobs.store import JobStore
from Data.modules.workers.pools import POOL_CATALOG, pool_for_capability


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


def _settings(root: Path, *, runner: str = "external"):
    class _RI:
        datasets_auto_index_ready_to_knowledge = False
        dataset_jobs_runner = runner
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


class DatasetKernelLinkageTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.db = root / "lev.db"
        self.store = DatasetStore(self.db)
        self.store.initialize()
        self.job_store = JobStore(self.db)
        self.job_store.initialize()
        self.gateway = ExecutionGateway(catalog=build_default_catalog())
        self.jobs = JobRuntime(self.job_store, self.gateway, ResourceManager(2))
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

    def test_capability_registered_and_externalized(self) -> None:
        ids = {c.id for c in build_default_catalog().list()}
        self.assertIn(CAPABILITY_PROCESS, ids)
        self.assertIn(CAPABILITY_PROCESS, EXTERNAL_WORKER_CAPABILITIES)
        self.assertEqual(pool_for_capability(CAPABILITY_PROCESS), "dataset")
        self.assertIn(CAPABILITY_PROCESS, POOL_CATALOG["dataset"].job_kinds)

    def test_domain_enqueue_links_kernel_job(self) -> None:
        domain = self.service._queue_domain_job(
            job_type=DatasetJobType.VALIDATE,
            dataset_id=None,
            version_id=None,
            config={"probe": True},
        )
        self.assertEqual(domain.status, DatasetJobStatus.QUEUED)

        kernel = self.job_store.get_by_idempotency_key(kernel_idempotency_key(domain.job_id))
        assert kernel is not None
        self.assertEqual(kernel.capability_id, CAPABILITY_PROCESS)
        self.assertEqual(kernel.worker_pool, WORKER_POOL)
        self.assertEqual(kernel.domain_entity_type, DOMAIN_ENTITY_TYPE)
        self.assertEqual(kernel.domain_entity_id, domain.job_id)
        self.assertEqual(kernel.state, JobState.QUEUED)
        self.assertEqual(kernel.arguments.get("dataset_job_id"), domain.job_id)

        reused = enqueue_kernel_for_domain_job(self.jobs, domain)
        assert reused is not None
        self.assertEqual(reused.job_id, kernel.job_id)

    def test_job_runtime_does_not_steal_dataset_process(self) -> None:
        domain = self.service._queue_domain_job(
            job_type=DatasetJobType.VALIDATE,
            dataset_id=None,
            config={},
        )
        stolen = self.jobs.process_next()
        if stolen is not None:
            self.assertNotEqual(stolen.capability_id, CAPABILITY_PROCESS)
        still = self.job_store.get_by_idempotency_key(kernel_idempotency_key(domain.job_id))
        assert still is not None
        self.assertEqual(still.state, JobState.QUEUED)


class DatasetExternalNoDoubleClaimTests(unittest.TestCase):
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
        self.claim_events: list[str] = []
        self.service = DatasetService(
            self.store,
            corpus=self.corpus,
            knowledge=None,
            settings=_settings(root),  # type: ignore[arg-type]
            allowed_import_roots=[self.corpus.root],
            job_runtime=self.jobs,
        )

        def _probe_handler(job):
            self.claim_events.append(job.job_id)
            return {"ok": True}

        self.service.runner.handlers[DatasetJobType.VALIDATE.value] = _probe_handler

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_external_mode_kernel_claim_not_domain_claim_next(self) -> None:
        with mock.patch.dict(os.environ, {"LEVIATHAN_DATASET_JOBS_RUNNER": "external"}):
            self.assertEqual(resolve_runner_mode(), "external")
            self.assertFalse(should_start_inprocess_runner())

        domain = self.service._queue_domain_job(
            job_type=DatasetJobType.VALIDATE,
            dataset_id=None,
            config={},
        )
        self.assertEqual(domain.status, DatasetJobStatus.QUEUED)
        queued_domain = self.store.list_jobs(status=DatasetJobStatus.QUEUED, limit=10)
        self.assertEqual(len(queued_domain), 1)

        with mock.patch.object(
            self.store,
            "claim_next_queued",
            wraps=self.store.claim_next_queued,
        ) as domain_claim:
            done = self.service.runner.process_next()
            assert done is not None
            self.assertEqual(done.job_id, domain.job_id)
            self.assertEqual(done.status, DatasetJobStatus.COMPLETED)
            domain_claim.assert_not_called()

        self.assertEqual(self.claim_events, [domain.job_id])

        kernel = self.job_store.get_by_idempotency_key(kernel_idempotency_key(domain.job_id))
        assert kernel is not None
        self.assertEqual(kernel.state, JobState.COMPLETED)

        again = self.service.runner.process_next()
        self.assertIsNone(again)
        self.assertEqual(self.claim_events, [domain.job_id])

    def test_legacy_domain_claim_when_no_job_runtime(self) -> None:
        legacy = DatasetService(
            self.store,
            corpus=self.corpus,
            knowledge=None,
            settings=self.service.settings,
            allowed_import_roots=[self.corpus.root],
            job_runtime=None,
        )

        def _probe(job):
            return {"legacy": True}

        legacy.runner.handlers[DatasetJobType.VALIDATE.value] = _probe
        domain = legacy.store.create_job(
            job_type=DatasetJobType.VALIDATE,
            dataset_id=None,
            config={},
        )
        done = legacy.runner.process_next()
        assert done is not None
        self.assertEqual(done.status, DatasetJobStatus.COMPLETED)
        self.assertTrue((done.result or {}).get("legacy"))


if __name__ == "__main__":
    unittest.main()
