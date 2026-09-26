"""W171–W176 — streaming checkpoint, public compute honesty, native probe, DB telemetry."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path


def _layout(root: Path):
    from Data.modules.common.corpus import CorpusLayout

    return CorpusLayout(
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
    ).ensure()


class TestCheckpointW171(unittest.TestCase):
    def test_checkpoint_roundtrip_and_resume_fingerprint(self) -> None:
        from Data.modules.datasets.checkpoint import (
            UNMEASURED,
            build_checkpoint,
            can_resume,
            invalidate_checkpoint,
            load_checkpoint,
            resolve_resume_skip,
            save_checkpoint,
        )

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            ckpt = build_checkpoint(
                input_hash="abc",
                operation="dataset.validate",
                options={"strict": True},
                phase="streaming",
                records_processed=10,
                backend="python_streaming",
            )
            self.assertEqual(ckpt.peak_memory, UNMEASURED)
            path = save_checkpoint(root, ckpt)
            self.assertTrue(path.is_file())
            loaded = load_checkpoint(root)
            self.assertIsNotNone(loaded)
            assert loaded is not None
            self.assertEqual(loaded.records_processed, 10)
            self.assertEqual(loaded.fingerprint, ckpt.fingerprint)
            self.assertTrue(can_resume(loaded, fingerprint=ckpt.fingerprint, input_hash="abc"))
            skip, resumed = resolve_resume_skip(
                loaded, fingerprint=ckpt.fingerprint, input_hash="abc"
            )
            self.assertTrue(resumed)
            self.assertEqual(skip, 10)
            self.assertFalse(
                can_resume(loaded, fingerprint="deadbeef", input_hash="abc")
            )
            self.assertTrue(invalidate_checkpoint(root))
            self.assertIsNone(load_checkpoint(root))


class TestPublicComputeHonestyW173(unittest.TestCase):
    def test_public_job_lifts_compute_and_keeps_unmeasured_not_zero(self) -> None:
        from Data.modules.datasets.service import DatasetService
        from Data.modules.datasets.store import DatasetStore
        from Data.modules.datasets.types import DatasetJobStatus

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            db = root / "lev.db"
            corpus = _layout(root / "corpus")
            store = DatasetStore(db)
            store.initialize()
            service = DatasetService(
                store,
                corpus=corpus,
                settings=None,
                allowed_import_roots=[root, corpus.root],
            )
            path = root / "rows.jsonl"
            path.write_text(
                '{"id":"1","text":"a","metadata":{}}\n'
                '{"id":"2","text":"b","metadata":{}}\n',
                encoding="utf-8",
            )
            imported = service.import_local_sync(str(path), name="w173", materialize=True)
            ds_id = imported["dataset"]["datasetId"]
            ver = service.pick_usable_version(ds_id)
            self.assertIsNotNone(ver)
            assert ver is not None
            job = service.enqueue_validate(ds_id, ver.version_id)
            done = service.process_jobs(max_jobs=1)[0]
            self.assertEqual(done.job_id, job.job_id)
            self.assertEqual(done.status, DatasetJobStatus.COMPLETED)
            pub = service.public_job(done)
            self.assertIn(pub.get("backend"), {"PYTHON_STREAMING", "RUST_NATIVE", "python_streaming", "rust_native"})
            # Missing RSS must not become 0.
            peak = pub.get("peakRssBytes")
            if peak is None:
                self.assertNotEqual(peak, 0)
            else:
                self.assertNotEqual(peak, 0)
            compute = pub.get("compute") or {}
            self.assertIsInstance(compute, dict)
            peak_mem = compute.get("peakMemory")
            self.assertTrue(peak_mem is None or peak_mem == "UNMEASURED" or isinstance(peak_mem, (int, float)))
            if peak_mem == 0:
                self.fail("UNMEASURED coerced to 0")
            streaming = (done.checkpoint or {}).get("streaming")
            self.assertIsInstance(streaming, dict)


class TestNativeProbeW174(unittest.TestCase):
    def test_dashboard_exposes_native_compute_probe(self) -> None:
        from Data.modules.workers.dashboard import build_worker_fabric_dashboard

        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "lev.db"
            from Data.modules.workers.registry import WorkerRegistry

            WorkerRegistry(db).initialize()
            dash = build_worker_fabric_dashboard(db_path=db, include_resources=False)
            nc = dash.get("nativeCompute")
            self.assertIsInstance(nc, dict)
            self.assertIn("status", nc)
            self.assertIn("operations", nc)
            self.assertTrue(dash.get("truth", {}).get("native_compute_probed"))


class TestDbContentionW176(unittest.TestCase):
    def test_db_contention_snapshot_bounded_and_honest(self) -> None:
        from Data.modules.common.db_contention import UNMEASURED, db_contention_snapshot

        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "lev.db"
            db.write_bytes(b"")
            snap = db_contention_snapshot(db)
            self.assertIsInstance(snap, dict)
            for key in ("dbFileSize", "walSize", "busyRetries", "commitQueueDepth"):
                self.assertIn(key, snap)
                value = snap[key]
                self.assertTrue(
                    isinstance(value, (int, float)) or value == UNMEASURED,
                    msg=f"{key}={value!r}",
                )
            self.assertTrue(snap.get("truth", {}).get("unmeasuredIsNotZero"))
            self.assertNotEqual(snap.get("busyRetries"), None)


class TestReconstructStableDatasetW175(unittest.TestCase):
    def test_reconstruct_dataset_service_reads_stable_dataset(self) -> None:
        from Data.modules.datasets.service import DatasetService
        from Data.modules.datasets.store import DatasetStore

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            db = root / "lev.db"
            corpus = _layout(root / "corpus")
            store = DatasetStore(db)
            store.initialize()
            service = DatasetService(
                store,
                corpus=corpus,
                settings=None,
                allowed_import_roots=[root, corpus.root],
            )
            path = root / "stable.jsonl"
            path.write_text(
                '{"id":"1","text":"alpha","metadata":{}}\n'
                '{"id":"2","text":"beta","metadata":{}}\n',
                encoding="utf-8",
            )
            imported = service.import_local_sync(str(path), name="stable-w175", materialize=True)
            ds_id = imported["dataset"]["datasetId"]

            store2 = DatasetStore(db)
            store2.initialize()
            reconstructed = DatasetService(
                store2,
                corpus=corpus,
                settings=None,
                allowed_import_roots=[root, corpus.root],
            )
            ds = reconstructed.get_dataset(ds_id)
            self.assertEqual(ds.name, "stable-w175")
            ver = reconstructed.pick_usable_version(ds_id)
            self.assertIsNotNone(ver)
            assert ver is not None
            rows = list(reconstructed.iter_version_records(ver.version_id))
            self.assertGreaterEqual(len(rows), 2)


if __name__ == "__main__":
    unittest.main()
