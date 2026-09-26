"""W167–W170 — ResourceAdmission, cancel, soft memory watchdog, orphan reconcile."""

from __future__ import annotations

import os
import stat
import subprocess
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

from Data.modules.common.corpus import CorpusLayout
from Data.modules.datasets.jobs import (
    MEMORY_HEAVY_JOB_TYPES,
    enqueue_kernel_for_domain_job,
)
from Data.modules.datasets.memory_policy import (
    DEFAULT_MEMORY_BUDGET_BYTES,
    MemoryEnforcement,
    resolve_dataset_memory_policy,
)
from Data.modules.datasets.publish import prepare_output_path, reconcile_orphans
from Data.modules.datasets.service import DatasetService
from Data.modules.datasets.store import DatasetStore
from Data.modules.datasets.types import DatasetJobStatus, DatasetJobType
from Data.modules.execution import build_default_catalog
from Data.modules.execution.gateway import ExecutionGateway
from Data.modules.jobs.resources import ResourceManager
from Data.modules.jobs.runtime import JobRuntime
from Data.modules.jobs.store import JobStore
from Data.modules.workers.native_compute import (
    MEMORY_ENFORCEMENT_SOFT,
    NativeComputeRunner,
    build_task_document,
    run_native_task,
)


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


def _sleep_binary(tmp: Path) -> Path:
    """Executable that sleeps long enough for cancel/RSS tests."""
    path = tmp / "fake-native-sleep"
    path.write_text(
        "#!/usr/bin/env python3\n"
        "import time, sys\n"
        "time.sleep(30)\n"
        "sys.exit(0)\n",
        encoding="utf-8",
    )
    path.chmod(path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    return path


class TestW167ResourceAdmission(unittest.TestCase):
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

    def test_heavy_ops_enqueue_memory_heavy_with_reserved_ram(self) -> None:
        policy = resolve_dataset_memory_policy()
        for job_type in (
            DatasetJobType.VALIDATE,
            DatasetJobType.DEDUPE,
            DatasetJobType.TRANSFORM,
            DatasetJobType.MATERIALIZE,
        ):
            with self.subTest(job_type=job_type.value):
                domain = self.service._queue_domain_job(
                    job_type=job_type,
                    dataset_id=None,
                    version_id=None,
                    config={},
                )
                kernel = enqueue_kernel_for_domain_job(self.jobs, domain)
                # Idempotent reuse of the kernel row created by _queue_domain_job
                assert kernel is not None
                refreshed = self.job_store.get(kernel.job_id)
                assert refreshed is not None
                self.assertEqual(refreshed.resource_class, "MEMORY_HEAVY")
                self.assertEqual(
                    int(refreshed.resource_request.get("reservedRamBytes") or 0),
                    int(policy.memory_budget_bytes),
                )
                self.assertEqual(
                    (refreshed.metadata.get("requested") or {}).get("reservedRamBytes"),
                    policy.memory_budget_bytes,
                )

        self.assertIn("validate", MEMORY_HEAVY_JOB_TYPES)
        self.assertGreaterEqual(policy.memory_budget_bytes, DEFAULT_MEMORY_BUDGET_BYTES)
        self.assertEqual(policy.enforcement, MemoryEnforcement.SOFT_ENFORCED)

    def test_import_stays_io_heavy(self) -> None:
        domain = self.service._queue_domain_job(
            job_type=DatasetJobType.IMPORT_LOCAL,
            dataset_id=None,
            config={"path": "/tmp/x"},
        )
        kernel = self.job_store.get_by_idempotency_key(
            f"dataset:process:{domain.job_id}"
        )
        assert kernel is not None
        self.assertEqual(kernel.resource_class, "IO_HEAVY")
        self.assertFalse(kernel.resource_request.get("reservedRamBytes"))


class TestW169CancelWiring(unittest.TestCase):
    def test_cancel_event_terminates_child(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            binary = _sleep_binary(root)
            cancel = threading.Event()
            task = build_task_document(
                task_id="cancel-1",
                operation="dataset.hash",
                input_path=root / "in.jsonl",
                temporary_path=root / "out.tmp",
                limits={"memoryBytes": 64 * 1024 * 1024},
            )
            (root / "in.jsonl").write_text('{"id":"1","text":"a"}\n', encoding="utf-8")

            result_box: list = []

            def _run() -> None:
                result_box.append(
                    run_native_task(
                        task,
                        binary=binary,
                        timeout_seconds=20,
                        cancel_event=cancel,
                    )
                )

            t = threading.Thread(target=_run, daemon=True)
            t.start()
            time.sleep(0.2)
            cancel.set()
            t.join(timeout=10)
            self.assertTrue(t.is_alive() is False)
            self.assertEqual(len(result_box), 1)
            result = result_box[0]
            self.assertFalse(result.ok)
            self.assertEqual(result.error_code, "NATIVE_CANCELLED")
            self.assertEqual(result.memory_enforcement, MEMORY_ENFORCEMENT_SOFT)

    def test_try_native_operation_wires_cancel_poll(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            db = root / "lev.db"
            store = DatasetStore(db)
            store.initialize()
            corpus = _layout(root / "corpus")
            service = DatasetService(
                store,
                corpus=corpus,
                knowledge=None,
                settings=_settings(root),  # type: ignore[arg-type]
                allowed_import_roots=[corpus.root],
            )
            inp = corpus.datasets_materialized / "d1" / "v1.jsonl"
            inp.parent.mkdir(parents=True, exist_ok=True)
            inp.write_text('{"id":"1","text":"hi"}\n', encoding="utf-8")
            dest = corpus.datasets_processed / "d1" / "out.jsonl"
            dest.parent.mkdir(parents=True, exist_ok=True)

            job = store.create_job(
                job_type=DatasetJobType.TRANSFORM,
                dataset_id="d1",
                version_id="v1",
                config={},
            )
            store.update_job(job.job_id, cancel_requested=True)

            cancel_seen = threading.Event()

            class _FakeRunner:
                available = True

                def capabilities(self):
                    return mock.Mock(detail="fake")

                def run(self, **kwargs):
                    cancel_event = kwargs.get("cancel_event")
                    if cancel_event is None:
                        raise AssertionError("cancel_event missing")
                    # Wait briefly for the poller thread to observe cancel_requested.
                    deadline = time.time() + 2.0
                    while time.time() < deadline:
                        if cancel_event.is_set():
                            cancel_seen.set()
                            from Data.modules.workers.native_compute import NativeRunResult

                            return NativeRunResult(
                                ok=False,
                                receipt=None,
                                status="error",
                                exit_code=-15,
                                stdout="",
                                stderr="",
                                duration_ms=1,
                                error_code="NATIVE_CANCELLED",
                                error_message="native task cancelled",
                                memory_enforcement=MEMORY_ENFORCEMENT_SOFT,
                            )
                        time.sleep(0.02)
                    raise AssertionError("cancel_event was never set by poller")

                def verify_output(self, *args, **kwargs):
                    return {"ok": False, "errorCode": "NATIVE_CANCELLED"}

            service._native_runner = _FakeRunner()  # type: ignore[attr-defined]
            with mock.patch.object(
                service,
                "_plan_compute_backend",
                return_value=mock.Mock(
                    backend=__import__(
                        "Data.modules.datasets.compute_planner", fromlist=["ComputeBackend"]
                    ).ComputeBackend.RUST_NATIVE,
                    native_mode="rust",
                    input_bytes=10,
                    rust_threshold_bytes=1,
                    native_status="AVAILABLE",
                    fallback_reason=None,
                    detail="",
                    public_dict=lambda: {},
                ),
            ):
                from Data.modules.datasets.types import DatasetError

                with self.assertRaises(DatasetError) as ctx:
                    service._try_native_operation(
                        job=job,
                        operation="dataset.transform",
                        input_path=inp,
                        dest=dest,
                        force_backend="rust",
                    )
                self.assertEqual(ctx.exception.code, "cancelled")
            self.assertTrue(cancel_seen.is_set())


class TestW168SoftMemoryWatchdog(unittest.TestCase):
    def test_memory_budget_kill_returns_exceeded(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            binary = _sleep_binary(root)
            task = build_task_document(
                task_id="mem-1",
                operation="dataset.hash",
                input_path=root / "in.jsonl",
                temporary_path=root / "out.tmp",
                limits={"memoryBytes": 1024},  # tiny budget
            )
            (root / "in.jsonl").write_text('{"id":"1","text":"a"}\n', encoding="utf-8")

            def fake_rss(_pid: int) -> int:
                return 10 * 1024 * 1024  # 10 MiB >> 1024 * 1.25

            result = run_native_task(
                task,
                binary=binary,
                timeout_seconds=15,
                rss_reader=fake_rss,
                memory_grace_factor=1.25,
            )
            self.assertFalse(result.ok)
            self.assertEqual(result.error_code, "NATIVE_MEMORY_BUDGET_EXCEEDED")
            self.assertEqual(result.memory_enforcement, MEMORY_ENFORCEMENT_SOFT)
            self.assertEqual(
                (result.receipt or {}).get("memoryEnforcement"),
                MEMORY_ENFORCEMENT_SOFT,
            )
            self.assertGreater(result.peak_rss_bytes or 0, 0)

    def test_runner_run_forwards_rss_reader(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            binary = _sleep_binary(root)
            (root / "in.jsonl").write_text("{}\n", encoding="utf-8")
            runner = NativeComputeRunner(binary=binary, timeout_seconds=15)
            called = {"n": 0}

            def fake_rss(_pid: int) -> int:
                called["n"] += 1
                return 50 * 1024 * 1024

            result = runner.run(
                task_id="mem-2",
                operation="dataset.validate",
                input_path=root / "in.jsonl",
                temporary_path=root / "out.tmp",
                limits={"memoryBytes": 2048},
                rss_reader=fake_rss,
            )
            self.assertEqual(result.error_code, "NATIVE_MEMORY_BUDGET_EXCEEDED")
            self.assertGreaterEqual(called["n"], 1)
            self.assertEqual(result.memory_enforcement, MEMORY_ENFORCEMENT_SOFT)


class TestW170OrphanReconcile(unittest.TestCase):
    def test_orphan_prepared_tmp_cleaned_grace_zero(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            processed = root / "processed"
            processed.mkdir(parents=True)
            dest = processed / "shard.jsonl"
            orphan = prepare_output_path(dest)
            orphan.write_text("orphan\n", encoding="utf-8")
            self.assertTrue(orphan.is_file())
            # Age the file so mtime is in the past even with grace=0 edge cases.
            past = time.time() - 10
            os.utime(orphan, (past, past))

            report = reconcile_orphans(
                [processed],
                referenced_paths=set(),
                grace_seconds=0,
            )
            self.assertFalse(orphan.exists())
            self.assertTrue(any(o.get("action") == "deleted_tmp" for o in report["orphans"]))

    def test_service_reconcile_invokes_orphan_sweep(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            db = root / "lev.db"
            store = DatasetStore(db)
            store.initialize()
            corpus = _layout(root / "corpus")
            service = DatasetService(
                store,
                corpus=corpus,
                knowledge=None,
                settings=_settings(root),  # type: ignore[arg-type]
                allowed_import_roots=[corpus.root],
            )
            dest = corpus.datasets_processed / "ds" / "out.jsonl"
            dest.parent.mkdir(parents=True, exist_ok=True)
            orphan = prepare_output_path(dest)
            orphan.write_text("x\n", encoding="utf-8")
            past = time.time() - 5
            os.utime(orphan, (past, past))

            with mock.patch.dict(
                os.environ, {"LEVIATHAN_DATASET_ORPHAN_GRACE_SECONDS": "0"}
            ):
                service.reconcile()
            self.assertFalse(orphan.exists())


if __name__ == "__main__":
    unittest.main()
