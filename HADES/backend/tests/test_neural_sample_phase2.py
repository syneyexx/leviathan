"""Phase 2: Dataset Brain provenance, redaction, resume, cancel."""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from dataset_brain import brain_dir, write_manifest
from dataset_brain_worker import _HIDDEN_RECORD_KEYS, _mapping_fingerprint, _source_fingerprint
from neural.sample_job import NeuralSampleCompileJob
from neural.samples import (
    HIDDEN_RECORD_KEYS,
    NeuralSampleCompileCancelled,
    NeuralSampleCompileError,
    NeuralSampleCompiler,
)
from training_service import TrainingWorkspace


class NeuralSamplePhase2Tests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.training_root = self.root / "training"
        self.workspace = TrainingWorkspace(self.training_root)
        self.source = self.root / "source.jsonl"
        self.rows = [
            {
                "instruction": "Explain alphamarker",
                "output": "alphamarker uses local evidence.",
                "reasoning": "privatereasonmarker must never appear",
            },
            {"query": "Q1", "answer": "A1", "api_key": "super-secret-value-xyz"},
            {"text": "public text with api_key=super-secret-value-xyz embedded"},
            {"text": ""},
            {"problem_statement": "fix crash", "patch": "diff --git a/x"},
        ]
        self.source.write_text("".join(json.dumps(r) + "\n" for r in self.rows), encoding="utf-8")
        self.dataset = self.workspace.register_local(self.source, name="Neural Phase2")
        self.dataset_id = str(self.dataset["id"])
        self._materialize_brain()

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def _materialize_brain(self) -> None:
        """Write a completed Brain snapshot + manifest with real fingerprints."""
        dataset = self.workspace.get_dataset(self.dataset_id)
        source_fp = _source_fingerprint(dataset)
        mapping_fp = _mapping_fingerprint(dataset)
        snap = brain_dir(self.training_root, self.dataset_id) / "data.jsonl"
        snap.parent.mkdir(parents=True, exist_ok=True)
        # Snapshot stores raw rows (Brain materialization); compiler must sanitize.
        snap.write_text("".join(json.dumps(r) + "\n" for r in self.rows), encoding="utf-8")
        write_manifest(
            self.training_root,
            self.dataset_id,
            {
                "status": "ready",
                "materialized_complete": True,
                "materialized_rows": len(self.rows),
                "source_fingerprint": source_fp,
                "mapping_fingerprint": mapping_fp,
                "snapshot_path": str(snap),
                "snapshot_bytes": snap.stat().st_size,
                "indexed_rows": 0,
                "chunks_indexed": 0,
            },
        )

    def test_hidden_keys_match_dataset_brain_worker(self) -> None:
        self.assertEqual(HIDDEN_RECORD_KEYS, _HIDDEN_RECORD_KEYS)

    def test_from_dataset_brain_wires_provenance(self) -> None:
        compiler = NeuralSampleCompiler.from_dataset_brain(self.training_root, self.dataset_id)
        manifest = json.loads(
            (brain_dir(self.training_root, self.dataset_id) / "manifest.json").read_text(encoding="utf-8")
        )
        self.assertEqual(compiler.source_fingerprint, manifest["source_fingerprint"])
        self.assertEqual(compiler.mapping_fingerprint, manifest["mapping_fingerprint"])
        self.assertIsNotNone(compiler.brain_manifest_fp)
        samples = list(compiler.iter_snapshot(manifest["snapshot_path"]))
        self.assertGreaterEqual(len(samples), 3)
        blob = " ".join(s.text for s in samples)
        self.assertNotIn("privatereasonmarker", blob)
        self.assertTrue(all(s.source_fingerprint == manifest["source_fingerprint"] for s in samples))
        self.assertTrue(all(s.brain_manifest_fingerprint == compiler.brain_manifest_fp for s in samples))

    def test_redacts_secrets_like_dataset_brain(self) -> None:
        compiler = NeuralSampleCompiler.from_dataset_brain(self.training_root, self.dataset_id)
        snap = brain_dir(self.training_root, self.dataset_id) / "data.jsonl"
        texts = [s.text for s in compiler.iter_snapshot(snap)]
        joined = "\n".join(texts)
        self.assertNotIn("super-secret-value-xyz", joined)
        self.assertTrue(any("REDACTED" in t or "alphamarker" in t for t in texts))

    def test_incomplete_brain_rejected(self) -> None:
        write_manifest(
            self.training_root,
            self.dataset_id,
            {"materialized_complete": False, "status": "running"},
        )
        with self.assertRaises(NeuralSampleCompileError):
            NeuralSampleCompiler.from_dataset_brain(self.training_root, self.dataset_id)

    def test_mapping_drift_rejected(self) -> None:
        write_manifest(
            self.training_root,
            self.dataset_id,
            {"mapping_fingerprint": "not-the-real-fingerprint"},
        )
        with self.assertRaises(NeuralSampleCompileError) as ctx:
            NeuralSampleCompiler.from_dataset_brain(self.training_root, self.dataset_id)
        self.assertIn("mapping fingerprint", str(ctx.exception).lower())

    def test_compile_job_complete_stream(self) -> None:
        jobs = NeuralSampleCompileJob(self.root / "neural_jobs")
        job = jobs.create(training_root=self.training_root, dataset_id=self.dataset_id, checkpoint_every=1)
        done = jobs.run(job["id"])
        self.assertEqual(done["status"], "completed")
        self.assertGreaterEqual(done["samples_emitted"], 3)
        emitted = list(jobs.iter_emitted_samples(job["id"]))
        self.assertEqual(len(emitted), done["samples_emitted"])
        self.assertTrue(all("source_fingerprint" in row for row in emitted))
        joined = " ".join(row["text"] for row in emitted)
        self.assertNotIn("privatereasonmarker", joined)
        self.assertNotIn("super-secret-value-xyz", joined)

    def test_compile_job_resume_after_partial(self) -> None:
        jobs = NeuralSampleCompileJob(self.root / "neural_jobs")
        job = jobs.create(
            training_root=self.training_root,
            dataset_id=self.dataset_id,
            max_samples=2,
            checkpoint_every=1,
        )
        first = jobs.run(job["id"])
        self.assertEqual(first["status"], "completed")
        self.assertEqual(first["samples_emitted"], 2)
        last_row = int(first["last_row_index"])

        # Continue as a new logical resume by lifting max_samples and resetting status.
        jobs.write_job(
            job["id"],
            {
                "status": "queued",
                "max_samples": 100,
                "completed_at": None,
            },
        )
        second = jobs.run(job["id"])
        self.assertEqual(second["status"], "completed")
        self.assertGreater(second["samples_emitted"], first["samples_emitted"])
        self.assertGreaterEqual(int(second["last_row_index"]), last_row)
        # No duplicate sample_ids after resume.
        ids = [row["sample_id"] for row in jobs.iter_emitted_samples(job["id"])]
        self.assertEqual(len(ids), len(set(ids)))

    def test_compile_job_cancel(self) -> None:
        # Large enough that we can cancel mid-stream by pre-planting cancel file
        # after create and using a cancel_check that trips after first sample via
        # request_cancel from a wrapper: plant cancel before run with a custom path.
        jobs = NeuralSampleCompileJob(self.root / "neural_jobs_cancel")
        # Expand snapshot so cancel can interrupt.
        big_rows = [{"text": f"row-{i} content pad"} for i in range(200)]
        snap = Path(json.loads((brain_dir(self.training_root, self.dataset_id) / "manifest.json").read_text())["snapshot_path"])
        snap.write_text("".join(json.dumps(r) + "\n" for r in big_rows), encoding="utf-8")
        write_manifest(
            self.training_root,
            self.dataset_id,
            {
                "materialized_rows": len(big_rows),
                "snapshot_bytes": snap.stat().st_size,
                "materialized_complete": True,
            },
        )
        # Refresh fingerprints after snapshot rewrite — path/mtime may change source_fp.
        dataset = self.workspace.get_dataset(self.dataset_id)
        write_manifest(
            self.training_root,
            self.dataset_id,
            {
                "source_fingerprint": _source_fingerprint(dataset),
                "mapping_fingerprint": _mapping_fingerprint(dataset),
            },
        )

        job = jobs.create(
            training_root=self.training_root,
            dataset_id=self.dataset_id,
            checkpoint_every=1,
        )
        # Request cancel immediately; run should observe cancel.requested.
        jobs.request_cancel(job["id"])
        result = jobs.run(job["id"])
        self.assertEqual(result["status"], "cancelled")
        self.assertLess(int(result["samples_emitted"]), 200)

    def test_bounded_max_rows_does_not_scan_forever(self) -> None:
        compiler = NeuralSampleCompiler.from_dataset_brain(
            self.training_root,
            self.dataset_id,
            max_rows=2,
        )
        snap = brain_dir(self.training_root, self.dataset_id) / "data.jsonl"
        samples = list(compiler.iter_snapshot(snap))
        # At most two non-empty compiled rows from the first two readable lines.
        self.assertLessEqual(len(samples), 2)
        self.assertGreaterEqual(len(samples), 1)

    def test_iterator_cancel_raises(self) -> None:
        compiler = NeuralSampleCompiler.from_dataset_brain(self.training_root, self.dataset_id)
        snap = brain_dir(self.training_root, self.dataset_id) / "data.jsonl"
        calls = {"n": 0}

        def cancel_after_one() -> bool:
            calls["n"] += 1
            return calls["n"] > 1

        with self.assertRaises(NeuralSampleCompileCancelled):
            list(compiler.iter_snapshot(snap, cancel_check=cancel_after_one))


if __name__ == "__main__":
    unittest.main()
