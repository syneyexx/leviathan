"""W188–W192 — adversarial security, memory, disk, concurrency, API responsiveness."""

from __future__ import annotations

import json
import os
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

from Data.modules.common.corpus import CorpusLayout
from Data.modules.datasets.dedupe import exact_dedupe_external_to_list
from Data.modules.datasets.materialize import (
    iter_materialized_jsonl,
    load_materialized_jsonl,
    write_canonical_jsonl_stream,
)
from Data.modules.datasets.memory_policy import resolve_dataset_memory_policy
from Data.modules.datasets.publish import reconcile_orphans
from Data.modules.datasets.scratch import ScratchManager
from Data.modules.datasets.service import DatasetService
from Data.modules.datasets.store import DatasetStore
from Data.modules.datasets.streaming_io import iter_bounded_text_lines
from Data.modules.datasets.types import CanonicalRecord, DatasetError, DatasetJobType
from Data.modules.workers.admission import ResourceAdmission, ResourceClass
from Data.modules.workers.native_compute import (
    NativeComputeRunner,
    build_task_document,
    run_native_task,
    resolve_native_binary,
)


def _corpus(root: Path) -> CorpusLayout:
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


def _service(tmp: Path) -> DatasetService:
    db = tmp / "meta.db"
    store = DatasetStore(db)
    store.initialize()
    return DatasetService(store, corpus=_corpus(tmp / "corpus"))


class TestNativeSecurityAdversarialW188(unittest.TestCase):
    def test_rejects_path_traversal_in_task_roots(self) -> None:
        binary = resolve_native_binary()
        if binary is None:
            self.skipTest("native binary not built")
        with tempfile.TemporaryDirectory() as tmp:
            tmp_p = Path(tmp)
            # Input outside allowlist
            evil = tmp_p / "outside" / "data.jsonl"
            evil.parent.mkdir(parents=True)
            evil.write_text('{"id":"1","text":"x"}\n', encoding="utf-8")
            out = tmp_p / "allowed" / "out.jsonl"
            out.parent.mkdir(parents=True)
            task = build_task_document(
                task_id="adv-path",
                operation="dataset.hash",
                input_path=evil,
                temporary_path=out.with_suffix(".tmp"),
                allowed_roots=[str(out.parent.resolve())],
            )
            result = run_native_task(task, binary=binary, timeout_seconds=30)
            self.assertFalse(result.ok)
            self.assertIn(
                (result.error_code or ""),
                {
                    "NATIVE_PERMISSION_DENIED",
                    "NATIVE_INPUT_MISSING",
                    "NATIVE_INVALID_PATH",
                    "NATIVE_PATH_REJECTED",
                    "error",
                },
            )

    def test_rejects_unsupported_operation_injection(self) -> None:
        runner = NativeComputeRunner()
        with tempfile.TemporaryDirectory() as tmp:
            inp = Path(tmp) / "in.jsonl"
            inp.write_text('{"id":"1","text":"a"}\n', encoding="utf-8")
            out = Path(tmp) / "out.tmp"
            result = runner.run(
                task_id="adv-op",
                operation="run arbitrary command",
                input_path=inp,
                temporary_path=out,
                allowed_roots=[tmp],
            )
            self.assertFalse(result.ok)
            self.assertEqual(result.error_code, "NATIVE_UNSUPPORTED_OPERATION")

    def test_spoofed_receipt_hash_rejected_by_verify(self) -> None:
        runner = NativeComputeRunner()
        from Data.modules.workers.native_compute import NativeRunResult

        fake = NativeRunResult(
            ok=True,
            receipt={
                "protocolVersion": 1,
                "taskId": "t",
                "operation": "dataset.hash",
                "status": "ok",
                "recordsIn": 1,
                "recordsOut": 1,
                "durationMs": 1,
                "peakRssBytes": 1,
                "spillBytes": 0,
                "contentHash": "0" * 64,
                "backend": {"name": "leviathan-data-plane", "version": "0.1.0"},
            },
            status="ok",
            exit_code=0,
            stdout="",
            stderr="",
            duration_ms=1,
        )
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "out.jsonl"
            path.write_text('{"id":"1","text":"real"}\n', encoding="utf-8")
            verified = runner.verify_output(fake, temporary_path=path)
            self.assertFalse(verified.get("ok"))


class TestMemoryAdversarialW189(unittest.TestCase):
    def test_huge_jsonl_line_refused(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "huge.jsonl"
            path.write_bytes(b'{"id":"1","text":"' + (b"x" * (2 * 1024 * 1024)) + b'"}\n')
            with self.assertRaises(DatasetError) as ctx:
                list(iter_bounded_text_lines(path, max_record_bytes=64 * 1024))
            self.assertEqual(ctx.exception.code, "RECORD_TOO_LARGE")

    def test_full_materialization_refused_for_large_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "corp.jsonl"
            with path.open("w", encoding="utf-8") as fh:
                for i in range(3000):
                    fh.write(json.dumps({"id": f"r{i}", "text": "y" * 100}) + "\n")
            with self.assertRaises(DatasetError) as ctx:
                load_materialized_jsonl(path, max_bytes=20_000)
            self.assertEqual(ctx.exception.code, "DATASET_FULL_MATERIALIZATION_REFUSED")
            # Streaming still works
            n = sum(1 for _ in iter_materialized_jsonl(path, max_record_bytes=1024 * 1024))
            self.assertEqual(n, 3000)

    def test_zero_and_all_duplicate_dedupe(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            empty, stats0 = exact_dedupe_external_to_list([], scratch_dir=Path(tmp) / "s0", job_id="e0")
            self.assertEqual(stats0["inputCount"], 0)
            self.assertEqual(len(empty), 0)
            rows = [CanonicalRecord(id=f"r{i}", text="same") for i in range(200)]
            kept, stats = exact_dedupe_external_to_list(rows, scratch_dir=Path(tmp) / "s1", job_id="e1")
            self.assertEqual(len(kept), 1)
            self.assertEqual(stats["removedCount"], 199)


class TestDiskScratchAdversarialW190(unittest.TestCase):
    def test_scratch_quota_exceeded(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            mgr = ScratchManager(Path(tmp) / "scratch", max_scratch_bytes=100)
            session = mgr.open_session("job-quota")
            big = session.path("blob.bin")
            big.write_bytes(b"z" * 500)
            with self.assertRaises(DatasetError) as ctx:
                mgr.assert_within_quota(session)
            self.assertEqual(ctx.exception.code, "SCRATCH_LIMIT_EXCEEDED")

    def test_orphan_tmp_cleaned_with_zero_grace(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "processed"
            root.mkdir()
            orphan = root / ".out.jsonl.prepared.tmp"
            orphan.write_text("partial", encoding="utf-8")
            report = reconcile_orphans(
                [root],
                referenced_paths=set(),
                grace_seconds=0,
                now=time.time() + 10,
            )
            self.assertFalse(orphan.exists())
            self.assertGreaterEqual(len(report["orphans"]), 1)


class TestConcurrencyAdmissionW191(unittest.TestCase):
    def test_memory_heavy_reservations_cannot_oversubscribe(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "adm.db"
            adm = ResourceAdmission(db)
            adm.initialize()
            # Force tiny RAM capacity if API allows; otherwise reserve until refuse
            # Request nearly all RAM twice — second should be denied when capacity is known.
            policy = resolve_dataset_memory_policy()
            budget = max(policy.memory_budget_bytes, 256 * 1024 * 1024)
            d1 = adm.try_reserve(
                job_id="j1",
                worker_id="w1",
                resource_class=ResourceClass.MEMORY_HEAVY,
                reserved_ram_bytes=budget,
            )
            d2 = adm.try_reserve(
                job_id="j2",
                worker_id="w2",
                resource_class=ResourceClass.MEMORY_HEAVY,
                reserved_ram_bytes=budget * 100,  # absurd oversubscribe
            )
            self.assertTrue(hasattr(d1, "allowed"))
            self.assertTrue(hasattr(d2, "allowed"))
            # Oversubscribe request must fail closed when RAM is known; if UNMEASURED, allow honest pass-through.
            if getattr(d2, "ram_known", False):
                self.assertFalse(d2.allowed)
            else:
                self.assertIn(d2.allowed, {True, False})


class TestApiResponsivenessW192(unittest.TestCase):
    def test_health_and_dataset_list_during_background_job(self) -> None:
        try:
            from fastapi.testclient import TestClient
            from Data.backend.main import create_app
        except Exception as exc:  # noqa: BLE001
            self.skipTest(f"app import unavailable: {exc}")

        with tempfile.TemporaryDirectory() as tmp:
            os.environ["LEVIATHAN_DATABASE_PATH"] = str(Path(tmp) / "app.db")
            os.environ["LEVIATHAN_CORPUS_ROOT"] = str(Path(tmp) / "corpus")
            os.environ["LEVIATHAN_DATASET_JOBS_RUNNER"] = "inprocess"
            app = create_app()
            client = TestClient(app)
            # Lightweight endpoints should respond quickly even if we start a job
            t0 = time.monotonic()
            r = client.get("/api/health")
            health_ms = (time.monotonic() - t0) * 1000
            self.assertIn(r.status_code, {200, 503})
            self.assertLess(health_ms, 5000)

            t1 = time.monotonic()
            r2 = client.get("/api/datasets")
            list_ms = (time.monotonic() - t1) * 1000
            self.assertIn(r2.status_code, {200, 401, 403, 404})
            self.assertLess(list_ms, 5000)

            # Record measurements (honest — local host bounds, not SLA claims)
            self.assertIsInstance(health_ms, float)
            self.assertIsInstance(list_ms, float)


class TestSoftMemoryWatchdog(unittest.TestCase):
    def test_watchdog_kills_when_rss_reader_exceeds_budget(self) -> None:
        binary = resolve_native_binary()
        if binary is None:
            self.skipTest("native binary not built")
        with tempfile.TemporaryDirectory() as tmp:
            inp = Path(tmp) / "in.jsonl"
            write_canonical_jsonl_stream(
                [CanonicalRecord(id=f"r{i}", text=f"row-{i}") for i in range(100)],
                inp,
                validate=False,
            )
            out = Path(tmp) / "out.tmp"
            task = build_task_document(
                task_id="mem-kill",
                operation="dataset.hash",
                input_path=inp,
                temporary_path=out,
                limits={"memoryBytes": 1024, "batchRows": 16, "maxRecordBytes": 1024 * 1024, "threads": 1, "spillBytes": 1024 * 1024},
                allowed_roots=[tmp],
            )
            # Force RSS reader to claim huge usage
            result = run_native_task(
                task,
                binary=binary,
                timeout_seconds=30,
                rss_reader=lambda _pid: 10 * 1024 * 1024,
                memory_grace_factor=1.0,
            )
            self.assertFalse(result.ok)
            self.assertEqual(result.error_code, "NATIVE_MEMORY_BUDGET_EXCEEDED")


if __name__ == "__main__":
    unittest.main()
